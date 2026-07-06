"""
LLM context export for yaspe.
Produces a compact JSON file for use as LLM input for performance analysis.
"""
from __future__ import annotations

import json
import os
from typing import Optional

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
        result[label] = value
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


def _build_iostat_timeseries(connection, interval: str) -> list:
    """
    Build iostat timeseries for IRIS-role devices only.
    Returns list of {role, device, records} dicts. Returns [] if no roles or no iostat table.
    """
    role_map = _load_iostat_role_map(connection)
    if not role_map:
        return []

    try:
        iostat_df = pd.read_sql_query("SELECT * FROM iostat", connection)
        if iostat_df.empty:
            return []
        if "datetime" in iostat_df.columns:
            iostat_df["dt"] = pd.to_datetime(
                iostat_df["datetime"].str.strip(),
                format="%Y/%m/%d %I:%M:%S %p",
                errors="coerce",
            )
        else:
            iostat_df["dt"] = pd.to_datetime(
                iostat_df["RunDate"].str.strip() + " " + iostat_df["RunTime"].str.strip(),
                errors="coerce",
            )
        iostat_df = iostat_df.dropna(subset=["dt"]).reset_index(drop=True)
    except Exception:
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
    except ValueError:
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
