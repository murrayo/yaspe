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


# ---- Task 2 additions ----
import sqlite3
import tempfile
import json
from performance_analysis import Finding
from llm_context import _serialise_finding, build_llm_context


def _make_sqlite_with_data():
    """In-memory SQLite with minimal mgstat + vmstat rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE mgstat (
            RunDate TEXT, RunTime TEXT,
            Glorefs REAL, PhyRds REAL, PhyWrs REAL, Gloupds REAL,
            Jrnwrts REAL, WDQsz REAL, Rdratio REAL, RouLaS REAL,
            Seize REAL, ASeize REAL
        )
    """)
    conn.execute("""
        CREATE TABLE vmstat (
            RunDate TEXT, RunTime TEXT,
            r REAL, b REAL, swpd REAL, free REAL, buff REAL, cache REAL,
            si REAL, so REAL, bi REAL, bo REAL, "in" REAL, cs REAL,
            us REAL, sy REAL, id REAL, wa REAL, st REAL
        )
    """)
    # Insert 20 rows at 30s intervals
    from datetime import datetime, timedelta
    base = datetime(2024, 1, 15, 9, 0, 0)
    for i in range(20):
        ts = base + timedelta(seconds=30 * i)
        conn.execute(
            "INSERT INTO mgstat VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts.strftime("%Y/%m/%d"), ts.strftime("%H:%M:%S"),
             10000 + i*100, 50, 20, 500, 30, i*5, 95.0, 0, 100, 5)
        )
        conn.execute(
            "INSERT INTO vmstat VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts.strftime("%Y/%m/%d"), ts.strftime("%H:%M:%S"),
             1, 0, 0, 8000000, 0, 2000000, 0, 0, 0, 0, 0, 0,
             30.0, 10.0, 60.0, 2.0, 0.0)
        )
    conn.commit()
    return conn


def test_serialise_finding_drops_chart_request():
    f = Finding(
        metric="wa",
        severity="Yellow",
        observation="wa exceeded 10%",
        when="09:00",
        corroborating=["WDQsz elevated"],
        hypotheses=["storage latency"],
        next_step="Check iostat",
        chart_request=None,
    )
    d = _serialise_finding(f)
    assert "chart_request" not in d
    assert d["metric"] == "wa"
    assert d["severity"] == "Yellow"
    assert d["observation"] == "wa exceeded 10%"
    assert d["corroborating"] == ["WDQsz elevated"]
    assert d["hypotheses"] == ["storage latency"]
    assert d["next_step"] == "Check iostat"


def test_build_llm_context_top_level_keys():
    conn = _make_sqlite_with_data()
    sp_dict = {"number cpus": "4", "memory MB": "16384", "globals total MB": "8192"}
    result = build_llm_context(conn, sp_dict)
    assert result["schema_version"] == "1.0"
    assert "system" in result
    assert "collection" in result
    assert "baselines" in result
    assert "findings" in result
    assert "timeseries" in result
    conn.close()


def test_build_llm_context_system_facts():
    conn = _make_sqlite_with_data()
    sp_dict = {"number cpus": "4", "memory MB": "16384", "globals total MB": "8192"}
    result = build_llm_context(conn, sp_dict)
    assert result["system"]["vcpus"] == 4
    assert result["system"]["ram_gb"] == 16
    assert result["system"]["iris_buffers_gb"] == 8
    conn.close()


def test_build_llm_context_timeseries_has_records():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {}, resample_interval="5min")
    ts = result["timeseries"]
    assert ts["resample_interval"] == "5min"
    assert isinstance(ts["records"], list)
    assert len(ts["records"]) > 0
    conn.close()


def test_build_llm_context_timeseries_record_has_timestamp():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {})
    rec = result["timeseries"]["records"][0]
    assert "timestamp" in rec
    from datetime import datetime
    datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S")
    conn.close()


def test_build_llm_context_findings_are_dicts():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {})
    assert isinstance(result["findings"], list)
    if result["findings"]:
        f = result["findings"][0]
        assert "metric" in f
        assert "severity" in f
        assert "chart_request" not in f
    conn.close()


def test_build_llm_context_with_context_string():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {}, context="users reported slowness")
    assert result["context"] == "users reported slowness"
    conn.close()


def test_build_llm_context_json_serialisable():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {})
    # Must not raise
    json_str = json.dumps(result)
    assert len(json_str) > 100
    conn.close()


# ---- Task 3 additions ----
from llm_context import export_llm_context


def test_export_llm_context_writes_file():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = export_llm_context(
            connection=conn,
            sp_dict={"number cpus": "4"},
            output_prefix="test_",
            filepath=tmpdir,
        )
        assert os.path.isfile(path)
        assert path.endswith(".json")
        with open(path) as fh:
            data = json.load(fh)
        assert data["schema_version"] == "1.0"
    conn.close()


def test_export_llm_context_filename_contains_dates():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = export_llm_context(conn, {}, output_prefix="", filepath=tmpdir)
        fname = os.path.basename(path)
        assert fname.startswith("performance_context_")
        assert fname.endswith(".json")
        # filename should contain a date like 2024-01-15
        assert "2024-01-15" in fname
    conn.close()


def test_export_llm_context_invalid_interval_raises():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError, match="Invalid resample interval"):
            export_llm_context(conn, {}, output_prefix="", filepath=tmpdir, resample_interval="garbage")
    conn.close()


# ---- Task 1: iostat role map ----
from llm_context import _load_iostat_role_map


def _make_conn_with_overview(rows):
    """rows: list of (field, value) tuples."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    for i, (field, value) in enumerate(rows):
        conn.execute("INSERT INTO overview VALUES (?,?,?)", (i, field, value))
    conn.commit()
    return conn


def test_load_iostat_role_map_empty_no_table():
    conn = sqlite3.connect(":memory:")
    result = _load_iostat_role_map(conn)
    assert result == {}
    conn.close()


def test_load_iostat_role_map_empty_no_role_rows():
    conn = _make_conn_with_overview([("customer", "ACME"), ("linux hostname", "srv1")])
    result = _load_iostat_role_map(conn)
    assert result == {}
    conn.close()


def test_load_iostat_role_map_filters_names_and_mount():
    conn = _make_conn_with_overview([
        ("iris disk role Database 0", "dm-5"),
        ("iris disk role Database 0 names", "IRISSYS,IRISLIB"),
        ("iris_disk_role_mount Database 0", "/trak/iris"),
        ("iris disk role Primary Journal", "dm-8"),
        ("iris_disk_role_mount Primary Journal", "/trak/jrnpri"),
    ])
    result = _load_iostat_role_map(conn)
    assert result == {"Database 0": "dm-5", "Primary Journal": "dm-8"}
    conn.close()


def test_load_iostat_role_map_returns_all_roles():
    conn = _make_conn_with_overview([
        ("iris disk role Database 0", "dm-5"),
        ("iris disk role Database 1", "dm-2"),
        ("iris disk role WIJ", "dm-3"),
        ("iris disk role Primary Journal", "dm-8"),
        ("iris disk role Alternate Journal", "dm-4"),
    ])
    result = _load_iostat_role_map(conn)
    assert len(result) == 5
    assert result["WIJ"] == "dm-3"
    conn.close()
