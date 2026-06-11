# tests/test_performance_analysis.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import tempfile
import pandas as pd
from datetime import datetime

from performance_analysis import IRIS_PERIODS, METRIC_THRESHOLDS, Finding, ChartRequest
from performance_analysis import _get_collection_meta, _get_system_facts
from performance_analysis import _label_period, _compute_baselines, _find_breaches
from performance_analysis import _analyse_vmstat

def test_iris_periods_count():
    assert len(IRIS_PERIODS) == 9

def test_iris_periods_structure():
    period = IRIS_PERIODS[0]
    assert "name" in period
    assert "start" in period
    assert "end" in period

def test_metric_thresholds_vmstat_keys():
    assert "wa" in METRIC_THRESHOLDS
    assert "r" in METRIC_THRESHOLDS
    assert "us_sy" in METRIC_THRESHOLDS
    assert "si" in METRIC_THRESHOLDS
    assert "so" in METRIC_THRESHOLDS
    assert "b" in METRIC_THRESHOLDS
    assert "sy_pct" in METRIC_THRESHOLDS

def test_metric_thresholds_mgstat_keys():
    assert "Glorefs" in METRIC_THRESHOLDS
    assert "PhyRds" in METRIC_THRESHOLDS
    assert "WDQsz" in METRIC_THRESHOLDS
    assert "Rdratio" in METRIC_THRESHOLDS

def test_finding_dataclass():
    f = Finding(
        metric="wa",
        severity="Yellow",
        observation="wa averaged 12%",
        when="09:00–09:22",
        corroborating=[],
        hypotheses=["hypothesis: storage latency"],
        next_step="Monitor",
        chart_request=None,
    )
    assert f.severity == "Yellow"
    assert f.chart_request is None

def test_chart_request_dataclass():
    import pandas as pd
    cr = ChartRequest(
        metric="wa",
        title="I/O Wait",
        df=pd.DataFrame({"datetime_parsed": [], "metric": []}),
        warn_level=10.0,
        alert_level=20.0,
        shading_spans=[],
        twin_metric=None,
        twin_df=None,
        output_dir="/tmp",
        filename="wa_finding",
    )
    assert cr.warn_level == 10.0


def _make_test_db(rows):
    """Create an in-memory SQLite DB with a minimal mgstat table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE mgstat (
            id_key INTEGER PRIMARY KEY,
            RunDate TEXT, RunTime TEXT,
            Glorefs REAL, PhyRds REAL, PhyWrs REAL,
            Gloupds REAL, Rdratio REAL, WDQsz REAL,
            Jrnwrts REAL, RouLaS REAL, Seize REAL, ASeize REAL,
            "html name" TEXT
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO mgstat (RunDate, RunTime, Glorefs, PhyRds, PhyWrs, "
            "Gloupds, Rdratio, WDQsz, Jrnwrts, RouLaS, Seize, ASeize, \"html name\") "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            r
        )
    conn.commit()
    return conn


def test_get_collection_meta_interval():
    rows = [
        ("01/01/2026", "09:00:00", 1000,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:05", 1100,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:10", 1200,0,0,0,50,0,0,0,0,0,"f.html"),
    ]
    conn = _make_test_db(rows)
    meta = _get_collection_meta(conn)
    assert meta["interval_seconds"] == 5
    assert meta["n_days"] == 1
    assert meta["gaps"] == []
    conn.close()


def test_get_collection_meta_detects_gap():
    rows = [
        ("01/01/2026", "09:00:00", 1000,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:05", 1100,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:10", 1150,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:15", 1200,0,0,0,50,0,0,0,0,0,"f.html"),
        # gap: 60 seconds > 3 × 5s interval
        ("01/01/2026", "09:01:15", 1300,0,0,0,50,0,0,0,0,0,"f.html"),
    ]
    conn = _make_test_db(rows)
    meta = _get_collection_meta(conn)
    assert len(meta["gaps"]) == 1
    conn.close()


def test_get_system_facts_linux():
    sp_dict = {
        "operating system": "Linux",
        "customer": "TestHospital",
        "number cpus": "8",
        "memory MB": "32768",
        "globals total MB": "16384",
        "version string": "IRIS for UNIX 2024.1",
    }
    facts = _get_system_facts(sp_dict)
    assert facts["vcpus"] == 8
    assert facts["ram_gb"] == 32
    assert facts["iris_buffers_gb"] == 16
    assert facts["customer"] == "TestHospital"


def test_get_system_facts_missing_keys():
    facts = _get_system_facts({})
    assert facts["vcpus"] is None
    assert facts["ram_gb"] is None
    assert facts["iris_buffers_gb"] is None
    assert facts["customer"] == "Unknown"


# Task 3: _label_period and _compute_baselines
def test_label_period_morning():
    assert _label_period("09:30") == "09:00–11:30"


def test_label_period_overnight():
    assert _label_period("01:00") == "00:15–02:45"


def test_label_period_outside_all():
    # 00:00–00:14 falls outside all defined periods
    assert _label_period("00:05") is None


def _make_mgstat_df():
    """Three rows in 09:00–11:30 period on same day."""
    return pd.DataFrame({
        "dt": pd.to_datetime([
            "2026-01-01 09:00:05",
            "2026-01-01 09:00:10",
            "2026-01-01 09:00:15",
        ]),
        "Glorefs": [1000.0, 1200.0, 800.0],
        "PhyRds":  [10.0, 12.0, 8.0],
    })


def test_compute_baselines_returns_expected_keys():
    df = _make_mgstat_df()
    baselines = _compute_baselines(df, ["Glorefs", "PhyRds"])
    assert "09:00–11:30" in baselines
    period = baselines["09:00–11:30"]
    assert "Glorefs" in period
    assert "mean" in period["Glorefs"]
    assert "sigma" in period["Glorefs"]
    assert "p95" in period["Glorefs"]
    assert "max" in period["Glorefs"]


def test_compute_baselines_values():
    df = _make_mgstat_df()
    baselines = _compute_baselines(df, ["Glorefs"])
    g = baselines["09:00–11:30"]["Glorefs"]
    assert abs(g["mean"] - 1000.0) < 1.0
    assert g["max"] == 1200.0


# Task 4: _find_breaches
def test_find_breaches_no_breach():
    vals = pd.Series([5.0, 6.0, 4.0, 3.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05",
                           "2026-01-01 09:00:10","2026-01-01 09:00:15"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert runs == []


def test_find_breaches_single_spike_ignored():
    vals = pd.Series([5.0, 25.0, 4.0, 3.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05",
                           "2026-01-01 09:00:10","2026-01-01 09:00:15"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert runs == []


def test_find_breaches_detects_run():
    vals = pd.Series([5.0, 25.0, 30.0, 22.0, 4.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05",
                           "2026-01-01 09:00:10","2026-01-01 09:00:15",
                           "2026-01-01 09:00:20"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert len(runs) == 1
    start, end, count = runs[0]
    assert count == 3


def test_find_breaches_returns_timestamps():
    vals = pd.Series([15.0, 15.0, 15.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05","2026-01-01 09:00:10"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert len(runs) == 1
    start, end, count = runs[0]
    assert str(start) == "2026-01-01 09:00:00"
    assert str(end)   == "2026-01-01 09:00:10"


# Task 5: _analyse_vmstat

def _make_vmstat_df(wa_vals, r_vals=None, si_vals=None, so_vals=None, us_vals=None, sy_vals=None):
    n = len(wa_vals)
    base_dt = pd.date_range("2026-01-01 09:00:00", periods=n, freq="5s")
    return pd.DataFrame({
        "dt": base_dt,
        "wa": wa_vals,
        "r":  r_vals  if r_vals  is not None else [0.0] * n,
        "si": si_vals if si_vals is not None else [0.0] * n,
        "so": so_vals if so_vals is not None else [0.0] * n,
        "us": us_vals if us_vals is not None else [20.0] * n,
        "sy": sy_vals if sy_vals is not None else [5.0] * n,
        "b":  [0.0] * n,
        "id": [75.0] * n,
    })


def test_analyse_vmstat_green_when_normal():
    df = _make_vmstat_df(wa_vals=[2.0] * 10)
    findings = _analyse_vmstat(df, vcpus=8)
    # All within thresholds — no Red or Yellow findings
    non_green = [f for f in findings if f.severity != "Green"]
    assert non_green == []


def test_analyse_vmstat_yellow_wa():
    # 5 consecutive samples of wa=12% → Yellow (warn threshold 10%, 5 consecutive)
    df = _make_vmstat_df(wa_vals=[12.0] * 5 + [2.0] * 5)
    findings = _analyse_vmstat(df, vcpus=8)
    wa_findings = [f for f in findings if "wa" in f.metric]
    assert any(f.severity in ("Yellow", "Red") for f in wa_findings)


def test_analyse_vmstat_red_wa():
    # 3 consecutive samples of wa=25% → Red (alert threshold 20%, 3 consecutive)
    df = _make_vmstat_df(wa_vals=[25.0] * 3 + [2.0] * 7)
    findings = _analyse_vmstat(df, vcpus=8)
    wa_findings = [f for f in findings if "wa" in f.metric]
    assert any(f.severity == "Red" for f in wa_findings)


def test_analyse_vmstat_swap_is_always_red():
    # Any sustained so > 0 is Red
    df = _make_vmstat_df(wa_vals=[2.0] * 10, so_vals=[1.0] * 3 + [0.0] * 7)
    findings = _analyse_vmstat(df, vcpus=8)
    so_findings = [f for f in findings if "so" in f.metric or "swap" in f.metric.lower()]
    assert any(f.severity == "Red" for f in so_findings)


def test_analyse_vmstat_run_queue_vcpu_relative():
    # r > 2 × 2 vCPUs = 4 → alert; use 3 consec samples of r=5 on 2-vCPU system
    df = _make_vmstat_df(wa_vals=[2.0] * 10, r_vals=[5.0] * 3 + [0.0] * 7)
    findings = _analyse_vmstat(df, vcpus=2)
    r_findings = [f for f in findings if "run queue" in f.metric.lower() or f.metric == "r"]
    assert any(f.severity == "Red" for f in r_findings)


def test_analyse_vmstat_finding_has_observation_text():
    df = _make_vmstat_df(wa_vals=[25.0] * 3 + [2.0] * 7)
    findings = _analyse_vmstat(df, vcpus=8)
    for f in findings:
        if f.severity in ("Yellow", "Red"):
            assert len(f.observation) > 0
            assert len(f.when) > 0
