import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime
import pytest
from llm_context import _resample_mgstat, _resample_vmstat, _merge_timeseries


def _make_mg_df(n=12):
    """12 rows at 30s intervals = 6 minutes of mgstat data."""
    base = datetime(2024, 1, 15, 9, 0, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=30 * i),
            "Glorefs": 10000 + i * 100,
            "PhyRds": 50,
            "PhyWrs": 20,
            "Gloupds": 500,
            "Jrnwrts": 30,
            "WDQsz": i * 10,      # grows: max matters
            "Rdratio": 95.0,
            "RouLaS": 0,
            "Seize": 100,
            "ASeize": 5,
        })
    return pd.DataFrame(rows)


def _make_vm_df(n=12):
    base = datetime(2024, 1, 15, 9, 0, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=30 * i),
            "us": 30.0,
            "sy": 10.0,
            "id": 60.0,
            "wa": 2.0,
            "r": i,               # grows: max matters
            "b": 0,
            "free": 8000000,
            "cache": 2000000,
            "swpd": 0,
            "si": 0,
            "so": 0,
            "st": 0,
        })
    return pd.DataFrame(rows)


def test_resample_mgstat_returns_list():
    result = _resample_mgstat(_make_mg_df(), "5min")
    assert isinstance(result, list)
    assert len(result) > 0


def test_resample_mgstat_record_has_timestamp():
    result = _resample_mgstat(_make_mg_df(), "5min")
    assert "timestamp" in result[0]
    # ISO 8601 format
    datetime.strptime(result[0]["timestamp"], "%Y-%m-%d %H:%M:%S")


def test_resample_mgstat_wdqsz_is_max():
    mg_df = _make_mg_df(n=12)
    # WDQsz values go 0,10,20,...,110 — in a 5min window (10 samples at 30s)
    # the first bucket max should be 90 (samples 0-9: 0..90)
    result = _resample_mgstat(mg_df, "5min")
    assert "WDQsz_max" in result[0]
    assert result[0]["WDQsz_max"] == pytest.approx(90, abs=20)


def test_resample_mgstat_glorefs_is_mean():
    result = _resample_mgstat(_make_mg_df(), "5min")
    assert "Glorefs" in result[0]
    # mean of 10000..10900 over 10 rows ≈ 10450
    assert result[0]["Glorefs"] == pytest.approx(10450, abs=200)


def test_resample_vmstat_returns_list():
    result = _resample_vmstat(_make_vm_df(), "5min")
    assert isinstance(result, list)
    assert len(result) > 0


def test_resample_vmstat_r_is_max():
    result = _resample_vmstat(_make_vm_df(n=12), "5min")
    assert "r_max" in result[0]
    # r values 0..11; first bucket (10 samples) max = 9
    assert result[0]["r_max"] == pytest.approx(9, abs=2)


def test_resample_vmstat_us_sy_derived():
    result = _resample_vmstat(_make_vm_df(), "5min")
    assert "us_sy" in result[0]
    assert result[0]["us_sy"] == pytest.approx(40.0, abs=1.0)


def test_merge_timeseries_joins_on_timestamp():
    mg = [{"timestamp": "2024-01-15 09:00:00", "Glorefs": 10000.0}]
    vm = [{"timestamp": "2024-01-15 09:00:00", "us": 30.0}]
    merged = _merge_timeseries(mg, vm)
    assert len(merged) == 1
    assert merged[0]["Glorefs"] == 10000.0
    assert merged[0]["us"] == 30.0


def test_merge_timeseries_outer_join():
    mg = [{"timestamp": "2024-01-15 09:00:00", "Glorefs": 10000.0},
          {"timestamp": "2024-01-15 09:05:00", "Glorefs": 11000.0}]
    vm = [{"timestamp": "2024-01-15 09:00:00", "us": 30.0}]
    merged = _merge_timeseries(mg, vm)
    assert len(merged) == 2
    # second row has no vmstat match
    row2 = next(r for r in merged if r["timestamp"] == "2024-01-15 09:05:00")
    assert row2.get("us") is None


def test_merge_timeseries_sorted():
    mg = [{"timestamp": "2024-01-15 09:05:00", "Glorefs": 11000.0},
          {"timestamp": "2024-01-15 09:00:00", "Glorefs": 10000.0}]
    merged = _merge_timeseries(mg, [])
    assert merged[0]["timestamp"] < merged[1]["timestamp"]
