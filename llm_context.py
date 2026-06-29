"""
LLM context export for yaspe.
Produces a compact JSON file for use as LLM input for performance analysis.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd


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


import performance_analysis as _pa


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
        "timeseries": {
            "resample_interval": resample_interval,
            "aggregation_notes": (
                "Most metrics: mean per interval. "
                "r, b aggregated as max (suffixed _max). "
                "WDQsz aggregated as max (suffixed _max). "
                "us_sy derived = us_mean + sy_mean."
            ),
            "records": merged_records,
        },
    }
