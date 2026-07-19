"""
LLM context export for yaspe.
Produces a compact JSON file for use as LLM input for performance analysis.
"""
from __future__ import annotations

import json
import os
import re
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


def _serialise_finding(f) -> dict:
    """Convert a Finding dataclass to a JSON-safe dict, dropping chart_request."""
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
            df["dt"] = pd.to_datetime(df["datetime"].str.strip(), errors="coerce")
        else:
            df["dt"] = pd.to_datetime(
                df["RunDate"].str.strip() + " " + df["RunTime"].str.strip(),
                errors="coerce",
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
            df["dt"] = pd.to_datetime(df["datetime"].str.strip(), errors="coerce")
        else:
            df["dt"] = pd.to_datetime(
                df["RunDate"].str.strip() + " " + df["RunTime"].str.strip(),
                errors="coerce",
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

    for col, name, label in (("r_await", "db_disk_read_response_ms", "read"),
                             ("w_await", "db_disk_write_response_ms", "write")):
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
            df["dt"] = pd.to_datetime(df["datetime"].str.strip(), errors="coerce")
        else:
            df["dt"] = pd.to_datetime(
                df["RunDate"].str.strip() + " " + df["RunTime"].str.strip(),
                errors="coerce",
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


def build_llm_context(
    connection,
    sp_dict: dict,
    resample_interval: str = "5min",
    context: Optional[str] = None,
) -> dict:
    """
    Build a JSON-serialisable dict for LLM-based performance analysis.

    Returns dict with keys:
      schema_version, generated_by, context, system, collection,
      baselines, findings, timeseries
    """
    meta  = _pa._get_collection_meta(connection)
    facts = _pa._get_system_facts(sp_dict)

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

    return {
        "schema_version": "1.0",
        "generated_by":   "yaspe --llm-context",
        "context":        context,
        "system":         facts,
        "collection":     collection,
        "baselines":      baselines,
        "findings":       [_serialise_finding(f) for f in all_findings],
        "timeseries":     timeseries,
    }


def export_llm_context(
    connection,
    sp_dict: dict,
    output_prefix: str,
    filepath: str,
    resample_interval: str = "5min",
    context: Optional[str] = None,
) -> str:
    """
    Build and write LLM context JSON to filepath.
    Filename: {filepath}/{output_prefix}performance_context_{start}_{end}.json
    Returns the path of the written file.
    """
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

    filename  = f"{output_prefix}performance_context_{start_str}_{end_str}.json"
    out_path  = os.path.join(filepath, filename)

    os.makedirs(filepath, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(ctx, fh, indent=2, default=str)

    return out_path
