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
