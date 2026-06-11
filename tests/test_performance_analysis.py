# tests/test_performance_analysis.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import tempfile
import pandas as pd
from datetime import datetime

from performance_analysis import IRIS_PERIODS, METRIC_THRESHOLDS, Finding, ChartRequest
from performance_analysis import _get_collection_meta, _get_system_facts

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
