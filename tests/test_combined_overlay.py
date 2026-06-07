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
