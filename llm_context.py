"""
LLM context export for yaspe.
Produces an anonymized markdown context bundle plus a companion LLM analysis prompt.
"""
from __future__ import annotations

import json
import os
import re
import warnings
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import performance_analysis as _pa


# mgstat columns included in timeseries (mean aggregation)
_MG_MEAN_COLS = [
    "Glorefs", "PhyRds", "PhyWrs", "Gloupds", "Jrnwrts",
    "Rdratio", "RouLaS", "Seize", "ASeize",
]
# mgstat columns aggregated as max (queue/count metrics where peak matters)
_MG_MAX_COLS = ["WDQsz"]

# vmstat columns included in timeseries (mean aggregation)
_VM_MEAN_COLS = ["us", "sy", "id", "wa", "free", "cache", "swpd", "si", "so", "st"]
# vmstat columns aggregated as max (saturation metrics where peak matters)
_VM_MAX_COLS = ["r", "b"]

# iostat columns included in timeseries (all aggregated as max)
_IOSTAT_COLS = ["r/s", "w/s", "rkB/s", "wkB/s", "r_await", "w_await", "aqu-sz", "%util"]

# mapping from iostat source column name to JSON-safe key
_IOSTAT_COL_MAP = {
    "r/s": "r_s",
    "w/s": "w_s",
    "rkB/s": "rkB_s",
    "wkB/s": "wkB_s",
    "r_await": "r_await",
    "w_await": "w_await",
    "aqu-sz": "aqu_sz",
    "%util": "util",
}


PROMPT_TEMPLATE = """\
# IRIS Performance Review — LLM Analysis Prompt

You are an experienced InterSystems IRIS performance analyst. You have been
given a **performance context bundle** (a markdown file produced by yaspe from
a SystemPerformance / pButtons capture of an EHR-style application on IRIS,
typically RHEL). Your job: produce a narrative system-health summary suitable
for a performance review meeting.

The bundle is **anonymized** — customer name, hostnames, and instance names
were redacted by the tool. The reviewer you are working with holds the
identity and business context; ask them rather than guessing. If a `context`
note is present in the bundle header, treat it as the reviewer's own framing.

## 1. What is in the bundle

- **YAML header** — `system` (vCPUs, RAM GB, IRIS global buffers GB, IRIS
  version, OS) and `collection` (window start/end, days, weekdays, sample
  interval in seconds, gaps). Gaps are collection outages: call them out,
  never interpolate across them. vCPU count is required to interpret the run
  queue; if missing, ask.
- **Baselines** — per IRIS Health Monitor period mean/sigma/p95/max for the
  baseline-relative mgstat metrics. Use these to judge "normal for this site".
- **Findings (pre-computed)** — deterministic breach and correlation
  detections made by yaspe. They are hints, not conclusions: verify each
  against the period statistics and timeseries, look for what they missed,
  and correlate findings with each other. Do not simply restate them.
- **Key metrics** — the analyst scorecard (overall window and the peak
  period). Ratios are computed from sums unless the basis column says
  otherwise. Lead your review with these numbers.
- **Not available** — metrics this capture cannot provide. Put these in your
  "data to request" section; do not speculate about their values.
- **Period statistics** — CSV, long format: per weekday x period x metric,
  mean/sigma/p90/p95/max/n_samples, computed from full-resolution samples.
  This is your primary quantitative source — prefer it over recomputing from
  the timeseries.
- **Timeseries** — CSV resampled to the interval stated in the caption. Most
  columns are per-interval means; columns suffixed `_max` are per-interval
  maxima; iostat blocks are per-interval maxima for IRIS-role disks only.
  Use the timeseries for shape, timing, and cross-metric correlation — not
  for precise statistics (the resampling already smoothed the peaks).

## 2. Method

Work **period by period** — EHR workload is strongly cyclical and whole-window
averages hide everything. The periods (IRIS Health Monitor defaults) are:
00:15-02:45, 03:00-06:00, 06:15-08:45, 09:00-11:30, 11:45-13:15, 13:30-16:00,
16:15-18:00, 18:15-20:45, 21:00-23:59, per weekday.

Breach evaluation uses the **consecutive-readings rule**: 3+ consecutive
samples over the alert threshold = alert event; 5+ consecutive over warning =
warning event. A single spike is noted only if extreme. For baseline-relative
metrics the per-period lines are:

```
alert   = 2.0 x MAX(mean + 3*sigma, highest + sigma)
warning = 1.6 x MAX(base, mean + 2*sigma, highest)
```

If the capture covers a single day, baselines derive from quiet periods of
that same day — say so explicitly and lower your confidence accordingly.

## 3. KPI thresholds

### vmstat (OS)
| Metric | Base | Alert | Warning |
|---|---|---|---|
| r (run queue) | vCPUs | > 2x vCPUs sustained | > 1x vCPUs sustained |
| b (blocked) | 0 | > 10-25% of vCPUs sustained | > 1-2 sustained |
| us+sy (CPU %) | 50 | 85 | 75 |
| sy (share of total CPU) | 10% | > 50% of total in kernel | > 30% of total |
| wa (I/O wait %) | 5 | > 20% sustained | > 10% sustained |
| si / so (swap) | 0 | any sustained so > 0 | any non-zero si/so |

On a dedicated IRIS server **any sustained swapping is an alert** — the shared
memory segment (global buffers) must never page. High sy relative to us at
similar workload points at huge pages, NUMA, interrupts, or network — not
application load.

### mgstat (IRIS)
| Metric | Base | Alert | Warning |
|---|---|---|---|
| Glorefs | baseline/period | > 2x norm, OR sustained drop toward 0 in business hours (stall) | > 1.6x norm |
| Gloupds | baseline | > 2x norm | > 1.6x norm |
| Rdratio | baseline | sustained fall to < ~10% of norm | declining trend |
| PhyRds | ~17/s | > 2x norm sustained | > 1.6x norm |
| PhyWrs | baseline | > 2x norm | > 1.6x norm |
| WDQsz | 0 | growing across consecutive write-daemon cycles | persistently non-zero |
| Jrnwrts | ~17/s | > 2x norm | > 1.6x norm |
| RouLaS | ~0 warm | sustained high (routine buffer undersized) | persistently > 0 |

### iostat (IRIS-role disks; general guidance)
| Metric | Healthy (flash-era) | Concerning |
|---|---|---|
| r_await / w_await | < ~1-2 ms typical | sustained > 10 ms, or growing with queue |
| aqu-sz | low single digits | sustained growth alongside await |
| %util | workload-dependent | 100% plus rising await |

## 4. Correlation patterns to test

1. **User stall** — Glorefs drops sharply in business hours: check WDQsz,
   vmstat b, wa at the same timestamps. Rising together = storage-side stall;
   not rising = upstream/application cause.
2. **Buffer pool pressure** — Rdratio trending down while PhyRds trends up:
   global buffers undersized for the working set. Quantify (first vs last day).
3. **Write daemon strain** — WDQsz non-zero between cycles + rising wa +
   PhyWrs at norm: write-path (storage/WIJ/journal) latency.
4. **Memory danger** — free trending down + cache shrinking + any si/so:
   flag prominently even without user impact yet.
5. **Contention vs throughput** — Seize rising in proportion to Glorefs is
   normal scaling; ASeize fraction rising is genuine contention.
6. **Kernel overhead** — sy growing relative to us at similar Glorefs.
7. **Batch/backup window** — identify the overnight PhyWrs/Jrnwrts surge and
   confirm it ends before the morning ramp; overlap is a finding.

## 5. Required output

1. **Executive summary** (<= 5 sentences): overall verdict (Green/Yellow/Red),
   the one or two findings that matter, urgency.
2. **Collection overview**: window, interval, gaps, data-quality caveats.
3. **Workload profile**: peak periods with timestamps, day-over-day
   consistency, the batch window, key-metrics scorecard commentary.
4. **Findings by severity** — each with value, threshold, duration, timestamps
   and recurrence, corroborating metrics, ranked hypotheses (observation vs
   inference clearly separated), and a concrete next step.
5. **Unusual but explainable** items (e.g. backup-window I/O) so reviewers do
   not rediscover them.
6. **Data limitations and data to request** — seed from the bundle's
   "Not available" section plus anything you found yourself missing.

Style: prose narrative, not bullet spam. Every claim carries value, threshold,
and duration ("wa averaged 18% (warning >= 10%) for 22 minutes from 09:42") —
never vague. No finding without timestamps. No alarmism — a single 5-second
spike is not an event. If the data is healthy, say so plainly and keep it
short. Where the data cannot support a root cause, offer ranked hypotheses
and the question that would discriminate between them.

## 6. Illustrate with charts, if you can

If your environment can execute code or render charts, plot the CSV blocks
to illustrate your key findings — this is a supplement to the written
analysis, not a substitute for it. Useful charts, chosen by what your
narrative actually discusses (do not chart every column):

- The metric behind your headline finding over the collection window
  (e.g. Glorefs, wa, or r), with the alert/warning threshold as a reference
  line and the breach period(s) you describe annotated or shaded.
- Two related metrics on a shared time axis when a correlation pattern
  (section 4) is central to a finding — e.g. CPU (us+sy) with run queue
  (r), or WDQsz with iostat w_await on the Database-role device.
- A per-period bar or box view (from the period-statistics CSV) when the
  finding is about a recurring time-of-day pattern rather than a single
  event.

If your environment cannot render charts, say so briefly and continue with
the narrative only — do not block the review on it.

---
*Prompt generated by yaspe --llm-context. Methodology source:
docs/Performance analysis/ in the yaspe repository. Before sharing the bundle
externally, eyeball it — anonymization is best-effort and only redacts
identifiers found in the capture header.*
"""


def _resample_mgstat(mg_df: pd.DataFrame, interval: str) -> list:
    """
    Resample mgstat DataFrame to interval (e.g. '5min').
    mg_df must have a 'dt' column of datetime64.
    Returns list of dicts with 'timestamp', mean cols, and _max suffixed max cols.
    """
    df = mg_df.copy().set_index("dt").sort_index()

    agg = {}
    for col in _MG_MEAN_COLS:
        if col in df.columns:
            agg[col] = pd.NamedAgg(column=col, aggfunc="mean")
    for col in _MG_MAX_COLS:
        if col in df.columns:
            agg[f"{col}_max"] = pd.NamedAgg(column=col, aggfunc="max")

    if not agg:
        return []

    resampled = df.resample(interval).agg(**agg).dropna(how="all").reset_index()
    resampled.rename(columns={"dt": "timestamp"}, inplace=True)
    resampled["timestamp"] = resampled["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    records = resampled.where(resampled.notna(), None).to_dict(orient="records")
    return records


def _resample_vmstat(vm_df: pd.DataFrame, interval: str) -> list:
    """
    Resample vmstat DataFrame to interval.
    vm_df must have a 'dt' column of datetime64.
    Returns list of dicts with 'timestamp', mean cols, _max suffixed max cols,
    and derived 'us_sy' (us + sy mean).
    """
    df = vm_df.copy().set_index("dt").sort_index()

    agg = {}
    for col in _VM_MEAN_COLS:
        if col in df.columns:
            agg[col] = pd.NamedAgg(column=col, aggfunc="mean")
    for col in _VM_MAX_COLS:
        if col in df.columns:
            agg[f"{col}_max"] = pd.NamedAgg(column=col, aggfunc="max")

    if not agg:
        return []

    resampled = df.resample(interval).agg(**agg).dropna(how="all").reset_index()
    resampled.rename(columns={"dt": "timestamp"}, inplace=True)

    if "us" in resampled.columns and "sy" in resampled.columns:
        resampled["us_sy"] = resampled["us"].fillna(0) + resampled["sy"].fillna(0)

    resampled["timestamp"] = resampled["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    records = resampled.where(resampled.notna(), None).to_dict(orient="records")
    return records


def _merge_timeseries(mg_records: list, vm_records: list) -> list:
    """
    Outer-join mgstat and vmstat records on 'timestamp'.
    Missing values in either source become None.
    Returns records sorted by 'timestamp'.
    """
    mg_map = {r["timestamp"]: dict(r) for r in mg_records}
    vm_map = {r["timestamp"]: dict(r) for r in vm_records}

    all_timestamps = sorted(set(mg_map) | set(vm_map))
    merged = []
    for ts in all_timestamps:
        row = {"timestamp": ts}
        if ts in mg_map:
            row.update({k: v for k, v in mg_map[ts].items() if k != "timestamp"})
        if ts in vm_map:
            row.update({k: v for k, v in vm_map[ts].items() if k != "timestamp"})
        merged.append(row)
    return merged


# Columns included in period statistics
_PERIOD_MG_COLS = ["Glorefs", "Gloupds", "PhyRds", "PhyWrs", "Jrnwrts", "Rdratio", "WDQsz", "PPGupds"]
_PERIOD_VM_COLS = ["r", "b", "sy", "wa", "si", "so"]
_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _series_stats(vals) -> Optional[dict]:
    """mean/sigma/p90/p95/max/n_samples for a numeric series; None if no numeric data."""
    vals = pd.to_numeric(vals, errors="coerce").dropna()
    if vals.empty:
        return None
    return {
        "mean": float(vals.mean()),
        "sigma": float(vals.std(ddof=1)) if len(vals) > 1 else 0.0,
        "p90": float(np.percentile(vals, 90)),
        "p95": float(np.percentile(vals, 95)),
        "max": float(vals.max()),
        "n_samples": int(len(vals)),
    }


def _add_period_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of df with _weekday and _period columns; rows outside all IRIS periods dropped."""
    df = df.copy()
    df["_weekday"] = df["dt"].dt.day_name()
    df["_period"] = df["dt"].dt.strftime("%H:%M").apply(_pa._label_period)
    return df.dropna(subset=["_period"])


def _compute_period_stats(mg_df: pd.DataFrame, vm_df: pd.DataFrame) -> list:
    """
    Per weekday × IRIS Health Monitor period stats from full-resolution data.
    Returns [{"weekday", "period", "metrics": {metric: stats}}] sorted by
    weekday then period. vmstat gains a derived us_sy column.
    """
    buckets = {}

    def _collect(df, cols, derive_us_sy=False):
        if df is None or df.empty or "dt" not in df.columns:
            return
        df = _add_period_cols(df)
        if df.empty:
            return
        if derive_us_sy and "us" in df.columns and "sy" in df.columns:
            df["us_sy"] = (pd.to_numeric(df["us"], errors="coerce")
                           + pd.to_numeric(df["sy"], errors="coerce"))
            cols = cols + ["us_sy"]
        for (weekday, period), group in df.groupby(["_weekday", "_period"]):
            metrics = buckets.setdefault((weekday, period), {})
            for col in cols:
                if col in group.columns:
                    stats = _series_stats(group[col])
                    if stats:
                        metrics[col] = stats

    _collect(mg_df, _PERIOD_MG_COLS)
    _collect(vm_df, _PERIOD_VM_COLS, derive_us_sy=True)

    period_order = [p["name"] for p in _pa.IRIS_PERIODS]
    keys = sorted(
        buckets,
        key=lambda k: (
            _WEEKDAY_ORDER.index(k[0]) if k[0] in _WEEKDAY_ORDER else 99,
            period_order.index(k[1]) if k[1] in period_order else 99,
        ),
    )
    return [{"weekday": w, "period": p, "metrics": buckets[(w, p)]} for w, p in keys]


# Formats seen in SystemPerformance captures; order matters — month/day before
# day/month to match dateutil's default resolution of ambiguous dates.
_DATETIME_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %I:%M:%S %p",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p",
    "%d/%m/%Y %H:%M:%S",
)


def _parse_datetime_series(series: pd.Series) -> pd.Series:
    """
    Parse a datetime string column. Infers the format once from the first
    value and parses vectorised (iostat timestamps can be locale 12-hour
    AM/PM, which pandas cannot infer). Falls back to per-element parsing
    for mixed-format columns.
    """
    s = series.str.strip()
    first = s.dropna()
    if not first.empty:
        sample = first.iloc[0]
        for fmt in _DATETIME_FORMATS:
            try:
                datetime.strptime(sample, fmt)
            except (ValueError, TypeError):
                continue
            parsed = pd.to_datetime(s, format=fmt, errors="coerce")
            # Uniform column: the matched format parses (almost) everything.
            if parsed.notna().sum() >= s.notna().sum() * 0.99:
                return parsed
            break
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        try:
            return pd.to_datetime(s, format="mixed", errors="coerce")
        except (TypeError, ValueError):
            return pd.to_datetime(s, errors="coerce")


def _serialise_finding(f) -> dict:
    """Convert a Finding dataclass to a JSON-safe dict."""
    return {
        "metric":        f.metric,
        "severity":      f.severity,
        "observation":   f.observation,
        "when":          f.when,
        "corroborating": list(f.corroborating),
        "hypotheses":    list(f.hypotheses),
        "next_step":     f.next_step,
    }


def _load_mg_df(connection) -> pd.DataFrame:
    """Load mgstat from SQLite and add a 'dt' column."""
    try:
        df = pd.read_sql_query("SELECT * FROM mgstat", connection)
        df.dropna(subset=["RunDate", "RunTime"], inplace=True)
        if "datetime" in df.columns:
            df["dt"] = _parse_datetime_series(df["datetime"])
        else:
            df["dt"] = _parse_datetime_series(
                df["RunDate"].str.strip() + " " + df["RunTime"].str.strip()
            )
        return df.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _load_vm_df(connection) -> pd.DataFrame:
    """Load vmstat from SQLite and add a 'dt' column."""
    try:
        df = pd.read_sql_query("SELECT * FROM vmstat", connection)
        df.dropna(subset=["RunDate", "RunTime"], inplace=True)
        if "datetime" in df.columns:
            df["dt"] = _parse_datetime_series(df["datetime"])
        else:
            df["dt"] = _parse_datetime_series(
                df["RunDate"].str.strip() + " " + df["RunTime"].str.strip()
            )
        return df.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _sum_ratio(num, den) -> Optional[float]:
    """Ratio of sums; None if denominator sums to <= 0."""
    num = pd.to_numeric(num, errors="coerce").dropna()
    den = pd.to_numeric(den, errors="coerce").dropna()
    total = float(den.sum())
    if total <= 0:
        return None
    return float(num.sum()) / total


def _role_devices(role_map: dict, prefix: str) -> list:
    return [dev for label, dev in role_map.items() if label.startswith(prefix)]


def _db_disk_metrics(iostat_df: pd.DataFrame, devices: list) -> dict:
    """Database-role disk scorecard entries. Rates summed across devices; response times from worst device."""
    entries = {}
    sub = iostat_df[iostat_df["Device"].isin(devices)]
    if sub.empty:
        return entries

    rate_cols = [c for c in ("r/s", "w/s") if c in sub.columns]
    if rate_cols:
        rates = sub.groupby("dt")[rate_cols].sum()
        if "r/s" in rates.columns:
            stats = _series_stats(rates["r/s"])
            if stats:
                entries["db_disk_reads_per_sec"] = {
                    "value": stats, "basis": "iostat r/s summed across Database-role devices"}
        if "w/s" in rates.columns:
            stats = _series_stats(rates["w/s"])
            if stats:
                entries["db_disk_writes_per_sec"] = {
                    "value": stats, "basis": "iostat w/s summed across Database-role devices"}
        if {"r/s", "w/s"} <= set(rates.columns):
            ratio = _sum_ratio(rates["r/s"], rates["w/s"])
            if ratio is not None:
                entries["db_disk_read_write_ratio"] = {
                    "value": ratio, "basis": "sum(r/s) / sum(w/s) on Database-role devices"}

    for col, name in (("r_await", "db_disk_read_response_ms"),
                      ("w_await", "db_disk_write_response_ms")):
        if col not in sub.columns:
            continue
        worst, worst_dev = None, None
        for dev in devices:
            stats = _series_stats(sub[sub["Device"] == dev][col])
            if stats and (worst is None or stats["p95"] > worst["p95"]):
                worst, worst_dev = stats, dev
        if worst:
            entries[name] = {
                "value": worst,
                "basis": f"iostat {col} on worst Database-role device ({worst_dev}, highest p95)"}
    return entries


def _key_metrics_slice(mg_df, vm_df, iostat_df, role_map, facts) -> dict:
    """Scorecard entries computable from the given (already time-filtered) frames."""
    km = {}
    ram_gb = facts.get("ram_gb")
    vcpus = facts.get("vcpus")

    if vm_df is not None and not vm_df.empty:
        mem_cols = [c for c in ("free", "buff", "cache") if c in vm_df.columns]
        if mem_cols and ram_gb:
            ram_kb = ram_gb * 1024 * 1024
            avail = vm_df[mem_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
            used_pct = ((ram_kb - avail) / ram_kb * 100).dropna()
            if not used_pct.empty:
                km["max_memory_utilization_pct"] = {
                    "value": float(used_pct.max()),
                    "basis": "max of (RAM − (free+buff+cache)) / RAM from vmstat",
                    "caveat": "page cache counted as used; reclaimable in practice"}
        if "us" in vm_df.columns and "sy" in vm_df.columns:
            us_sy = (pd.to_numeric(vm_df["us"], errors="coerce")
                     + pd.to_numeric(vm_df["sy"], errors="coerce"))
            stats = _series_stats(us_sy)
            if stats:
                km["cpu_utilization"] = {
                    "value": stats, "basis": "vmstat us+sy; p95 is the headline number"}

    if mg_df is not None and not mg_df.empty:
        if "Glorefs" in mg_df.columns:
            stats = _series_stats(mg_df["Glorefs"])
            if stats:
                km["glorefs_distribution"] = {
                    "value": stats, "basis": "mgstat Glorefs; p90 is the headline number"}
                if vcpus:
                    km["glorefs_per_core"] = {
                        "value": {k: stats[k] / vcpus for k in ("mean", "p90", "p95", "max")},
                        "basis": f"Glorefs ÷ {vcpus} vCPUs — capacity benchmark"}
        if "Gloupds" in mg_df.columns:
            stats = _series_stats(mg_df["Gloupds"])
            if stats:
                km["global_update_rate"] = {"value": stats, "basis": "mgstat Gloupds"}
        if {"PhyRds", "PhyWrs"} <= set(mg_df.columns):
            ratio = _sum_ratio(mg_df["PhyRds"], mg_df["PhyWrs"])
            if ratio is not None:
                km["physical_read_write_ratio"] = {
                    "value": ratio, "basis": "sum(PhyRds) / sum(PhyWrs)"}
        if {"Rdratio", "PhyRds"} <= set(mg_df.columns):
            rr = pd.to_numeric(mg_df["Rdratio"], errors="coerce")
            pr = pd.to_numeric(mg_df["PhyRds"], errors="coerce")
            logical = (rr * pr).dropna()
            denom = float(pr.dropna().sum())
            if denom > 0 and not logical.empty:
                agg_rdratio = float(logical.sum()) / denom
                if agg_rdratio > 1:
                    km["global_cache_hit_ratio_pct"] = {
                        "value": (1 - 1 / agg_rdratio) * 100,
                        "basis": "1 − 1/Rdratio with Rdratio = sum(Rdratio×PhyRds)/sum(PhyRds)",
                        "caveat": "block-level approximation of cache hit ratio"}
        if "PPGupds" in mg_df.columns:
            stats = _series_stats(mg_df["PPGupds"])
            if stats:
                km["ppg_update_rate"] = {"value": stats, "basis": "mgstat PPGupds"}
            if "Gloupds" in mg_df.columns:
                ratio = _sum_ratio(mg_df["PPGupds"], mg_df["Gloupds"])
                if ratio is not None:
                    km["ppg_to_global_update_ratio"] = {
                        "value": ratio, "basis": "sum(PPGupds) / sum(Gloupds)"}

    db_devices = _role_devices(role_map, "Database")
    if iostat_df is not None and not iostat_df.empty and db_devices:
        km.update(_db_disk_metrics(iostat_df, db_devices))

    iris_devices = _role_devices(role_map, "IRIS")
    if (iostat_df is not None and not iostat_df.empty and iris_devices
            and mg_df is not None and not mg_df.empty
            and "PPGupds" in mg_df.columns and "w/s" in iostat_df.columns):
        sub = iostat_df[iostat_df["Device"].isin(iris_devices)]
        ws_mean = pd.to_numeric(sub["w/s"], errors="coerce").dropna().mean() if not sub.empty else None
        ppg_mean = pd.to_numeric(mg_df["PPGupds"], errors="coerce").dropna().mean()
        if ws_mean and ws_mean > 0 and pd.notna(ppg_mean):
            km["ppg_to_iristemp_writes_ratio"] = {
                "value": float(ppg_mean) / float(ws_mean),
                "basis": "mean(PPGupds) / mean(w/s on IRIS-role devices) — cross-source, mean-based",
                "caveat": "IRIS-role device carries more than IRISTEMP"}
    return km


def _slice_by_period(df, weekday: str, period: str):
    if df is None or df.empty or "dt" not in getattr(df, "columns", []):
        return pd.DataFrame()
    d = _add_period_cols(df)
    return d[(d["_weekday"] == weekday) & (d["_period"] == period)]


def _compute_key_metrics(mg_df, vm_df, iostat_df, role_map, facts) -> dict:
    """Analyst scorecard: overall window plus the peak (highest mean Glorefs) weekday×period."""
    overall = _key_metrics_slice(mg_df, vm_df, iostat_df, role_map, facts)
    peak = None
    if mg_df is not None and not mg_df.empty and "Glorefs" in mg_df.columns:
        dfp = _add_period_cols(mg_df)
        if not dfp.empty:
            means = dfp.groupby(["_weekday", "_period"])["Glorefs"].mean()
            if not means.empty:
                weekday, period = means.idxmax()
                peak = {
                    "weekday": weekday,
                    "period": period,
                    "metrics": _key_metrics_slice(
                        _slice_by_period(mg_df, weekday, period),
                        _slice_by_period(vm_df, weekday, period),
                        _slice_by_period(iostat_df, weekday, period),
                        role_map, facts),
                }
    return {"overall": overall, "peak_period": peak}


def _build_not_available(mg_df, role_map) -> list:
    """Metrics this dataset cannot provide, with collection advice. Seeds the LLM's data-request list."""
    na = [
        {"metric": "transaction rate",
         "reason": "journal files are not part of a SystemPerformance capture",
         "how_to_collect": "journal file analysis (Begin/Commit records)"},
        {"metric": "global updates per transaction",
         "reason": "requires the journal-derived transaction rate",
         "how_to_collect": "journal file analysis"},
        {"metric": "ECP synch rate",
         "reason": "ECP synch records live in journal files",
         "how_to_collect": "journal file analysis"},
        {"metric": "global kill rate",
         "reason": "mgstat Gloupds merges sets and kills",
         "how_to_collect": "^GLOSTAT collection"},
        {"metric": "bitsets rate / bitsets-to-update ratio",
         "reason": "not reported by mgstat",
         "how_to_collect": "^GLOSTAT collection"},
        {"metric": "max IRIS / user processes",
         "reason": "process counts are not captured as a timeseries",
         "how_to_collect": "license/process count monitoring during the window"},
        {"metric": "average memory per IRIS process",
         "reason": "per-process memory is not captured",
         "how_to_collect": "periodic ps RSS sampling"},
        {"metric": "routine buffer statistics",
         "reason": "irisstat -R output is not in standard profiles",
         "how_to_collect": "irisstat -R snapshots"},
    ]
    has_ppg = mg_df is not None and not mg_df.empty and "PPGupds" in mg_df.columns
    if not has_ppg:
        na.append({"metric": "PPG update rate and ratios",
                   "reason": "mgstat from this IRIS version has no PPGupds column",
                   "how_to_collect": "capture from a newer IRIS version or ^GLOSTAT"})
    if not _role_devices(role_map, "Database"):
        na.append({"metric": "database disk I/O metrics",
                   "reason": "no Database-role device identified (CPF or iostat missing from capture)",
                   "how_to_collect": "re-run yaspe on a capture containing the CPF and iostat sections"})
    return na


def _load_iostat_role_map(connection) -> dict:
    """
    Return {role_label: device} from overview 'iris disk role *' entries.
    Excludes 'names' and '_mount' variants. Returns {} on any error.
    """
    try:
        rows = connection.execute(
            "SELECT field, value FROM overview WHERE field LIKE 'iris disk role %'"
        ).fetchall()
    except Exception:
        return {}
    result = {}
    for field, value in rows:
        if "names" in field or "_mount" in field:
            continue
        # "iris disk role Database 0" -> "Database 0"
        label = field[len("iris disk role "):]
        result[label] = value.strip()
    return result


def _resample_iostat(iostat_df: pd.DataFrame, device: str, interval: str) -> list:
    """
    Resample iostat DataFrame for one device to interval.
    All 8 metrics aggregated as max. Returns [] if device not present.
    """
    df = iostat_df[iostat_df["Device"] == device].copy()
    if df.empty:
        return []

    df = df.set_index("dt").sort_index()

    agg = {}
    for src_col in _IOSTAT_COLS:
        if src_col in df.columns:
            json_key = _IOSTAT_COL_MAP[src_col]
            agg[json_key] = pd.NamedAgg(column=src_col, aggfunc="max")

    if not agg:
        return []

    resampled = df.resample(interval).agg(**agg).dropna(how="all").reset_index()
    resampled.rename(columns={"dt": "timestamp"}, inplace=True)
    resampled["timestamp"] = resampled["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    return resampled.where(resampled.notna(), None).to_dict(orient="records")


def _load_iostat_df(connection) -> pd.DataFrame:
    """Load iostat from SQLite with a 'dt' column. Empty DataFrame on any error."""
    try:
        df = pd.read_sql_query("SELECT * FROM iostat", connection)
        if df.empty:
            return pd.DataFrame()
        if "datetime" in df.columns:
            df["dt"] = _parse_datetime_series(df["datetime"])
        else:
            df["dt"] = _parse_datetime_series(
                df["RunDate"].str.strip() + " " + df["RunTime"].str.strip()
            )
        return df.dropna(subset=["dt"]).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _build_iostat_timeseries(connection, interval: str) -> list:
    """
    Build iostat timeseries for IRIS-role devices only.
    Returns list of {role, device, records} dicts. Returns [] if no roles or no iostat table.
    """
    role_map = _load_iostat_role_map(connection)
    if not role_map:
        return []
    iostat_df = _load_iostat_df(connection)
    if iostat_df.empty:
        return []
    result = []
    for role, device in role_map.items():
        records = _resample_iostat(iostat_df, device, interval)
        if records:
            result.append({"role": role, "device": device, "records": records})
    return result


def _run_correlation_tests(joined: pd.DataFrame) -> list:
    """Run all 7 cross-signal correlation tests; return list of Finding."""
    results = []
    for test_fn in (
        _pa._test_user_stall,
        _pa._test_buffer_pressure,
        _pa._test_write_daemon_strain,
        _pa._test_memory_danger,
        _pa._test_contention_vs_throughput,
        _pa._test_kernel_overhead,
        _pa._test_batch_window,
    ):
        try:
            r = test_fn(joined)
            if r is not None:
                results.append(r)
        except Exception:
            pass
    return results


_SCRUB_ALLOWLIST = {"IRIS", "LINUX", "TEST", "PROD", "DEV", "LIVE"}
_REDACTED = "[redacted]"


def _gather_secrets(sp_dict: dict) -> list:
    """
    Identifying strings from sp_dict (customer, hostname, instance names),
    plus short-hostname variants of FQDNs. Longest first so FQDNs are
    redacted before their prefixes. Secrets < 4 chars or on the allowlist
    are dropped (an instance literally named IRIS must not shred output).
    """
    if not sp_dict:
        return []
    raw = []
    for key in ("customer", "linux hostname", "instance"):
        value = sp_dict.get(key)
        if value:
            raw.append(str(value).strip())
    for key, value in sp_dict.items():
        if key.startswith("up instance") and value:
            raw.append(str(value).strip())
    secrets = set()
    for value in raw:
        if value:
            secrets.add(value)
            if "." in value:
                secrets.add(value.split(".", 1)[0])
    keep = [s for s in secrets if len(s) >= 4 and s.upper() not in _SCRUB_ALLOWLIST]
    return sorted(keep, key=len, reverse=True)


def _scrub(obj, secrets: list):
    """
    Recursively redact secrets in all strings of a dict/list structure.
    Case-insensitive, word-boundary matched. Best-effort: never raises.
    """
    if not secrets:
        return obj
    try:
        if isinstance(obj, str):
            for secret in secrets:
                pattern = re.compile(
                    r"(?<![A-Za-z0-9])" + re.escape(secret) + r"(?![A-Za-z0-9])",
                    re.IGNORECASE,
                )
                obj = pattern.sub(_REDACTED, obj)
            return obj
        if isinstance(obj, dict):
            return {_scrub(k, secrets): _scrub(v, secrets) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_scrub(v, secrets) for v in obj]
        return obj
    except Exception:
        return obj


def _auto_resample_interval(n_days) -> str:
    """Timeseries interval scaled to window length so bundles stay chat-sized."""
    if not n_days or n_days <= 2:
        return "5min"
    if n_days <= 4:
        return "15min"
    return "30min"


def build_llm_context(
    connection,
    sp_dict: dict,
    resample_interval: Optional[str] = None,
    context: Optional[str] = None,
) -> dict:
    """
    Build a JSON-serialisable dict for LLM-based performance analysis.

    Returns dict with keys:
      schema_version, generated_by, context, system, collection,
      baselines, findings, period_stats, key_metrics, not_available,
      timeseries
    """
    meta  = _pa._get_collection_meta(connection)
    if resample_interval is None:
        resample_interval = _auto_resample_interval(meta.get("n_days"))
    facts = _pa._get_system_facts(sp_dict)
    facts.pop("customer", None)

    mg_df = _load_mg_df(connection)
    vm_df = _load_vm_df(connection)

    # Baselines (per IRIS period)
    mgstat_metrics = [m for m in ("Glorefs", "PhyRds", "PhyWrs", "Gloupds", "Jrnwrts", "Rdratio")
                      if not mg_df.empty and m in mg_df.columns]
    baselines = _pa._compute_baselines(mg_df, mgstat_metrics) if not mg_df.empty else {}

    # Findings
    vcpus = facts.get("vcpus")
    all_findings = []
    if not vm_df.empty:
        all_findings.extend(_pa._analyse_vmstat(vm_df, vcpus=vcpus))
    if not mg_df.empty:
        all_findings.extend(_pa._analyse_mgstat(mg_df, baselines))
    if not mg_df.empty and not vm_df.empty:
        interval = meta.get("interval_seconds") or 30.0
        joined = _pa._nearest_join(mg_df, vm_df, interval)
        all_findings.extend(_run_correlation_tests(joined))
    elif not mg_df.empty:
        for test_fn in (_pa._test_buffer_pressure, _pa._test_write_daemon_strain,
                        _pa._test_contention_vs_throughput, _pa._test_batch_window):
            try:
                r = test_fn(mg_df)
                if r is not None:
                    all_findings.append(r)
            except Exception:
                pass

    # Timeseries
    mg_records = _resample_mgstat(mg_df, resample_interval) if not mg_df.empty else []
    vm_records = _resample_vmstat(vm_df, resample_interval) if not vm_df.empty else []
    merged_records = _merge_timeseries(mg_records, vm_records)

    iostat_series = _build_iostat_timeseries(connection, resample_interval)

    timeseries = {
        "resample_interval": resample_interval,
        "aggregation_notes": (
            "Most metrics: mean per interval. "
            "r, b aggregated as max (suffixed _max). "
            "WDQsz aggregated as max (suffixed _max). "
            "us_sy derived = us_mean + sy_mean. "
            "iostat metrics (r_s, w_s, rkB_s, wkB_s, r_await, w_await, aqu_sz, util): "
            "max per interval, IRIS-role devices only."
        ),
        "records": merged_records,
    }
    if iostat_series:
        timeseries["iostat"] = iostat_series

    # Collection meta: convert timestamps to strings
    gaps_serialised = [
        [g[0].strftime("%Y-%m-%d %H:%M:%S"), g[1].strftime("%Y-%m-%d %H:%M:%S")]
        for g in meta.get("gaps", [])
        if hasattr(g[0], "strftime")
    ]
    collection = {
        "start":             meta["start"].strftime("%Y-%m-%d %H:%M:%S") if meta.get("start") else None,
        "end":               meta["end"].strftime("%Y-%m-%d %H:%M:%S")   if meta.get("end")   else None,
        "n_days":            meta.get("n_days"),
        "weekdays":          meta.get("weekdays", []),
        "interval_seconds":  meta.get("interval_seconds"),
        "gaps":              gaps_serialised,
    }

    role_map = _load_iostat_role_map(connection)
    iostat_df = _load_iostat_df(connection)

    period_stats = _compute_period_stats(mg_df, vm_df)
    key_metrics = _compute_key_metrics(mg_df, vm_df, iostat_df, role_map, facts)
    not_available = _build_not_available(mg_df, role_map)

    ctx = {
        "schema_version": "2.0",
        "generated_by":   "yaspe --llm-context",
        "context":        context,
        "system":         facts,
        "collection":     collection,
        "baselines":      baselines,
        "findings":       [_serialise_finding(f) for f in all_findings],
        "period_stats":   period_stats,
        "key_metrics":    key_metrics,
        "not_available":  not_available,
        "timeseries":     timeseries,
    }
    return _scrub(ctx, _gather_secrets(sp_dict or {}))


def export_llm_context(
    connection,
    sp_dict: dict,
    filepath: str,
    resample_interval: Optional[str] = None,
    context: Optional[str] = None,
) -> tuple:
    """
    Build and write the LLM context bundle and companion prompt.
    resample_interval None = auto (scaled to window length).

    Filenames deliberately carry no output_prefix: yaspe's default prefix
    is derived from the input HTML filename, which typically embeds
    hostname/instance (e.g. "trakprod1svr_MEKKESHLIVETCA_..."). These two
    files are meant to leave the building for a public LLM, so the
    filename itself must not be a second leak channel alongside the
    (already anonymized) content.

    Returns (bundle_path, prompt_path).
    """
    if resample_interval is not None:
        try:
            pd.tseries.frequencies.to_offset(resample_interval)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid resample interval: {resample_interval!r}. "
                "Examples: '5min', '10min', '1min'."
            )

    ctx = build_llm_context(connection, sp_dict, resample_interval, context)

    start_str = (ctx["collection"].get("start") or "unknown")[:10]
    end_str   = (ctx["collection"].get("end")   or "unknown")[:10]

    os.makedirs(filepath, exist_ok=True)

    bundle_path = os.path.join(filepath, f"performance_context_{start_str}_{end_str}.md")
    with open(bundle_path, "w", encoding="utf-8") as fh:
        fh.write(_render_markdown(ctx))

    prompt_path = os.path.join(filepath, "llm_analysis_prompt.md")
    with open(prompt_path, "w", encoding="utf-8") as fh:
        fh.write(PROMPT_TEMPLATE)

    return bundle_path, prompt_path


# ---- Markdown renderer ----

def _fmt_num(v, ratio: bool = False) -> str:
    """Rounded string form: ratios 2dp, >=100 integer, else 1dp. None -> empty."""
    if v is None:
        return ""
    if isinstance(v, bool) or isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if ratio:
            return f"{v:.2f}"
        if abs(v) >= 100:
            return f"{v:.0f}"
        return f"{v:.1f}"
    return str(v)


def _md_cell(text) -> str:
    """Escape pipe characters so free text cannot break a markdown table row."""
    return str(text).replace("|", "\\|") if text else ""


def _csv_block(records: list, columns: list) -> str:
    """Fenced csv block; header once, None -> empty cell, floats rounded."""
    lines = [",".join(columns)]
    for rec in records:
        lines.append(",".join(_fmt_num(rec.get(col)) for col in columns))
    return "```csv\n" + "\n".join(lines) + "\n```"


def _ordered_columns(records: list) -> list:
    cols = ["timestamp"]
    for rec in records:
        for key in rec:
            if key not in cols:
                cols.append(key)
    return cols


def _yaml_header(ctx: dict) -> str:
    y = ["---",
         f'schema_version: "{ctx["schema_version"]}"',
         f'generated_by: {ctx["generated_by"]}']
    if ctx.get("context"):
        y.append(f'context: {json.dumps(ctx["context"])}')
    y.append("system:")
    for key, value in ctx["system"].items():
        if value is None:
            y.append(f"  {key}: null")
        elif isinstance(value, float):
            y.append(f"  {key}: {_fmt_num(value)}")
        elif isinstance(value, str):
            y.append(f"  {key}: {json.dumps(value)}")
        else:
            y.append(f"  {key}: {value}")
    coll = ctx["collection"]
    y.append("collection:")
    for key in ("start", "end", "n_days", "interval_seconds"):
        value = coll.get(key)
        if value is None:
            y.append(f"  {key}: null")
        elif isinstance(value, float):
            y.append(f"  {key}: {_fmt_num(value)}")
        elif isinstance(value, str):
            y.append(f"  {key}: {json.dumps(value)}")
        else:
            y.append(f"  {key}: {value}")
    y.append(f"  weekdays: [{', '.join(coll.get('weekdays') or [])}]")
    gaps = coll.get("gaps") or []
    if gaps:
        y.append("  gaps:")
        for gap in gaps:
            y.append(f'    - [{json.dumps(gap[0])}, {json.dumps(gap[1])}]')
    else:
        y.append("  gaps: []")
    y.append("---")
    return "\n".join(y)


def _render_key_metrics_table(title: str, metrics: dict) -> str:
    rows = [f"### {title}", "",
            "| Metric | Mean | p90 | p95 | Max | Value | Basis | Caveat |",
            "|---|---|---|---|---|---|---|---|"]
    for name, entry in metrics.items():
        value = entry.get("value")
        is_ratio = "_ratio" in name
        basis = _md_cell(entry.get("basis", ""))
        caveat = _md_cell(entry.get("caveat", ""))
        if isinstance(value, dict):
            rows.append(
                f"| {name} | {_fmt_num(value.get('mean'))} | {_fmt_num(value.get('p90'))} "
                f"| {_fmt_num(value.get('p95'))} | {_fmt_num(value.get('max'))} |  | {basis} | {caveat} |")
        else:
            rows.append(f"| {name} |  |  |  |  | {_fmt_num(value, ratio=is_ratio)} | {basis} | {caveat} |")
    return "\n".join(rows)


def _render_markdown(ctx: dict) -> str:
    parts = [_yaml_header(ctx)]
    parts.append(
        "# Performance context bundle\n\n"
        "Anonymized IRIS/EHR performance capture produced by yaspe. "
        "Read alongside the companion prompt file (llm_analysis_prompt.md).")

    # Baselines
    baselines = ctx.get("baselines") or {}
    if baselines:
        rows = ["## Baselines", "",
                "Per IRIS Health Monitor period, from full-resolution mgstat.", "",
                "| Period | Metric | Mean | Sigma | p95 | Max |", "|---|---|---|---|---|---|"]
        for period, metrics in baselines.items():
            for metric, stats in metrics.items():
                rows.append(f"| {period} | {metric} | {_fmt_num(stats.get('mean'))} "
                            f"| {_fmt_num(stats.get('sigma'))} | {_fmt_num(stats.get('p95'))} "
                            f"| {_fmt_num(stats.get('max'))} |")
        parts.append("\n".join(rows))

    # Findings
    findings = ctx.get("findings") or []
    fparts = ["## Findings (pre-computed)", "",
              "Deterministic breach/correlation detections. Verify against the data; extend, do not parrot."]
    if findings:
        for f in findings:
            fparts.append(f"- **{f['severity']} — {f['metric']}**: {f['observation']}")
            if f.get("when"):
                fparts.append(f"  - When: {f['when']}")
            if f.get("corroborating"):
                fparts.append(f"  - Corroborating: {'; '.join(f['corroborating'])}")
            if f.get("hypotheses"):
                fparts.append(f"  - Hypotheses: {'; '.join(f['hypotheses'])}")
            if f.get("next_step"):
                fparts.append(f"  - Next step: {f['next_step']}")
    else:
        fparts.append("- No findings triggered.")
    parts.append("\n".join(fparts))

    # Key metrics
    km = ctx.get("key_metrics") or {}
    kparts = ["## Key metrics", "",
              "Analyst headline scorecard. Ratios are sums-based unless the basis says otherwise."]
    if km.get("overall"):
        kparts.append("")
        kparts.append(_render_key_metrics_table("Overall window", km["overall"]))
    peak = km.get("peak_period")
    if peak:
        kparts.append("")
        kparts.append(_render_key_metrics_table(
            f"Peak period — {peak['weekday']} {peak['period']} (highest mean Glorefs)",
            peak["metrics"]))
    parts.append("\n".join(kparts))

    # Not available
    na = ctx.get("not_available") or []
    if na:
        rows = ["## Not available", "",
                "Metrics this dataset cannot provide — candidates for the data-to-request list.", "",
                "| Metric | Reason | How to collect |", "|---|---|---|"]
        for entry in na:
            rows.append(f"| {_md_cell(entry['metric'])} | {_md_cell(entry['reason'])} | {_md_cell(entry['how_to_collect'])} |")
        parts.append("\n".join(rows))

    # Period statistics
    ps = ctx.get("period_stats") or []
    if ps:
        records = []
        for entry in ps:
            for metric, stats in entry["metrics"].items():
                records.append({"weekday": entry["weekday"], "period": entry["period"],
                                "metric": metric, **stats})
        columns = ["weekday", "period", "metric", "mean", "sigma", "p90", "p95", "max", "n_samples"]
        parts.append("## Period statistics\n\n"
                     "Per weekday × IRIS period, from full-resolution samples (long format).\n\n"
                     + _csv_block(records, columns))

    # Timeseries
    ts = ctx.get("timeseries") or {}
    tparts = ["## Timeseries", "",
              f"Resampled to {ts.get('resample_interval')}. {ts.get('aggregation_notes', '')}"]
    records = ts.get("records") or []
    if records:
        tparts.append("")
        tparts.append("### mgstat + vmstat (merged)")
        tparts.append("")
        tparts.append(_csv_block(records, _ordered_columns(records)))
    for series in ts.get("iostat") or []:
        tparts.append("")
        tparts.append(f"### iostat — {series['role']} ({series['device']}), max per interval")
        tparts.append("")
        tparts.append(_csv_block(series["records"], _ordered_columns(series["records"])))
    parts.append("\n".join(tparts))

    return "\n\n".join(parts) + "\n"
