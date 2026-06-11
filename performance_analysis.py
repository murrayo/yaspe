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
    n_days = (end.date() - start.date()).days + 1
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
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="wa (I/O wait %)",
                severity="Red",
                observation=f"wa exceeded 20% (alert) for {count} consecutive samples "
                            f"(≥ {count * df['dt'].diff().median().total_seconds():.0f}s). "
                            f"Peak: {vals.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: storage latency — check iostat await/svctm",
                            "hypothesis: excessive write-back I/O from dirty page flush"],
                next_step="Correlate with iostat await; check WDQsz and PhyWrs.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="wa (I/O wait %)",
                severity="Yellow",
                observation=f"wa exceeded 10% (warning) for {count} consecutive samples. "
                            f"Peak: {vals.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: intermittent storage latency"],
                next_step="Monitor; correlate with iostat.",
                chart_request=None,
            ))

    # --- us+sy (total CPU) ---
    if "us" in df.columns and "sy" in df.columns:
        us_sy = pd.to_numeric(df["us"], errors="coerce").fillna(0) + \
                pd.to_numeric(df["sy"], errors="coerce").fillna(0)
        red_runs  = _find_breaches(us_sy, df["dt"], 85.0, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(us_sy, df["dt"], 75.0, WARN_CONSECUTIVE)
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="us+sy (CPU %)",
                severity="Red",
                observation=f"us+sy exceeded 85% for {count} consecutive samples. "
                            f"Peak: {us_sy.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: CPU-bound workload surge",
                            "hypothesis: runaway process — check top"],
                next_step="Correlate with Glorefs; if Glorefs is proportional this is normal scaling. "
                          "If Glorefs is low, suspect a runaway process.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="us+sy (CPU %)",
                severity="Yellow",
                observation=f"us+sy exceeded 75% for {count} consecutive samples. Peak: {us_sy.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: elevated workload"],
                next_step="Monitor trend.",
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
                observation=f"Run queue exceeded {alert_thr:.0f} (2× vCPUs={vcpus}) for "
                            f"{count} consecutive samples. Peak: {r_vals.max():.0f}.",
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
                observation=f"Run queue exceeded {warn_thr:.0f} (1× vCPUs={vcpus}) for {count} consecutive samples.",
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
                                f"IRIS shared memory segment is paging. Peak: {vals.max():.0f} KB/s.",
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
    if "WDQsz" in df.columns:
        vals = pd.to_numeric(df["WDQsz"], errors="coerce").fillna(0)
        warn_runs = _find_breaches(vals, df["dt"], 0.0, WARN_CONSECUTIVE)
        if warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="WDQsz (write daemon queue)",
                severity="Yellow",
                observation=f"WDQsz was non-zero for {count} consecutive samples "
                            f"(max {vals.max():.0f}). Write daemon queue backing up between cycles.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: write path (storage/WIJ/journal) latency causing WD queue growth"],
                next_step="Correlate with wa and PhyWrs. If wa is elevated: storage write latency. "
                          "Check WD cycle time; any cycle ≥ 90 s is critical.",
                chart_request=None,
            ))

    # --- RouLaS (column name is capitalised S in pButtons schema) ---
    roul_col = "RouLaS" if "RouLaS" in df.columns else "RouLas" if "RouLas" in df.columns else None
    if roul_col:
        vals = pd.to_numeric(df[roul_col], errors="coerce").fillna(0)
        warn_runs = _find_breaches(vals, df["dt"], 0.0, WARN_CONSECUTIVE)
        if warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="RouLaS (routine cache misses)",
                severity="Yellow",
                observation=f"RouLaS was non-zero for {count} consecutive samples (max {vals.max():.0f}). "
                            f"Routine buffer cache is undersized.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: routine buffer (routines= in CPF) too small for working set"],
                next_step="Review routines= setting in CPF. Consider increasing.",
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
                    observation=f"{metric} exceeded alert level {alert_level:.0f} "
                                f"(2× period norm) for {count} consecutive samples. "
                                f"Peak: {group_vals.max():.0f}.",
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
                    observation=f"{metric} exceeded warning level {warn_level:.0f} "
                                f"(1.6× period norm) for {count} consecutive samples. "
                                f"Peak: {group_vals.max():.0f}.",
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
