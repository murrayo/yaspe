"""
Performance analysis module for yaspe.
Produces a narrative markdown summary from a SQLite database following
the methodology in docs/Performance analysis/PERFORMANCE_ANALYSIS.md.
Linux only.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import time as dtime
from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd


# 9 IRIS Health Monitor periods (per PERFORMANCE_ANALYSIS.md §2)
IRIS_PERIODS = [
    {"name": "00:15–02:45", "start": "00:15", "end": "02:45"},
    {"name": "03:00–06:00", "start": "03:00", "end": "06:00"},
    {"name": "06:15–08:45", "start": "06:15", "end": "08:45"},
    {"name": "09:00–11:30", "start": "09:00", "end": "11:30"},
    {"name": "11:45–13:15", "start": "11:45", "end": "13:15"},
    {"name": "13:30–16:00", "start": "13:30", "end": "16:00"},
    {"name": "16:15–18:00", "start": "16:15", "end": "18:00"},
    {"name": "18:15–20:45", "start": "18:15", "end": "20:45"},
    {"name": "21:00–23:59", "start": "21:00", "end": "23:59"},
]

# KPI thresholds (per PERFORMANCE_ANALYSIS.md §3)
# fixed_warn / fixed_alert: used directly (not baseline-relative)
# baseline_relative=True: alert/warn computed dynamically from mean/σ
METRIC_THRESHOLDS = {
    # vmstat — fixed thresholds
    "us_sy":    {"fixed_warn": 75.0,  "fixed_alert": 85.0,  "baseline_relative": False, "label": "us+sy (CPU %)"},
    "wa":       {"fixed_warn": 10.0,  "fixed_alert": 20.0,  "baseline_relative": False, "label": "wa (I/O wait %)"},
    "r":        {"fixed_warn": None,  "fixed_alert": None,   "baseline_relative": False, "vcpu_relative": True,  "label": "r (run queue)"},
    "b":        {"fixed_warn": 2.0,   "fixed_alert": None,   "baseline_relative": False, "vcpu_relative": True,  "label": "b (blocked)"},
    "sy_pct":   {"fixed_warn": 30.0,  "fixed_alert": 50.0,  "baseline_relative": False, "label": "sy (% of total CPU)"},
    "si":       {"fixed_warn": 0.0,   "fixed_alert": 0.0,   "baseline_relative": False, "label": "si (swap in)"},
    "so":       {"fixed_warn": 0.0,   "fixed_alert": 0.0,   "baseline_relative": False, "label": "so (swap out)"},
    # mgstat — baseline-relative
    "Glorefs":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Glorefs"},
    "Gloupds":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Gloupds"},
    "PhyRds":   {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "PhyRds"},
    "PhyWrs":   {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "PhyWrs"},
    "Jrnwrts":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Jrnwrts"},
    "WDQsz":    {"fixed_warn": 0.0,   "fixed_alert": 0.0,   "baseline_relative": False, "label": "WDQsz"},
    "Rdratio":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Rdratio", "invert": True},
    "RouLaS":   {"fixed_warn": 0.0,   "fixed_alert": None,  "baseline_relative": False, "label": "RouLaS"},
}

# Consecutive-readings rule
ALERT_CONSECUTIVE = 3   # samples above alert threshold = Red
WARN_CONSECUTIVE  = 5   # samples above warn threshold  = Yellow


def _fmt_n(value) -> str:
    """Format a number with thousands separator, no decimal places."""
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value)


@dataclass
class ChartRequest:
    metric: str
    title: str
    df: pd.DataFrame
    warn_level: float
    alert_level: float
    shading_spans: list          # list of (start_dt, end_dt) for abnormal run shading
    twin_metric: Optional[str]   # None, or name of second metric for twin-axis overlay
    twin_df: Optional[pd.DataFrame]
    output_dir: str
    filename: str                # no extension; .png appended by renderer


@dataclass
class Finding:
    metric: str
    severity: str                # "Red", "Yellow", "Green"
    observation: str             # prose: value, threshold, duration
    when: str                    # timestamps / recurrence pattern
    corroborating: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    next_step: str = ""
    chart_request: Optional[ChartRequest] = None


def _get_collection_meta(connection) -> dict:
    """
    Establish collection window, median interval, and gaps > 3× interval.
    Returns dict with keys: start, end, n_days, weekdays, interval_seconds, gaps.
    gaps is a list of (gap_start, gap_end) datetime tuples.
    """
    try:
        df = pd.read_sql_query(
            "SELECT RunDate, RunTime FROM mgstat ORDER BY RunDate, RunTime",
            connection,
        )
    except Exception:
        return {"start": None, "end": None, "n_days": 0, "weekdays": [],
                "interval_seconds": None, "gaps": []}

    if df.empty:
        return {"start": None, "end": None, "n_days": 0, "weekdays": [],
                "interval_seconds": None, "gaps": []}

    # Use the pre-computed 'datetime' column when available (yaspe stores it);
    # fall back to combining RunDate + RunTime with flexible parsing.
    if "datetime" in df.columns:
        df["dt"] = pd.to_datetime(df["datetime"].str.strip(), errors="coerce")
    else:
        df["dt"] = pd.to_datetime(
            df["RunDate"].str.strip() + " " + df["RunTime"].str.strip(),
            errors="coerce",
        )
    df = df.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)

    diffs = df["dt"].diff()
    interval_secs = diffs.median().total_seconds() if len(diffs) > 1 else None
    gap_threshold = timedelta(seconds=interval_secs * 3) if interval_secs else None

    gaps = []
    if gap_threshold:
        for i in range(1, len(df)):
            if diffs.iloc[i] > gap_threshold:
                gaps.append((df["dt"].iloc[i - 1], df["dt"].iloc[i]))

    start = df["dt"].min()
    end = df["dt"].max()
    # If end timestamp is exactly midnight (00:00:00) it belongs to the previous
    # day's collection window, not a new calendar day — avoid overcounting.
    end_date = end.date()
    if end.hour == 0 and end.minute == 0 and end.second == 0:
        end_date = (end - timedelta(seconds=1)).date()
    n_days = (end_date - start.date()).days + 1
    weekdays = sorted({ts.strftime("%A") for ts in df["dt"]})

    return {
        "start": start,
        "end": end,
        "n_days": n_days,
        "weekdays": weekdays,
        "interval_seconds": interval_secs,
        "gaps": gaps,
    }


def _get_system_facts(sp_dict: dict) -> dict:
    """
    Extract system facts from sp_dict (populated by sp_check.system_check()).
    Returns dict with: vcpus, ram_gb, iris_buffers_gb, customer, version, os.
    Missing values are None; customer defaults to "Unknown".
    """
    vcpus = None
    for key in ("number cpus",):
        if key in sp_dict:
            try:
                vcpus = int(str(sp_dict[key]).strip().split()[0])
            except (ValueError, IndexError):
                pass
            break

    ram_gb = None
    if "memory MB" in sp_dict:
        try:
            ram_gb = round(int(str(sp_dict["memory MB"]).strip()) / 1024)
        except (ValueError, TypeError):
            pass

    iris_buffers_gb = None
    if "globals total MB" in sp_dict:
        try:
            iris_buffers_gb = round(int(str(sp_dict["globals total MB"]).strip()) / 1024)
        except (ValueError, TypeError):
            pass

    return {
        "vcpus": vcpus,
        "ram_gb": ram_gb,
        "iris_buffers_gb": iris_buffers_gb,
        "customer": sp_dict.get("customer", "Unknown"),
        "version": sp_dict.get("version string"),
        "os": sp_dict.get("operating system", "Linux"),
    }


def _label_period(time_str: str) -> Optional[str]:
    """
    Map an HH:MM string to the matching IRIS Health Monitor period name.
    Returns None if outside all defined periods (e.g. 00:00–00:14).
    """
    h, m = int(time_str[:2]), int(time_str[3:5])
    t = dtime(h, m)
    for p in IRIS_PERIODS:
        sh, sm = int(p["start"][:2]), int(p["start"][3:])
        eh, em = int(p["end"][:2]), int(p["end"][3:])
        if dtime(sh, sm) <= t <= dtime(eh, em):
            return p["name"]
    return None


def _compute_baselines(df: pd.DataFrame, metrics: list) -> dict:
    """
    Compute per-period mean/σ/p95/max for each metric column in df.
    df must have a 'dt' column of datetime64.
    Returns: {period_name: {metric: {mean, sigma, p95, max}}}
    """
    df = df.copy()
    df["_period"] = df["dt"].dt.strftime("%H:%M").apply(_label_period)
    df = df.dropna(subset=["_period"])

    result = {}
    for period_name, group in df.groupby("_period"):
        result[period_name] = {}
        for metric in metrics:
            if metric not in group.columns:
                continue
            vals = pd.to_numeric(group[metric], errors="coerce").dropna()
            if vals.empty:
                continue
            result[period_name][metric] = {
                "mean":  float(vals.mean()),
                "sigma": float(vals.std(ddof=1)) if len(vals) > 1 else 0.0,
                "p95":   float(np.percentile(vals, 95)),
                "max":   float(vals.max()),
            }
    return result


def _find_breaches(
    values: pd.Series,
    datetimes: pd.Series,
    threshold: float,
    min_consecutive: int,
) -> list:
    """
    Find runs of consecutive samples above threshold.
    Returns list of (run_start, run_end, count) tuples.
    Only returns runs with length >= min_consecutive.
    """
    above = (values > threshold).values
    runs = []
    i = 0
    while i < len(above):
        if above[i]:
            j = i
            while j < len(above) and above[j]:
                j += 1
            run_len = j - i
            if run_len >= min_consecutive:
                runs.append((datetimes[i], datetimes[j - 1], run_len))
            i = j
        else:
            i += 1
    return runs


def _analyse_vmstat(df: pd.DataFrame, vcpus: Optional[int]) -> list:
    """
    Evaluate vmstat KPIs. Returns list[Finding] — one per metric that
    triggers Yellow or Red (plus Green summary if all clear).
    df must have columns: dt, wa, r, b, si, so, us, sy, id.
    """
    findings = []
    df = df.copy().sort_values("dt").reset_index(drop=True)

    def _fmt_ts(dt):
        return pd.Timestamp(dt).strftime("%Y-%m-%d %H:%M:%S")

    # --- wa (I/O wait) ---
    if "wa" in df.columns:
        vals = pd.to_numeric(df["wa"], errors="coerce").fillna(0)
        red_runs  = _find_breaches(vals, df["dt"], 20.0, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(vals, df["dt"], 10.0, WARN_CONSECUTIVE)
        interval_secs_wa = df["dt"].diff().median().total_seconds()
        if red_runs:
            start, end, count = red_runs[0]
            duration_s = count * interval_secs_wa
            findings.append(Finding(
                metric="wa (I/O wait %)",
                severity="Red",
                observation=f"wa exceeded 20% (alert) for {count} consecutive samples (~{duration_s:.0f}s). "
                            f"Peak: {vals.max():.1f}%. "
                            f"iostat device latency is required to confirm storage-side cause.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: storage latency — requires iostat await/svctm to confirm "
                            "(database/journal writes target 1–2 ms; wa alone does not prove latency)",
                            "hypothesis: excessive write-back I/O from dirty page flush"],
                next_step="Correlate with iostat await and queue depth. Check WDQsz and PhyWrs. "
                          "wa > 20% is significant but requires device-level confirmation.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            duration_s = count * interval_secs_wa
            findings.append(Finding(
                metric="wa (I/O wait %)",
                severity="Yellow",
                observation=f"wa exceeded 10% (warning) for {count} consecutive samples (~{duration_s:.0f}s). "
                            f"Peak: {vals.max():.1f}%. "
                            f"Possible intermittent I/O pressure — iostat needed to confirm.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: possible intermittent storage latency — "
                            "correlate with iostat await before concluding"],
                next_step="Check iostat device latency and queue depth during this window. "
                          "wa alone is insufficient to diagnose storage latency.",
                chart_request=None,
            ))

    # --- us+sy (total CPU) ---
    if "us" in df.columns and "sy" in df.columns:
        us_sy = pd.to_numeric(df["us"], errors="coerce").fillna(0) + \
                pd.to_numeric(df["sy"], errors="coerce").fillna(0)
        red_runs  = _find_breaches(us_sy, df["dt"], 85.0, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(us_sy, df["dt"], 75.0, WARN_CONSECUTIVE)
        interval_secs = df["dt"].diff().median().total_seconds()
        if red_runs:
            start, end, count = red_runs[0]
            duration_s = count * interval_secs
            findings.append(Finding(
                metric="us+sy (CPU %)",
                severity="Red",
                observation=f"us+sy exceeded 85% for {count} consecutive samples "
                            f"(~{duration_s:.0f}s). Peak: {us_sy.max():.1f}%. "
                            f"Verify duration and impact before treating as sustained pressure — "
                            f"a short burst during batch or report generation may be expected.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: CPU-bound workload burst (batch, report, or SQL) — correlate with Glorefs",
                            "hypothesis: runaway process — check run queue (r) and process list",
                            "hypothesis: VM CPU ready/steal — check steal time (st) if virtualised"],
                next_step="Correlate with Glorefs and run queue. If Glorefs is proportional: normal peak load. "
                          "If Glorefs is low: suspect a runaway process or external CPU consumer. "
                          "Check steal time (st) if virtualised. Use History Monitor for CPU/GloRefs trend.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            duration_s = count * interval_secs
            findings.append(Finding(
                metric="us+sy (CPU %)",
                severity="Yellow",
                observation=f"us+sy exceeded 75% for {count} consecutive samples (~{duration_s:.0f}s). "
                            f"Peak: {us_sy.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: elevated workload — correlate with Glorefs and run queue"],
                next_step="Monitor trend across collections. Check History Monitor CPU and GloRefs together.",
                chart_request=None,
            ))

    # --- sy as % of total CPU ---
    if "us" in df.columns and "sy" in df.columns:
        us_vals = pd.to_numeric(df["us"], errors="coerce").fillna(0)
        sy_vals = pd.to_numeric(df["sy"], errors="coerce").fillna(0)
        total = us_vals + sy_vals
        sy_pct = sy_vals.where(total > 0, 0) / total.where(total > 0, 1) * 100
        red_runs  = _find_breaches(sy_pct, df["dt"], 50.0, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(sy_pct, df["dt"], 30.0, WARN_CONSECUTIVE)
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="sy (% of total CPU)",
                severity="Red",
                observation=f"Kernel CPU exceeded 50% of total CPU for {count} consecutive samples. "
                            f"Peak sy fraction: {sy_pct.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: HugePages not configured — IRIS managing own TLB",
                            "hypothesis: NUMA cross-socket traffic",
                            "hypothesis: high interrupt/softirq rate"],
                next_step="Check HugePages configuration. Review /proc/interrupts during a repeat event.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="sy (% of total CPU)",
                severity="Yellow",
                observation=f"Kernel CPU exceeded 30% of total CPU for {count} consecutive samples.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: elevated system-call rate or kernel overhead"],
                next_step="Monitor; check HugePages setting.",
                chart_request=None,
            ))

    # --- r (run queue) — vCPU-relative ---
    if "r" in df.columns and vcpus is not None:
        r_vals = pd.to_numeric(df["r"], errors="coerce").fillna(0)
        alert_thr = vcpus * 2.0
        warn_thr  = vcpus * 1.0
        red_runs  = _find_breaches(r_vals, df["dt"], alert_thr, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(r_vals, df["dt"], warn_thr,  WARN_CONSECUTIVE)
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="r (run queue)",
                severity="Red",
                observation=f"Run queue exceeded {_fmt_n(alert_thr)} (2× vCPUs={vcpus}) for "
                            f"{count} consecutive samples. Peak: {_fmt_n(r_vals.max())}.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: CPU saturation — more runnable threads than cores"],
                next_step="Cross-reference with us+sy. If us+sy < 80%, suspect lock contention rather than CPU shortage.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="r (run queue)",
                severity="Yellow",
                observation=f"Run queue exceeded {_fmt_n(warn_thr)} (1× vCPUs={vcpus}) for {count} consecutive samples.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: intermittent CPU pressure"],
                next_step="Monitor trend.",
                chart_request=None,
            ))

    # --- si / so (swap) — any sustained = Red ---
    for col, label in (("si", "swap in (si)"), ("so", "swap out (so)")):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0)
            red_runs = _find_breaches(vals, df["dt"], 0.0, ALERT_CONSECUTIVE)
            if red_runs:
                start, end, count = red_runs[0]
                findings.append(Finding(
                    metric=label,
                    severity="Red",
                    observation=f"Sustained {col} > 0 for {count} consecutive samples — "
                                f"IRIS shared memory segment is paging. Peak: {_fmt_n(vals.max())} KB/s.",
                    when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                    hypotheses=["confirmed: memory pressure causing IRIS shared memory to page out"],
                    next_step="URGENT: Reduce global buffer allocation or add RAM. "
                              "Any sustained swap on a dedicated IRIS server is critical.",
                    chart_request=None,
                ))

    if not findings:
        findings.append(Finding(
            metric="vmstat (all)",
            severity="Green",
            observation="All vmstat metrics within normal thresholds for the collection window.",
            when="entire window",
        ))

    return findings


def _analyse_mgstat(df: pd.DataFrame, baselines: dict) -> list:
    """
    Evaluate mgstat KPIs. Returns list[Finding].
    df must have columns: dt, Glorefs, PhyRds, PhyWrs, Gloupds, Jrnwrts, WDQsz, Rdratio, RouLaS.
    Seize and ASeize are optional (not present in all pButtons files).
    baselines: output of _compute_baselines() for mgstat metrics.
    """
    findings = []
    df = df.copy().sort_values("dt").reset_index(drop=True)

    def _fmt_ts(dt):
        return pd.Timestamp(dt).strftime("%Y-%m-%d %H:%M:%S")

    def _dynamic_thresholds(metric, period_name):
        """Return (warn_level, alert_level) for a baseline-relative metric."""
        if period_name not in baselines or metric not in baselines.get(period_name, {}):
            return None, None
        b = baselines[period_name][metric]
        mean, sigma, highest = b["mean"], b["sigma"], b["max"]
        cfg = METRIC_THRESHOLDS.get(metric, {})
        warn_mult = cfg.get("warn_mult", 1.6)
        max_mult  = cfg.get("max_mult", 2.0)
        warn_level  = warn_mult  * max(mean, mean + 2 * sigma, highest)
        alert_level = max_mult   * max(mean + 3 * sigma, highest + sigma)
        return warn_level, alert_level

    # --- WDQsz ---
    # WDQsz is normally non-zero during a write daemon cycle and drains each cycle.
    # A finding requires either (a) a growing trend across multiple cycles or
    # (b) a sustained abnormally high level relative to the period baseline.
    if "WDQsz" in df.columns:
        vals = pd.to_numeric(df["WDQsz"], errors="coerce").fillna(0)
        nonzero = vals[vals > 0]
        if len(nonzero) >= WARN_CONSECUTIVE:
            # Check for growth: compare first-third vs last-third of non-zero values
            nz_idx = nonzero.index.tolist()
            third = max(1, len(nz_idx) // 3)
            first_mean = nonzero.iloc[:third].mean()
            last_mean  = nonzero.iloc[-third:].mean()
            growing = last_mean > first_mean * 1.5 and last_mean > first_mean + 100

            # Check for sustained abnormal level: mean > 2× p25 (persistently elevated)
            p25 = float(np.percentile(nonzero, 25))
            sustained = nonzero.mean() > p25 * 3 and p25 > 0

            if growing or sustained:
                peak = vals.max()
                if growing:
                    obs = (f"WDQsz grew from mean {_fmt_n(first_mean)} to {_fmt_n(last_mean)} across the window "
                           f"(peak {_fmt_n(peak)}) — queue is not draining between write daemon cycles.")
                else:
                    obs = (f"WDQsz was persistently elevated (mean {_fmt_n(nonzero.mean())}, "
                           f"peak {_fmt_n(peak)}) — not draining to zero between write daemon cycles.")
                start_dt = df["dt"].iloc[nz_idx[0]]
                end_dt   = df["dt"].iloc[nz_idx[-1]]
                findings.append(Finding(
                    metric="WDQsz (write daemon queue)",
                    severity="Yellow",
                    observation=obs,
                    when=f"{_fmt_ts(start_dt)} – {_fmt_ts(end_dt)}",
                    hypotheses=["hypothesis: write path (storage/WIJ/journal) latency preventing queue drain"],
                    next_step="Correlate with wa and PhyWrs. Check WD cycle time; any cycle ≥ 90 s is critical.",
                    chart_request=None,
                ))

    # --- RouLaS (column name is capitalised S in pButtons schema) ---
    # Only flag if it occurs during business hours (08:00–18:00) to avoid
    # overnight/startup transients being misread as a sizing problem.
    roul_col = "RouLaS" if "RouLaS" in df.columns else "RouLas" if "RouLas" in df.columns else None
    if roul_col:
        vals = pd.to_numeric(df[roul_col], errors="coerce").fillna(0)
        bh_mask = df["dt"].dt.hour.between(8, 17)
        bh_vals = vals[bh_mask].reset_index(drop=True)
        bh_dts  = df["dt"][bh_mask].reset_index(drop=True)
        warn_runs = _find_breaches(bh_vals, bh_dts, 0.0, WARN_CONSECUTIVE) if not bh_vals.empty else []
        if warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="RouLaS (routine cache misses)",
                severity="Yellow",
                observation=f"RouLaS was non-zero during business hours for {count} consecutive samples "
                            f"(max {_fmt_n(bh_vals.max())}). Routine cache misses during production workload — "
                            f"may indicate routine buffer is undersized.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: routine buffer (routines= in CPF) too small for working set during peak"],
                next_step="Review routines= setting in CPF. Only increase if misses persist across multiple "
                          "business-hours collections — transient startup/batch activity is normal.",
                chart_request=None,
            ))

    # --- Baseline-relative metrics: Glorefs, PhyRds, PhyWrs, Gloupds, Jrnwrts ---
    for metric in ("Glorefs", "PhyRds", "PhyWrs", "Gloupds", "Jrnwrts"):
        if metric not in df.columns:
            continue
        vals = pd.to_numeric(df[metric], errors="coerce").fillna(0)
        df["_period_tmp"] = df["dt"].dt.strftime("%H:%M").apply(_label_period)

        period_findings = []
        for period_name, group_idx in df.groupby("_period_tmp").groups.items():
            group_vals = vals.iloc[group_idx]
            group_dts  = df["dt"].iloc[group_idx]
            warn_level, alert_level = _dynamic_thresholds(metric, period_name)
            if warn_level is None:
                continue
            red_runs  = _find_breaches(group_vals, group_dts, alert_level, ALERT_CONSECUTIVE)
            warn_runs = _find_breaches(group_vals, group_dts, warn_level,  WARN_CONSECUTIVE)
            if red_runs:
                start, end, count = red_runs[0]
                period_findings.append(Finding(
                    metric=metric,
                    severity="Red",
                    observation=f"{metric} exceeded alert level {_fmt_n(alert_level)} "
                                f"(2× period norm) for {count} consecutive samples. "
                                f"Peak: {_fmt_n(group_vals.max())}.",
                    when=f"{_fmt_ts(start)} – {_fmt_ts(end)} ({period_name})",
                    hypotheses=[f"hypothesis: abnormal workload spike in {metric}"],
                    next_step=f"Correlate with vmstat and other mgstat metrics in the same window.",
                    chart_request=None,
                ))
            elif warn_runs:
                start, end, count = warn_runs[0]
                period_findings.append(Finding(
                    metric=metric,
                    severity="Yellow",
                    observation=f"{metric} exceeded warning level {_fmt_n(warn_level)} "
                                f"(1.6× period norm) for {count} consecutive samples. "
                                f"Peak: {_fmt_n(group_vals.max())}.",
                    when=f"{_fmt_ts(start)} – {_fmt_ts(end)} ({period_name})",
                    hypotheses=[f"hypothesis: elevated {metric} during {period_name}"],
                    next_step="Monitor trend across multiple days.",
                    chart_request=None,
                ))
        findings.extend(period_findings)

    if not findings:
        findings.append(Finding(
            metric="mgstat (all)",
            severity="Green",
            observation="All mgstat metrics within normal thresholds for the collection window.",
            when="entire window",
        ))

    return findings


# ---------------------------------------------------------------------------
# Task 7: cross-signal correlation tests
# ---------------------------------------------------------------------------

def _nearest_join(mgstat_df: pd.DataFrame, vmstat_df: pd.DataFrame,
                  interval_secs: float) -> pd.DataFrame:
    """Merge mgstat and vmstat on nearest timestamp within 1.5× interval."""
    tolerance = pd.Timedelta(seconds=interval_secs * 1.5)
    mg = mgstat_df.sort_values("dt").reset_index(drop=True)
    vm = vmstat_df.sort_values("dt").reset_index(drop=True)
    merged = pd.merge_asof(mg, vm, on="dt", tolerance=tolerance,
                           direction="nearest", suffixes=("", "_vm"))
    return merged


def _test_user_stall(df: pd.DataFrame) -> Optional[Finding]:
    """
    Test 1: Glorefs drops sharply in business hours.
    df is a merged vmstat+mgstat DataFrame with 'dt', 'Glorefs', 'WDQsz', 'b', 'wa'.
    Business hours = 08:00–18:00.
    """
    bh = df[df["dt"].dt.hour.between(8, 17)].copy()
    if bh.empty or "Glorefs" not in bh.columns:
        return None

    glorefs = pd.to_numeric(bh["Glorefs"], errors="coerce").dropna()
    if glorefs.empty:
        return None

    mean_g = glorefs.mean()
    # A stall = at least 3 consecutive samples below 5% of mean
    stall_threshold = mean_g * 0.05
    if stall_threshold < 1:
        return None

    stall_runs = _find_breaches(-glorefs, bh["dt"].reset_index(drop=True),
                                threshold=-stall_threshold, min_consecutive=ALERT_CONSECUTIVE)

    if not stall_runs:
        return None

    start, end, count = stall_runs[0]
    # Check corroborating evidence
    window = bh[(bh["dt"] >= start) & (bh["dt"] <= end)]
    wa_elevated = "wa" in window.columns and pd.to_numeric(window["wa"], errors="coerce").mean() > 10
    wdqsz_elevated = "WDQsz" in window.columns and pd.to_numeric(window["WDQsz"], errors="coerce").max() > 0

    corroborating = []
    if wa_elevated:
        corroborating.append(f"wa elevated ({pd.to_numeric(window['wa'], errors='coerce').mean():.1f}%) during stall — storage-side cause likely")
    if wdqsz_elevated:
        corroborating.append(f"WDQsz non-zero during stall — write daemon queue backing up")
    if not corroborating:
        corroborating.append("wa and WDQsz within normal range — upstream/application-side cause possible")

    return Finding(
        metric="Glorefs (user stall)",
        severity="Red",
        observation=f"Glorefs dropped to near zero (< 5% of mean {_fmt_n(mean_g)}) in business hours "
                    f"for {count} consecutive samples — potential user-visible stall.",
        when=f"{pd.Timestamp(start).strftime('%Y-%m-%d %H:%M:%S')} – "
             f"{pd.Timestamp(end).strftime('%Y-%m-%d %H:%M:%S')}",
        corroborating=corroborating,
        hypotheses=(["confirmed: storage-side stall (wa + WDQsz corroborate)"]
                    if wa_elevated or wdqsz_elevated
                    else ["hypothesis: application-side stall (no storage indicators)"]),
        next_step="Capture ^SystemPerformance during a recurrence. "
                  "Check storage latency with iostat -x during the window.",
        chart_request=None,
    )


def _test_buffer_pressure(df: pd.DataFrame) -> Optional[Finding]:
    """
    Test 2: Rdratio trending down while PhyRds trends up.
    Quantify first-third vs last-third of window.
    """
    if "Rdratio" not in df.columns or "PhyRds" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 9:
        return None

    third = n // 3
    rdratio = pd.to_numeric(df["Rdratio"], errors="coerce").fillna(0)
    phyrds  = pd.to_numeric(df["PhyRds"],  errors="coerce").fillna(0)

    rd_first = rdratio.iloc[:third].mean()
    rd_last  = rdratio.iloc[2*third:].mean()
    ph_first = phyrds.iloc[:third].mean()
    ph_last  = phyrds.iloc[2*third:].mean()

    rdratio_declined = rd_last < rd_first * 0.85   # > 15% decline
    phyrds_increased = ph_last > ph_first * 1.20   # > 20% increase

    if not (rdratio_declined and phyrds_increased):
        return None

    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    return Finding(
        metric="Rdratio / PhyRds (buffer pool pressure)",
        severity="Yellow",
        observation=f"Rdratio declined from {rd_first:.1f}% to {rd_last:.1f}% "
                    f"({(rd_last - rd_first) / rd_first * 100:.1f}% change) while PhyRds "
                    f"increased from {ph_first:.1f} to {ph_last:.1f} over the collection window.",
        when=f"{start_ts} – {end_ts}",
        corroborating=["Rdratio decline and PhyRds increase are anti-correlated, consistent with buffer pressure"],
        hypotheses=["hypothesis: global buffer working set is growing beyond allocated size — "
                    "buffers are undersized for current workload"],
        next_step="Review globals= setting in CPF. If Rdratio trend continues across multiple "
                  "collections, increase global buffers (if RAM allows).",
        chart_request=None,
    )


def _test_write_daemon_strain(df: pd.DataFrame) -> Optional[Finding]:
    """Test 3: WDQsz non-zero between cycles + rising wa."""
    if "WDQsz" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    wdqsz = pd.to_numeric(df["WDQsz"], errors="coerce").fillna(0)
    warn_runs = _find_breaches(wdqsz, df["dt"], 0.0, WARN_CONSECUTIVE)
    if not warn_runs:
        return None

    start, end, count = warn_runs[0]
    window = df[(df["dt"] >= start) & (df["dt"] <= end)]
    wa_mean = pd.to_numeric(window.get("wa", pd.Series([0])), errors="coerce").mean()

    if wa_mean < 5.0:
        return None

    return Finding(
        metric="WDQsz + wa (write daemon strain)",
        severity="Yellow",
        observation=f"WDQsz non-zero for {count} consecutive samples with concurrent wa={wa_mean:.1f}% — "
                    f"write path under strain.",
        when=f"{pd.Timestamp(start).strftime('%Y-%m-%d %H:%M:%S')} – "
             f"{pd.Timestamp(end).strftime('%Y-%m-%d %H:%M:%S')}",
        corroborating=[f"wa averaged {wa_mean:.1f}% during WDQsz event"],
        hypotheses=["hypothesis: storage write latency causing write daemon queue growth",
                    "hypothesis: WIJ or journal device saturated"],
        next_step="Check iostat await on WIJ and journal devices during recurrence.",
        chart_request=None,
    )


def _test_memory_danger(df: pd.DataFrame) -> Optional[Finding]:
    """Test 4: free trending down + cache shrinking + any si/so."""
    if "free" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 6:
        return None

    free  = pd.to_numeric(df["free"],  errors="coerce").fillna(0)
    cache = pd.to_numeric(df.get("cache", pd.Series([float("nan")] * n)), errors="coerce")
    si    = pd.to_numeric(df.get("si",    pd.Series([0.0] * n)),           errors="coerce").fillna(0)
    so    = pd.to_numeric(df.get("so",    pd.Series([0.0] * n)),           errors="coerce").fillna(0)

    third = n // 3
    free_declining  = free.iloc[2*third:].mean() < free.iloc[:third].mean() * 0.80
    cache_shrinking = (not cache.isna().all()) and cache.iloc[2*third:].mean() < cache.iloc[:third].mean() * 0.85
    any_swap = (si > 0).any() or (so > 0).any()

    if not (free_declining and any_swap):
        return None

    severity = "Red" if any_swap else "Yellow"
    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    corroborating = []
    if cache_shrinking:
        corroborating.append("Page cache is also shrinking — kernel reclaiming memory")
    if any_swap:
        corroborating.append("Swap activity detected — memory pressure is confirmed")

    return Finding(
        metric="free / cache / swap (memory danger)",
        severity=severity,
        observation=f"Free memory declined {_fmt_n(free.iloc[:third].mean())} → {_fmt_n(free.iloc[2*third:].mean())} KB "
                    f"over the collection window" +
                    (" with concurrent swap activity." if any_swap else "."),
        when=f"{start_ts} – {end_ts}",
        corroborating=corroborating,
        hypotheses=["hypothesis: memory leak or growing resident set in IRIS or companion processes",
                    "hypothesis: insufficient RAM for configured IRIS global buffers + OS overhead"],
        next_step="URGENT if swap is active: reduce global buffers or add RAM. "
                  "Monitor free memory trend across collections.",
        chart_request=None,
    )


def _test_contention_vs_throughput(df: pd.DataFrame) -> Optional[Finding]:
    """Test 5: ASeize fraction rising relative to Seizes."""
    if "Seize" not in df.columns or "ASeize" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 9:
        return None

    seize  = pd.to_numeric(df["Seize"],  errors="coerce").fillna(0)
    aseize = pd.to_numeric(df["ASeize"], errors="coerce").fillna(0)

    fraction = aseize.where(seize > 0, 0) / seize.where(seize > 0, 1) * 100
    third = n // 3
    frac_first = fraction.iloc[:third].mean()
    frac_last  = fraction.iloc[2*third:].mean()

    if frac_last < 5.0 or frac_last < frac_first * 1.5:
        return None

    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    return Finding(
        metric="ASeize/Seize (lock contention)",
        severity="Yellow",
        observation=f"ASeize fraction rose from {frac_first:.1f}% to {frac_last:.1f}% of Seizes — "
                    f"genuine lock contention increasing, not just throughput scaling.",
        when=f"{start_ts} – {end_ts}",
        corroborating=["Seize is rising in proportion but ASeize fraction is also rising — contention, not scaling"],
        hypotheses=["hypothesis: lock table pressure — review locksiz in CPF",
                    "hypothesis: application-level contention on a shared resource"],
        next_step="Review locksiz setting. Capture ^SystemPerformance lock analysis during peak.",
        chart_request=None,
    )


def _test_kernel_overhead(df: pd.DataFrame) -> Optional[Finding]:
    """Test 6: sy growing relative to us at similar Glorefs."""
    if "us" not in df.columns or "sy" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 9:
        return None

    us = pd.to_numeric(df["us"], errors="coerce").fillna(0)
    sy = pd.to_numeric(df["sy"], errors="coerce").fillna(0)
    total = us + sy
    sy_frac = sy.where(total > 0, 0) / total.where(total > 0, 1)

    third = n // 3
    sf_first = sy_frac.iloc[:third].mean()
    sf_last  = sy_frac.iloc[2*third:].mean()

    glorefs = pd.to_numeric(df.get("Glorefs", pd.Series([1.0] * n)), errors="coerce").fillna(1)
    gl_first = glorefs.iloc[:third].mean()
    gl_last  = glorefs.iloc[2*third:].mean()
    glorefs_stable = abs(gl_last - gl_first) / (gl_first + 1) < 0.20

    if not (glorefs_stable and sf_last > sf_first * 1.5 and sf_last > 0.30):
        return None

    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    return Finding(
        metric="sy/us ratio (kernel overhead)",
        severity="Yellow",
        observation=f"Kernel CPU fraction grew from {sf_first*100:.1f}% to {sf_last*100:.1f}% of total CPU "
                    f"while Glorefs remained stable ({_fmt_n(gl_first)} → {_fmt_n(gl_last)}) — "
                    f"increasing kernel overhead not explained by workload growth.",
        when=f"{start_ts} – {end_ts}",
        corroborating=["Glorefs stable — workload not increasing, so sy growth is not proportional"],
        hypotheses=["hypothesis: HugePages not configured — IRIS managing its own TLB misses",
                    "hypothesis: NUMA cross-socket memory traffic",
                    "hypothesis: growing interrupt or softirq load (network/storage driver)"],
        next_step="Verify HugePages configuration. Check /proc/interrupts for growth on specific IRQs.",
        chart_request=None,
    )


def _attach_chart_requests(
    findings: list,
    metric_df_map: dict,
    output_dir: str,
) -> list:
    """
    For each Yellow/Red finding, populate finding.chart_request if a matching
    DataFrame is available in metric_df_map (keyed by finding.metric).
    Green findings are left unchanged.
    """
    updated = []
    for f in findings:
        if f.severity in ("Yellow", "Red") and f.metric in metric_df_map:
            df = metric_df_map[f.metric]
            thresh = METRIC_THRESHOLDS.get(f.metric.split()[0], {})
            warn_level  = thresh.get("fixed_warn", 0.0) or 0.0
            alert_level = thresh.get("fixed_alert", 0.0) or 0.0
            safe_name = f.metric.replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
            f.chart_request = ChartRequest(
                metric=f.metric,
                title=f.metric,
                df=df,
                warn_level=float(warn_level),
                alert_level=float(alert_level),
                shading_spans=[],
                twin_metric=None,
                twin_df=None,
                output_dir=output_dir,
                filename=f"{safe_name}_finding",
            )
        updated.append(f)
    return updated


def _write_report(
    meta: dict,
    facts: dict,
    findings: list,
    baselines: dict,
    context: Optional[str],
    output_dir: str,
) -> str:
    """
    Write the 7-section narrative markdown report.
    Returns the path to the written file.
    """
    start = meta.get("start")
    end   = meta.get("end")
    start_str = start.strftime("%Y-%m-%d") if start else "unknown"
    end_str   = end.strftime("%Y-%m-%d")   if end   else "unknown"

    filename = f"performance_summary_{start_str}_{end_str}.md"
    filepath = os.path.join(output_dir, filename)

    red_findings    = [f for f in findings if f.severity == "Red"]
    yellow_findings = [f for f in findings if f.severity == "Yellow"]
    green_findings  = [f for f in findings if f.severity == "Green"]

    if red_findings:
        overall = "Red"
    elif yellow_findings:
        overall = "Yellow"
    else:
        overall = "Green"

    context_line = context or "Routine health check — no specific context provided."

    customer    = facts.get("customer", "Unknown")
    vcpus       = facts.get("vcpus")
    ram_gb      = facts.get("ram_gb")
    buffers_gb  = facts.get("iris_buffers_gb")
    version     = facts.get("version", "")
    interval    = meta.get("interval_seconds")
    n_days      = meta.get("n_days", 1)
    weekdays    = meta.get("weekdays", [])
    gaps        = meta.get("gaps", [])

    vcpu_str    = str(vcpus) if vcpus else "unknown (assumption: check sp_check output)"
    ram_str     = f"{ram_gb} GB" if ram_gb else "unknown"
    buf_str     = f"{buffers_gb} GB" if buffers_gb else "unknown"
    interval_str = f"{interval:.0f}s" if interval else "unknown"

    lines = []

    # 1. Executive summary
    top_findings = (red_findings + yellow_findings)[:2]
    top_text = (
        " ".join(f.observation.split(". ")[0] + "." for f in top_findings)
        if top_findings
        else "No anomalies detected."
    )
    urgent = any(f.severity == "Red" for f in findings)
    urgency_text = "Immediate review recommended." if urgent else "No urgent action required."

    lines += [
        f"# Performance Summary: {customer}",
        f"",
        f"**Collection:** {start_str} - {end_str}  ",
        f"**Context:** {context_line}  ",
        f"**Generated by:** yaspe `--analysis`",
        f"",
        f"---",
        f"",
        f"## 1. Executive Summary",
        f"",
        f"Overall health: **{overall}**. {top_text} {urgency_text}",
        f"",
    ]

    # 2. Collection overview
    lines += [
        f"## 2. Collection Overview",
        f"",
        f"| Item | Value |",
        f"|---|---|",
        f"| Customer / hostname | {customer} |",
        f"| IRIS version | {version or 'not captured'} |",
        f"| Collection window | {start_str} {start.strftime('%H:%M') if start else ''} - "
        f"{end_str} {end.strftime('%H:%M') if end else ''} |",
        f"| Days covered | {n_days} ({', '.join(weekdays)}) |",
        f"| Median sample interval | {interval_str} |",
        f"| vCPUs | {vcpu_str} |",
        f"| RAM | {ram_str} |",
        f"| IRIS global buffers | {buf_str} |",
        f"",
    ]

    if gaps:
        lines.append("**Data quality — collection gaps (> 3x interval):**")
        lines.append("")
        for g_start, g_end in gaps:
            lines.append(f"- {pd.Timestamp(g_start).strftime('%Y-%m-%d %H:%M:%S')} - "
                         f"{pd.Timestamp(g_end).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("Gaps are not interpolated. Statistics within gap windows may be unreliable.")
        lines.append("")
    else:
        lines += ["No collection gaps detected.", ""]

    # 3. Workload profile
    lines += [f"## 3. Workload Profile", f""]
    if baselines:
        lines += [
            "Per-period peak Glorefs and Gloupds:",
            "",
            "| Period | Peak Glorefs | Peak Gloupds |",
            "|---|---|---|",
        ]
        for period in IRIS_PERIODS:
            pname = period["name"]
            if pname in baselines:
                gl = baselines[pname].get("Glorefs", {}).get("max", "-")
                gu = baselines[pname].get("Gloupds", {}).get("max", "-")
                gl_str = _fmt_n(gl) if isinstance(gl, float) else str(gl)
                gu_str = _fmt_n(gu) if isinstance(gu, float) else str(gu)
                lines.append(f"| {pname} | {gl_str} | {gu_str} |")
        lines.append("")
    else:
        lines += ["Workload profile data not available.", ""]

    # 4. Findings
    lines += ["## 4. Findings", ""]

    ordered_findings = red_findings + yellow_findings
    if not ordered_findings:
        lines += ["No Yellow or Red findings. System health is **Green** for this collection window.", ""]
    else:
        for i, f in enumerate(ordered_findings, 1):
            badge = "Red" if f.severity == "Red" else "Yellow"
            lines += [
                f"### Finding {i}: {badge} — {f.metric}",
                f"",
                f"**Observed:** {f.observation}",
                f"",
                f"**When:** {f.when}",
                f"",
            ]
            if f.corroborating:
                lines.append("**Corroborating metrics:**")
                lines.append("")
                for c in f.corroborating:
                    lines.append(f"- {c}")
                lines.append("")
            if f.hypotheses:
                lines.append("**Hypotheses (ranked):**")
                lines.append("")
                for h in f.hypotheses:
                    lines.append(f"1. {h}")
                lines.append("")
            if f.next_step:
                lines += [f"**Next step:** {f.next_step}", ""]
            if f.chart_request:
                chart_path = os.path.join(f.chart_request.output_dir, f"{f.chart_request.filename}.png")
                rel_path = os.path.relpath(chart_path, output_dir)
                lines += [f"![{f.metric} chart]({rel_path})", ""]

    # 5. Explainable anomalies
    batch = next((f for f in findings if "batch" in f.metric.lower() and f.severity == "Green"), None)
    lines += ["## 5. Explainable Anomalies", ""]
    if batch:
        lines += [f"**Batch/backup window:** {batch.observation}", ""]
    else:
        lines += ["No explainable anomalies identified outside of findings above.", ""]

    # 6. Baseline table
    lines += ["## 6. Baseline Table", ""]
    if baselines:
        all_metrics = set()
        for p in baselines.values():
            all_metrics.update(p.keys())
        all_metrics = sorted(all_metrics)

        lines += [
            "Per-period mean / σ / p95 for baseline-relative metrics. "
            "Where σ > mean the distribution is highly skewed — use p95 rather than mean for capacity assessment. "
            "Rows marked † have σ > mean for at least one metric.",
            "",
        ]

        header = "| Period | " + " | ".join(f"{m} mean / σ / p95" for m in all_metrics) + " |"
        sep    = "|---|" + "---|" * len(all_metrics)
        lines += [header, sep]

        for period in IRIS_PERIODS:
            pname = period["name"]
            if pname not in baselines:
                continue
            high_var = any(
                baselines[pname][m]["sigma"] > baselines[pname][m]["mean"]
                for m in all_metrics
                if m in baselines[pname] and baselines[pname][m]["mean"] > 0
            )
            row = f"| {pname}{'†' if high_var else ''} |"
            for m in all_metrics:
                if m in baselines[pname]:
                    b = baselines[pname][m]
                    row += f" {_fmt_n(b['mean'])} / {_fmt_n(b['sigma'])} / {_fmt_n(b['p95'])} |"
                else:
                    row += " - |"
            lines.append(row)
        lines.append("")
    else:
        lines += ["Baseline data not available.", ""]

    # 7. Appendix
    lines += [
        "## 7. Appendix: SQL Queries",
        "",
        "Queries used to produce this report:",
        "",
        "```sql",
        "-- mgstat data",
        "SELECT RunDate, RunTime, Glorefs, PhyRds, PhyWrs, Gloupds, Jrnwrts,",
        "       WDQsz, Rdratio, RouLaS, Seize, ASeize FROM mgstat",
        "ORDER BY RunDate, RunTime;",
        "",
        "-- vmstat data",
        "SELECT RunDate, RunTime, r, b, swpd, free, buff, cache,",
        '       si, so, bi, bo, "in", cs, us, sy, id, wa, st FROM vmstat',
        "ORDER BY RunDate, RunTime;",
        "```",
        "",
    ]

    # Caveat
    lines += [
        "---",
        "",
        "> **Disclaimer:** These explanations are general guidance for InterSystems IRIS and Linux environments. "
        "They are not universal recommendations. Validate changes against the application workload, "
        "IRIS version, operating system, storage platform, and support requirements before implementation.",
        "",
    ]

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return filepath


def run_analysis(
    connection,
    sp_dict: dict,
    output_prefix: str,
    filepath: str,
    context: Optional[str] = None,
    png_out: bool = False,
) -> tuple:
    """
    Public entry point. Run full performance analysis.

    Returns (markdown_path, chart_requests) where:
      markdown_path  — path to the written .md file
      chart_requests — list[ChartRequest] for Yellow/Red findings (empty if all Green)
    """
    meta  = _get_collection_meta(connection)
    facts = _get_system_facts(sp_dict)

    # Load vmstat and mgstat DataFrames
    try:
        mg_raw = pd.read_sql_query("SELECT * FROM mgstat", connection)
        mg_raw.dropna(subset=["RunDate", "RunTime"], inplace=True)
        if "datetime" in mg_raw.columns:
            mg_raw["dt"] = pd.to_datetime(mg_raw["datetime"].str.strip(), errors="coerce")
        else:
            mg_raw["dt"] = pd.to_datetime(
                mg_raw["RunDate"].str.strip() + " " + mg_raw["RunTime"].str.strip(),
                errors="coerce",
            )
        mg_df = mg_raw.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    except Exception:
        mg_df = pd.DataFrame()

    try:
        vm_raw = pd.read_sql_query("SELECT * FROM vmstat", connection)
        vm_raw.dropna(subset=["RunDate", "RunTime"], inplace=True)
        if "datetime" in vm_raw.columns:
            vm_raw["dt"] = pd.to_datetime(vm_raw["datetime"].str.strip(), errors="coerce")
        else:
            vm_raw["dt"] = pd.to_datetime(
                vm_raw["RunDate"].str.strip() + " " + vm_raw["RunTime"].str.strip(),
                errors="coerce",
            )
        vm_df = vm_raw.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    except Exception:
        vm_df = pd.DataFrame()

    # Compute baselines from mgstat
    mgstat_metrics = [m for m in ("Glorefs","PhyRds","PhyWrs","Gloupds","Jrnwrts","Rdratio")
                      if not mg_df.empty and m in mg_df.columns]
    baselines = _compute_baselines(mg_df, mgstat_metrics) if not mg_df.empty else {}

    # Per-metric analysis
    vcpus = facts.get("vcpus")
    all_findings = []

    if not vm_df.empty:
        all_findings.extend(_analyse_vmstat(vm_df, vcpus=vcpus))

    if not mg_df.empty:
        all_findings.extend(_analyse_mgstat(mg_df, baselines))

    # Correlation tests
    if not mg_df.empty and not vm_df.empty:
        interval = meta.get("interval_seconds") or 30.0
        joined = _nearest_join(mg_df, vm_df, interval)
        for test_fn in (
            _test_user_stall,
            _test_buffer_pressure,
            _test_write_daemon_strain,
            _test_memory_danger,
            _test_contention_vs_throughput,
            _test_kernel_overhead,
            _test_batch_window,
        ):
            try:
                result = test_fn(joined)
                if result is not None:
                    all_findings.append(result)
            except Exception:
                pass
    elif not mg_df.empty:
        for test_fn in (_test_buffer_pressure, _test_write_daemon_strain,
                        _test_contention_vs_throughput, _test_batch_window):
            try:
                result = test_fn(mg_df)
                if result is not None:
                    all_findings.append(result)
            except Exception:
                pass

    # Build metric_df_map for chart attachment
    metric_df_map = {}
    if not vm_df.empty:
        for col in ("wa", "r", "b", "si", "so"):
            if col in vm_df.columns:
                key = next((f.metric for f in all_findings if f.metric.startswith(col)), None)
                if key:
                    sub = vm_df[["dt", col]].rename(columns={col: "metric"})
                    metric_df_map[key] = sub
    if not mg_df.empty:
        for col in ("WDQsz", "RouLaS", "Glorefs", "PhyRds", "PhyWrs", "Jrnwrts"):
            if col in mg_df.columns:
                key = next((f.metric for f in all_findings if col in f.metric), None)
                if key:
                    sub = mg_df[["dt", col]].rename(columns={col: "metric"})
                    metric_df_map[key] = sub

    analysis_dir = os.path.join(filepath, f"{output_prefix}analysis_metrics")
    os.makedirs(analysis_dir, exist_ok=True)

    all_findings = _attach_chart_requests(all_findings, metric_df_map, analysis_dir)

    md_path = _write_report(
        meta=meta,
        facts=facts,
        findings=all_findings,
        baselines=baselines,
        context=context,
        output_dir=filepath,
    )

    chart_requests = [f.chart_request for f in all_findings if f.chart_request is not None]
    return md_path, chart_requests


def _test_batch_window(df: pd.DataFrame) -> Optional[Finding]:
    """
    Test 7: Identify overnight PhyWrs/Jrnwrts surge.
    Alert if it overlaps with business hours (08:00+).
    """
    if "PhyWrs" not in df.columns and "Jrnwrts" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)

    overnight = df[df["dt"].dt.hour.between(0, 6)].copy()
    business  = df[df["dt"].dt.hour.between(8, 9)].copy()

    if overnight.empty:
        return None

    phywrs  = pd.to_numeric(df.get("PhyWrs",  pd.Series([0.0]*len(df))), errors="coerce").fillna(0)
    jrnwrts = pd.to_numeric(df.get("Jrnwrts", pd.Series([0.0]*len(df))), errors="coerce").fillna(0)

    overnight_pw  = pd.to_numeric(overnight.get("PhyWrs",  pd.Series([0.0])), errors="coerce").mean()
    business_pw   = pd.to_numeric(business.get("PhyWrs",   pd.Series([0.0])), errors="coerce").mean() if not business.empty else 0
    overall_pw    = phywrs.mean()

    # Batch window exists if overnight writes are >2× overall mean
    if overnight_pw < overall_pw * 2.0:
        return None

    # Only a finding if it overlaps business hours
    overlap = business_pw > overnight_pw * 0.5

    severity = "Yellow" if overlap else "Green"
    note = (" Batch window overlaps business hours — I/O contention risk." if overlap
            else " Batch window ends before business hours ramp — normal.")

    return Finding(
        metric="PhyWrs/Jrnwrts (batch/backup window)",
        severity=severity,
        observation=f"Overnight PhyWrs averaged {_fmt_n(overnight_pw)}/s (vs overall mean {_fmt_n(overall_pw)}/s) "
                    f"— batch/backup window identified.{note}",
        when=f"00:00–06:00 window",
        corroborating=[],
        hypotheses=(["confirmed: batch/backup I/O overlapping morning ramp — monitor for user impact"]
                    if overlap
                    else ["confirmed: batch window clears before business hours — acceptable"]),
        next_step=("Review backup schedule; aim to complete before 07:00." if overlap
                   else "No action required."),
        chart_request=None,
    )
