# tests/test_combined_overlay.py
import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaspe_combined_overlay as yco


def test_load_dataframes_empty_for_missing_tables():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.close()
        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert mgstat_df.empty
        assert vmstat_df.empty
    finally:
        os.unlink(db_path)


def test_load_dataframes_reads_mgstat_and_computes_total_cpu():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE mgstat (id INTEGER PRIMARY KEY, datetime TEXT, Glorefs REAL)"
        )
        conn.execute("INSERT INTO mgstat VALUES (1, '2026-04-30 10:00:00', 99.0)")
        conn.execute(
            "CREATE TABLE vmstat (rowid_ INTEGER PRIMARY KEY, datetime TEXT, us REAL, sy REAL, id REAL, wa REAL)"
        )
        conn.execute("INSERT INTO vmstat VALUES (1, '2026-04-30 10:00:00', 10.0, 5.0, 80.0, 5.0)")
        conn.commit()
        conn.close()

        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert len(mgstat_df) == 1
        assert len(vmstat_df) == 1
        # Total CPU = 100 - id
        assert vmstat_df["Total CPU"].iloc[0] == 20.0
    finally:
        os.unlink(db_path)


def test_detect_datetime_column_finds_datetime_lowercase():
    df = pd.DataFrame({"datetime": ["2026-04-30 10:00:00"], "val": [1.0]})
    assert yco._detect_datetime_column(df) == "datetime"


def test_detect_datetime_column_finds_DateTime():
    df = pd.DataFrame({"DateTime": ["2026-04-30 10:00:00"], "val": [1.0]})
    assert yco._detect_datetime_column(df) == "DateTime"


def test_detect_datetime_column_returns_empty_when_not_found():
    df = pd.DataFrame({"value": [1.0], "count": [2.0]})
    assert yco._detect_datetime_column(df) == ""


def _make_mgstat_df():
    return pd.DataFrame({
        "datetime": pd.date_range("2026-04-30 10:00", periods=5, freq="min").astype(str),
        "WIJwri":  [1.0, 2.0, 3.0, 4.0, 5.0],
        "PhyRds":  [10.0, 11.0, 12.0, 13.0, 14.0],
        "PhyWrs":  [5.0, 6.0, 7.0, 8.0, 9.0],
        "Jrnwrts": [0.1, 0.2, 0.3, 0.4, 0.5],
        "Rourefs": [100.0, 110.0, 120.0, 130.0, 140.0],
        "RouLaS":  [2.0, 2.1, 2.2, 2.3, 2.4],
        "RouCMs":  [0.0, 0.0, 0.1, 0.0, 0.0],
        "Gloupds": [50.0, 51.0, 52.0, 53.0, 54.0],
        "Glorefs": [200.0, 210.0, 220.0, 230.0, 240.0],
    })


def _make_vmstat_df():
    df = pd.DataFrame({
        "datetime": pd.date_range("2026-04-30 10:00", periods=5, freq="min").astype(str),
        "us": [10.0, 12.0, 11.0, 13.0, 10.0],
        "sy": [3.0, 4.0, 3.0, 5.0, 3.0],
        "wa": [2.0, 1.0, 2.0, 1.0, 2.0],
        "id": [85.0, 83.0, 84.0, 81.0, 85.0],
    })
    df["Total CPU"] = 100 - df["id"]
    return df


def test_build_combined_chart_writes_html():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "combined_overlay.html")
        yco._build_combined_chart(
            _make_mgstat_df(),
            _make_vmstat_df(),
            "datetime",
            "datetime",
            out_path,
        )
        assert os.path.exists(out_path)
        with open(out_path) as f:
            html = f.read()
        assert "WIJwri" in html
        assert "Rourefs" in html
        assert "Glorefs" in html
        assert "wa" in html


def test_build_combined_chart_skips_missing_columns(capsys):
    mg = _make_mgstat_df().drop(columns=["PhyWrs"])
    vm = _make_vmstat_df()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "combined_overlay.html")
        yco._build_combined_chart(mg, vm, "datetime", "datetime", out_path)
        captured = capsys.readouterr()
        assert "PhyWrs" in captured.out
        assert os.path.exists(out_path)


def test_build_combined_chart_skips_missing_vmstat_column(capsys):
    mg = _make_mgstat_df()
    vm = _make_vmstat_df().drop(columns=["wa"])
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "combined_overlay.html")
        yco._build_combined_chart(mg, vm, "datetime", "datetime", out_path)
        captured = capsys.readouterr()
        assert "wa" in captured.out
        assert os.path.exists(out_path)
