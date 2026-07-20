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


def test_serialise_finding_fields():
    f = Finding(
        metric="wa",
        severity="Yellow",
        observation="wa exceeded 10%",
        when="09:00",
        corroborating=["WDQsz elevated"],
        hypotheses=["storage latency"],
        next_step="Check iostat",
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
    assert result["schema_version"] == "2.0"
    for key in ("system", "collection", "baselines", "findings",
                "period_stats", "key_metrics", "not_available", "timeseries"):
        assert key in result
    conn.close()


def test_build_llm_context_system_facts():
    conn = _make_sqlite_with_data()
    sp_dict = {"number cpus": "4", "memory MB": "16384", "globals total MB": "8192"}
    result = build_llm_context(conn, sp_dict)
    assert result["system"]["vcpus"] == 4
    assert result["system"]["ram_gb"] == 16
    assert result["system"]["iris_buffers_gb"] == 8
    assert "customer" not in result["system"]
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


def test_export_llm_context_writes_bundle_and_prompt():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path, prompt_path = export_llm_context(
            connection=conn, sp_dict={"number cpus": "4"}, filepath=tmpdir)
        assert os.path.isfile(bundle_path) and bundle_path.endswith(".md")
        assert os.path.isfile(prompt_path) and prompt_path.endswith("llm_analysis_prompt.md")
        content = open(bundle_path).read()
        assert 'schema_version: "2.0"' in content
        assert "## Timeseries" in content
        prompt = open(prompt_path).read()
        assert "consecutive" in prompt.lower()      # methodology present
        assert "Glorefs" in prompt                  # KPI tables present
        assert "illustrate" in prompt.lower()        # chart-illustration guidance present
    conn.close()


def test_export_llm_context_filename_contains_dates():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path, _ = export_llm_context(conn, {}, filepath=tmpdir)
        fname = os.path.basename(bundle_path)
        assert fname.startswith("performance_context_")
        assert fname.endswith(".md")
        assert "2024-01-15" in fname
    conn.close()


def test_export_llm_context_filenames_carry_no_site_prefix():
    """
    Filenames must never carry a site-derived prefix (yaspe.py defaults
    output_prefix from the input HTML filename, which typically embeds
    hostname/instance) — these two files are meant to leave the building.
    """
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path, prompt_path = export_llm_context(conn, {}, filepath=tmpdir)
        assert os.path.basename(bundle_path) == "performance_context_2024-01-15_2024-01-15.md"
        assert os.path.basename(prompt_path) == "llm_analysis_prompt.md"
    conn.close()


def test_export_llm_context_invalid_interval_raises():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError):
            export_llm_context(conn, {}, filepath=tmpdir, resample_interval="bogus")
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


# ---- Task 2: _resample_iostat ----
from llm_context import _resample_iostat


def _make_iostat_df(device="dm-5", n=12):
    """12 rows at 30s intervals for one device."""
    base = datetime(2024, 1, 15, 9, 0, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=30 * i),
            "Device": device,
            "r/s": float(i),
            "w/s": float(i * 2),
            "rkB/s": float(i * 10),
            "wkB/s": float(i * 20),
            "r_await": float(i) * 0.1,
            "w_await": float(i) * 0.2,
            "aqu-sz": float(i) * 0.01,
            "%util": float(i),
        })
    return pd.DataFrame(rows)


def test_resample_iostat_returns_list():
    df = _make_iostat_df()
    result = _resample_iostat(df, "dm-5", "5min")
    assert isinstance(result, list)
    assert len(result) > 0


def test_resample_iostat_json_safe_keys():
    df = _make_iostat_df()
    result = _resample_iostat(df, "dm-5", "5min")
    rec = result[0]
    assert "timestamp" in rec
    assert "r_s" in rec
    assert "w_s" in rec
    assert "rkB_s" in rec
    assert "wkB_s" in rec
    assert "r_await" in rec
    assert "w_await" in rec
    assert "aqu_sz" in rec
    assert "util" in rec
    # original names must not appear
    assert "r/s" not in rec
    assert "%util" not in rec
    assert "aqu-sz" not in rec


def test_resample_iostat_all_max():
    df = _make_iostat_df(n=12)
    result = _resample_iostat(df, "dm-5", "5min")
    # r/s values 0..11; first 5min bucket (10 rows at 30s) max = 9
    assert result[0]["r_s"] == pytest.approx(9.0, abs=1.0)


def test_resample_iostat_unknown_device_returns_empty():
    df = _make_iostat_df(device="dm-5")
    result = _resample_iostat(df, "dm-99", "5min")
    assert result == []


def test_resample_iostat_timestamp_format():
    df = _make_iostat_df()
    result = _resample_iostat(df, "dm-5", "5min")
    datetime.strptime(result[0]["timestamp"], "%Y-%m-%d %H:%M:%S")


# ---- Task 3: _build_iostat_timeseries + build_llm_context integration ----
from llm_context import _build_iostat_timeseries


def _make_sqlite_with_iostat():
    """SQLite with overview roles + iostat table for dm-5 and dm-8."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    overview_rows = [
        (0, "iris disk role Database 0", "dm-5"),
        (1, "iris disk role Database 0 names", "IRISSYS,IRISLIB"),
        (2, "iris_disk_role_mount Database 0", "/trak/iris"),
        (3, "iris disk role Primary Journal", "dm-8"),
        (4, "iris_disk_role_mount Primary Journal", "/trak/jrnpri"),
    ]
    conn.executemany("INSERT INTO overview VALUES (?,?,?)", overview_rows)

    conn.execute("""
        CREATE TABLE iostat (
            id_key INTEGER, RunDate TEXT, RunTime TEXT, Device TEXT,
            "r/s" REAL, "w/s" REAL, "rkB/s" REAL, "wkB/s" REAL,
            "rrqm/s" REAL, "wrqm/s" REAL, "%rrqm" REAL, "%wrqm" REAL,
            r_await REAL, w_await REAL, "aqu-sz" REAL,
            "rareq-sz" REAL, "wareq-sz" REAL, svctm REAL, "%util" REAL,
            "html name" TEXT, datetime TEXT
        )
    """)
    from datetime import datetime as _dt, timedelta
    base = _dt(2024, 1, 15, 9, 0, 0)
    for i in range(20):
        ts = base + timedelta(seconds=30 * i)
        dt_str = ts.strftime("%Y/%m/%d %I:%M:%S %p")
        for device in ("dm-5", "dm-8"):
            conn.execute(
                """INSERT INTO iostat VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (i, ts.strftime("%Y/%m/%d"), ts.strftime("%I:%M:%S %p"), device,
                 float(i), float(i*2), float(i*10), float(i*20),
                 0.0, 0.0, 0.0, 0.0,
                 float(i)*0.1, float(i)*0.2, float(i)*0.01,
                 0.0, 0.0, 0.0, float(i),
                 "test_html", dt_str)
            )
    conn.commit()
    return conn


def test_build_iostat_timeseries_returns_list():
    conn = _make_sqlite_with_iostat()
    result = _build_iostat_timeseries(conn, "5min")
    assert isinstance(result, list)
    conn.close()


def test_build_iostat_timeseries_has_both_roles():
    conn = _make_sqlite_with_iostat()
    result = _build_iostat_timeseries(conn, "5min")
    roles = [r["role"] for r in result]
    assert "Database 0" in roles
    assert "Primary Journal" in roles
    conn.close()


def test_build_iostat_timeseries_role_structure():
    conn = _make_sqlite_with_iostat()
    result = _build_iostat_timeseries(conn, "5min")
    db_entry = next(r for r in result if r["role"] == "Database 0")
    assert db_entry["device"] == "dm-5"
    assert isinstance(db_entry["records"], list)
    assert len(db_entry["records"]) > 0
    rec = db_entry["records"][0]
    assert "timestamp" in rec
    assert "r_s" in rec
    assert "util" in rec
    conn.close()


def test_build_iostat_timeseries_empty_when_no_roles():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    conn.execute("CREATE TABLE iostat (id_key INTEGER, RunDate TEXT, RunTime TEXT, Device TEXT, datetime TEXT)")
    conn.commit()
    result = _build_iostat_timeseries(conn, "5min")
    assert result == []
    conn.close()


def test_build_iostat_timeseries_empty_when_no_iostat_table():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    conn.execute("INSERT INTO overview VALUES (0, 'iris disk role Database 0', 'dm-5')")
    conn.commit()
    result = _build_iostat_timeseries(conn, "5min")
    assert result == []
    conn.close()


def test_build_llm_context_iostat_present():
    conn = _make_sqlite_with_iostat()
    # Also need mgstat + vmstat for build_llm_context
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
    conn.commit()
    result = build_llm_context(conn, {})
    assert "iostat" in result["timeseries"]
    roles = [r["role"] for r in result["timeseries"]["iostat"]]
    assert "Database 0" in roles
    json.dumps(result)  # must not raise (NaN leak check)
    conn.close()


def test_build_llm_context_iostat_absent_when_no_table():
    conn = _make_sqlite_with_data()  # existing helper — no overview roles, no iostat table
    result = build_llm_context(conn, {})
    assert "iostat" not in result["timeseries"]
    conn.close()


# ---- Period stats ----
from llm_context import _compute_period_stats, _series_stats


def _make_mg_df_business_hours(n=20):
    """20 rows at 60s starting Tue 2024-01-16 09:30 — inside period 09:00–11:30."""
    base = datetime(2024, 1, 16, 9, 30, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=60 * i),
            "Glorefs": 10000 + i * 100,
            "Gloupds": 500,
            "PhyRds": 50,
            "PhyWrs": 20,
            "Jrnwrts": 30,
            "Rdratio": 95.0,
            "WDQsz": i,
        })
    return pd.DataFrame(rows)


def _make_vm_df_business_hours(n=20):
    base = datetime(2024, 1, 16, 9, 30, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=60 * i),
            "r": i, "b": 0, "us": 30.0, "sy": 10.0, "wa": 2.0, "si": 0, "so": 0,
        })
    return pd.DataFrame(rows)


def test_series_stats_keys():
    s = _series_stats(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert set(s) == {"mean", "sigma", "p90", "p95", "max", "n_samples"}
    assert s["mean"] == pytest.approx(2.5)
    assert s["max"] == 4.0
    assert s["n_samples"] == 4


def test_series_stats_empty_returns_none():
    assert _series_stats(pd.Series([], dtype=float)) is None
    assert _series_stats(pd.Series(["x", None])) is None


def test_period_stats_bucketing():
    result = _compute_period_stats(_make_mg_df_business_hours(), _make_vm_df_business_hours())
    assert len(result) == 1
    entry = result[0]
    assert entry["weekday"] == "Tuesday"
    assert entry["period"] == "09:00–11:30"
    assert "Glorefs" in entry["metrics"]
    assert "r" in entry["metrics"]


def test_period_stats_us_sy_derived():
    result = _compute_period_stats(pd.DataFrame(), _make_vm_df_business_hours())
    assert result[0]["metrics"]["us_sy"]["mean"] == pytest.approx(40.0)


def test_period_stats_has_p90():
    result = _compute_period_stats(_make_mg_df_business_hours(), pd.DataFrame())
    g = result[0]["metrics"]["Glorefs"]
    assert "p90" in g and "p95" in g
    assert g["p90"] <= g["p95"] <= g["max"]


def test_period_stats_empty_inputs():
    assert _compute_period_stats(pd.DataFrame(), pd.DataFrame()) == []


def test_period_stats_ppgupds_when_present():
    mg = _make_mg_df_business_hours()
    mg["PPGupds"] = 250.0
    result = _compute_period_stats(mg, pd.DataFrame())
    assert result[0]["metrics"]["PPGupds"]["mean"] == pytest.approx(250.0)


# ---- Key metrics + not_available ----
from llm_context import _compute_key_metrics, _build_not_available


def _make_iostat_role_df(n=20):
    """iostat rows for one Database device (dm-3) and one IRIS device (dm-9)."""
    base = datetime(2024, 1, 16, 9, 30, 0)
    rows = []
    for i in range(n):
        for dev, r_s, w_s, r_await, w_await in (("dm-3", 200.0, 100.0, 1.5, 0.8),
                                                ("dm-9", 5.0, 50.0, 0.5, 0.6)):
            rows.append({
                "dt": pd.Timestamp(base) + pd.Timedelta(seconds=60 * i),
                "Device": dev, "r/s": r_s, "w/s": w_s,
                "r_await": r_await, "w_await": w_await,
            })
    return pd.DataFrame(rows)


_FACTS = {"vcpus": 4, "ram_gb": 16, "iris_buffers_gb": 8, "version": "x", "os": "Linux"}
_ROLE_MAP = {"Database 0": "dm-3", "IRIS 0": "dm-9"}


def test_key_metrics_ratio_from_sums():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    # PhyRds=50, PhyWrs=20 constant → sum ratio = 2.5
    assert km["overall"]["physical_read_write_ratio"]["value"] == pytest.approx(2.5)


def test_key_metrics_cpu_distribution():
    km = _compute_key_metrics(pd.DataFrame(), _make_vm_df_business_hours(), pd.DataFrame(), {}, _FACTS)
    cpu = km["overall"]["cpu_utilization"]["value"]
    assert cpu["mean"] == pytest.approx(40.0)
    assert "p95" in cpu


def test_key_metrics_glorefs_per_core():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    g = km["overall"]["glorefs_distribution"]["value"]
    gpc = km["overall"]["glorefs_per_core"]["value"]
    assert gpc["max"] == pytest.approx(g["max"] / 4)


def test_key_metrics_db_disk_from_role():
    km = _compute_key_metrics(pd.DataFrame(), pd.DataFrame(), _make_iostat_role_df(), _ROLE_MAP, _FACTS)
    o = km["overall"]
    assert o["db_disk_reads_per_sec"]["value"]["mean"] == pytest.approx(200.0)
    assert o["db_disk_read_response_ms"]["value"]["mean"] == pytest.approx(1.5)
    assert o["db_disk_read_write_ratio"]["value"] == pytest.approx(2.0)


def test_key_metrics_ppg_conditional():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    assert "ppg_update_rate" not in km["overall"]
    mg["PPGupds"] = 250.0
    km2 = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    assert km2["overall"]["ppg_update_rate"]["value"]["mean"] == pytest.approx(250.0)
    assert km2["overall"]["ppg_to_global_update_ratio"]["value"] == pytest.approx(0.5)


def test_key_metrics_max_memory():
    # free=8000000 KB + cache=2000000 KB of 16 GB (16777216 KB) → used ≈ 40.4%
    vm = _make_vm_df_business_hours()
    vm["free"] = 8000000
    vm["cache"] = 2000000
    km = _compute_key_metrics(pd.DataFrame(), vm, pd.DataFrame(), {}, _FACTS)
    val = km["overall"]["max_memory_utilization_pct"]["value"]
    assert val == pytest.approx((16 * 1024 * 1024 - 10000000) / (16 * 1024 * 1024) * 100, abs=0.5)


def test_key_metrics_peak_period():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    peak = km["peak_period"]
    assert peak["weekday"] == "Tuesday"
    assert peak["period"] == "09:00–11:30"
    assert "glorefs_distribution" in peak["metrics"]


def test_not_available_static_entries():
    na = _build_not_available(pd.DataFrame(), {})
    metrics = [e["metric"] for e in na]
    assert any("transaction rate" in m for m in metrics)
    assert any("kill" in m for m in metrics)
    assert all({"metric", "reason", "how_to_collect"} <= set(e) for e in na)


def test_not_available_ppg_conditional():
    mg = _make_mg_df_business_hours()
    na = _build_not_available(mg, {"Database 0": "dm-3"})
    assert any("PPG" in e["metric"] for e in na)
    mg["PPGupds"] = 1.0
    na2 = _build_not_available(mg, {"Database 0": "dm-3"})
    assert not any("PPG" in e["metric"] for e in na2)


def test_not_available_db_disk_conditional():
    na = _build_not_available(pd.DataFrame(), {})
    assert any("disk" in e["metric"].lower() for e in na)
    na2 = _build_not_available(pd.DataFrame(), {"Database 0": "dm-3"})
    assert not any(e["metric"] == "database disk I/O metrics" for e in na2)


# ---- Anonymization scrub ----
from llm_context import _gather_secrets, _scrub


def test_gather_secrets_collects_identifiers():
    sp = {"customer": "Acme Hospital", "linux hostname": "acmedb01.acme.local",
          "instance": "ACMEPROD", "up instance 1": "ACMEPROD on machine acmedb01"}
    secrets = _gather_secrets(sp)
    assert "Acme Hospital" in secrets
    assert "acmedb01.acme.local" in secrets
    assert "acmedb01" in secrets          # short-hostname variant of the FQDN
    assert "ACMEPROD" in secrets


def test_gather_secrets_skips_short_and_allowlisted():
    sp = {"customer": "abc", "instance": "IRIS", "linux hostname": "prod"}
    assert _gather_secrets(sp) == []


def test_gather_secrets_longest_first():
    sp = {"customer": "Acme", "linux hostname": "acmedb01.acme.local"}
    secrets = _gather_secrets(sp)
    assert secrets[0] == "acmedb01.acme.local"


def test_scrub_redacts_case_insensitive_nested():
    secrets = ["Acme Hospital", "acmedb01"]
    obj = {"note": "Users at ACME HOSPITAL reported slowness",
           "list": [{"deep": "host acmedb01 was rebooted"}]}
    out = _scrub(obj, secrets)
    assert out["note"] == "Users at [redacted] reported slowness"
    assert out["list"][0]["deep"] == "host [redacted] was rebooted"


def test_scrub_word_boundary_no_partial_mangling():
    out = _scrub("The acmedb011 host and acmedb01 host", ["acmedb01"])
    # acmedb011 is a different token — must NOT be redacted
    assert out == "The acmedb011 host and [redacted] host"


def test_scrub_non_string_passthrough():
    assert _scrub(42, ["secret"]) == 42
    assert _scrub(None, ["secret"]) is None
    assert _scrub(3.14, ["secret"]) == 3.14


def test_scrub_empty_secrets_identity():
    obj = {"a": "unchanged"}
    assert _scrub(obj, []) == obj


def test_scrub_redacts_dict_keys():
    out = _scrub({"acmedb01": {"nested": "on acmedb01"}}, ["acmedb01"])
    assert out == {"[redacted]": {"nested": "on [redacted]"}}


# ---- Schema 2.0 integration ----

def test_build_llm_context_no_customer_even_when_present():
    conn = _make_sqlite_with_data()
    sp_dict = {"number cpus": "4", "customer": "Acme Hospital"}
    result = build_llm_context(conn, sp_dict)
    assert "customer" not in result["system"]
    conn.close()


def test_build_llm_context_scrubs_context_note():
    conn = _make_sqlite_with_data()
    sp_dict = {"customer": "Acme Hospital", "linux hostname": "acmedb01"}
    result = build_llm_context(conn, sp_dict, context="Acme Hospital users on acmedb01 reported slowness")
    assert "Acme Hospital" not in result["context"]
    assert "acmedb01" not in result["context"]
    assert "[redacted]" in result["context"]
    conn.close()


def test_build_llm_context_period_stats_populated():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {})
    assert isinstance(result["period_stats"], list)
    # _make_sqlite_with_data rows start 09:00 → inside 09:00–11:30
    assert result["period_stats"], "expected at least one period bucket"
    assert "Glorefs" in result["period_stats"][0]["metrics"]
    conn.close()


def test_build_llm_context_key_metrics_populated():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {"number cpus": "4", "memory MB": "16384"})
    assert "physical_read_write_ratio" in result["key_metrics"]["overall"]
    assert result["key_metrics"]["peak_period"] is not None
    conn.close()


def test_build_llm_context_not_available_populated():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {})
    assert any("transaction rate" in e["metric"] for e in result["not_available"])
    conn.close()


def test_auto_resample_interval_boundaries():
    from llm_context import _auto_resample_interval
    assert _auto_resample_interval(None) == "5min"
    assert _auto_resample_interval(1) == "5min"
    assert _auto_resample_interval(2) == "5min"
    assert _auto_resample_interval(3) == "15min"
    assert _auto_resample_interval(4) == "15min"
    assert _auto_resample_interval(5) == "30min"
    assert _auto_resample_interval(7) == "30min"


def test_build_llm_context_auto_resample_default():
    conn = _make_sqlite_with_data()
    # fixture is a single day → auto resolves to 5min
    result = build_llm_context(conn, {})
    assert result["timeseries"]["resample_interval"] == "5min"
    conn.close()


def test_build_llm_context_explicit_resample_wins():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {}, resample_interval="10min")
    assert result["timeseries"]["resample_interval"] == "10min"
    conn.close()


# ---- Markdown renderer ----
import io
from llm_context import _fmt_num, _csv_block, _render_markdown


def test_fmt_num_rules():
    assert _fmt_num(None) == ""
    assert _fmt_num(12345.678) == "12346"        # >=100 → integer
    assert _fmt_num(18.349) == "18.3"            # <100 → 1 decimal
    assert _fmt_num(2.5, ratio=True) == "2.50"   # ratio → 2 decimals
    assert _fmt_num(7) == "7"
    assert _fmt_num("2024-01-15 09:00:00") == "2024-01-15 09:00:00"


def test_csv_block_shape():
    records = [{"timestamp": "2024-01-15 09:00:00", "Glorefs": 10450.333, "us": None}]
    block = _csv_block(records, ["timestamp", "Glorefs", "us"])
    assert block.startswith("```csv\n")
    assert block.endswith("\n```")
    lines = block.splitlines()
    assert lines[1] == "timestamp,Glorefs,us"
    assert lines[2] == "2024-01-15 09:00:00,10450,"   # rounded, empty cell for None


def _built_ctx():
    conn = _make_sqlite_with_data()
    ctx = build_llm_context(conn, {"number cpus": "4", "memory MB": "16384"},
                            context="users reported slowness")
    conn.close()
    return ctx


def test_render_markdown_yaml_header():
    md = _render_markdown(_built_ctx())
    assert md.startswith("---\n")
    header = md.split("---")[1]
    assert 'schema_version: "2.0"' in header
    assert "customer" not in header
    import yaml
    parsed = yaml.safe_load(header)
    assert parsed["schema_version"] == "2.0"
    assert parsed["system"]["vcpus"] == 4


def test_render_markdown_sections_present():
    md = _render_markdown(_built_ctx())
    for heading in ("## Findings", "## Key metrics", "## Not available",
                    "## Period statistics", "## Timeseries"):
        assert heading in md, f"missing {heading}"


def test_render_markdown_timeseries_csv_roundtrip():
    md = _render_markdown(_built_ctx())
    ts_section = md.split("## Timeseries")[1]
    csv_text = ts_section.split("```csv\n")[1].split("\n```")[0]
    df = pd.read_csv(io.StringIO(csv_text))
    assert "timestamp" in df.columns
    assert "Glorefs" in df.columns
    assert len(df) > 0


def test_render_markdown_no_full_float_repr():
    md = _render_markdown(_built_ctx())
    import re as _re
    assert not _re.search(r"\d+\.\d{4,}", md), "unrounded float leaked into bundle"


def test_yaml_header_rounds_float_interval():
    ctx = _built_ctx()
    ctx["collection"]["interval_seconds"] = 4.999000000001
    md = _render_markdown(ctx)
    import yaml
    parsed = yaml.safe_load(md.split("---")[1])
    assert parsed["collection"]["interval_seconds"] == 5.0


def test_yaml_header_context_with_quotes_parses():
    ctx = _built_ctx()
    ctx["context"] = 'users said "slow" on Tuesday \\ Wednesday'
    md = _render_markdown(ctx)
    import yaml
    parsed = yaml.safe_load(md.split("---")[1])
    assert 'slow' in parsed["context"]


def test_yaml_header_survives_redacted_system_value():
    ctx = _built_ctx()
    ctx["system"]["version"] = "[redacted] 2022.1 (Build 205)"
    md = _render_markdown(ctx)
    import yaml
    parsed = yaml.safe_load(md.split("---")[1])
    assert parsed["system"]["version"] == "[redacted] 2022.1 (Build 205)"


def test_table_cells_escape_pipes():
    ctx = _built_ctx()
    ctx["not_available"].append(
        {"metric": "x|y", "reason": "a|b", "how_to_collect": "c"})
    md = _render_markdown(ctx)
    assert "x\\|y" in md


# ---- Datetime parsing (uniform-format fast path) ----
import warnings as _warnings
from llm_context import _parse_datetime_series


def test_parse_datetime_series_ampm_no_warning():
    s = pd.Series(["2026/04/30 12:00:00 AM", "2026/04/30 12:00:05 AM",
                   "2026/04/30 01:15:00 PM"])
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        out = _parse_datetime_series(s)
    assert not [w for w in caught if "Could not infer format" in str(w.message)]
    assert out.tolist() == [pd.Timestamp("2026-04-30 00:00:00"),
                            pd.Timestamp("2026-04-30 00:00:05"),
                            pd.Timestamp("2026-04-30 13:15:00")]


def test_parse_datetime_series_24h():
    s = pd.Series(["2026/04/30 23:59:56", "2026/05/01 00:00:01"])
    out = _parse_datetime_series(s)
    assert out.tolist() == [pd.Timestamp("2026-04-30 23:59:56"),
                            pd.Timestamp("2026-05-01 00:00:01")]


def test_parse_datetime_series_mixed_falls_back():
    # Uniform-format fast path can't parse mixed input; must still coerce per-element
    s = pd.Series(["2026/04/30 10:00:00", "30 April 2026 10:05:00", "garbage"])
    out = _parse_datetime_series(s)
    assert out.iloc[0] == pd.Timestamp("2026-04-30 10:00:00")
    assert out.iloc[1] == pd.Timestamp("2026-04-30 10:05:00")
    assert pd.isna(out.iloc[2])


def test_load_iostat_df_ampm_no_warning():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE iostat (RunDate TEXT, RunTime TEXT, datetime TEXT, Device TEXT, \"r/s\" REAL)")
    for i in range(5):
        conn.execute("INSERT INTO iostat VALUES (?,?,?,?,?)",
                     ("2026/04/30", f"12:00:{i:02d} AM", f"2026/04/30 12:00:{i:02d} AM", "dm-3", 10.0))
    conn.commit()
    from llm_context import _load_iostat_df
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        df = _load_iostat_df(conn)
    assert not [w for w in caught if "Could not infer format" in str(w.message)]
    assert len(df) == 5
    assert df["dt"].iloc[0] == pd.Timestamp("2026-04-30 00:00:00")
    conn.close()
