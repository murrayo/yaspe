import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe import align_table_columns


def test_noop_when_table_missing():
    conn = sqlite3.connect(":memory:")
    df = pd.DataFrame({"a": [1]})
    align_table_columns(conn, "vmstat", df)  # must not raise
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert tables == []


def test_day2_with_new_column_appends():
    """Day 2 gained a column: append must succeed, day-1 rows read back NULL."""
    conn = sqlite3.connect(":memory:")
    day1 = pd.DataFrame({"r": [1, 2], "us": [10, 20]})
    day1.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    day2 = pd.DataFrame({"r": [3], "us": [30], "st": [5]})
    align_table_columns(conn, "vmstat", day2)
    day2.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    rows = conn.execute("SELECT r, us, st FROM vmstat ORDER BY r").fetchall()
    assert rows == [(1, 10, None), (2, 20, None), (3, 30, 5)]


def test_day2_with_dropped_column_appends():
    """Day 2 lost a column: append must succeed, day-2 rows read back NULL."""
    conn = sqlite3.connect(":memory:")
    day1 = pd.DataFrame({"r": [1], "us": [10], "st": [5]})
    day1.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    day2 = pd.DataFrame({"r": [2], "us": [20]})
    align_table_columns(conn, "vmstat", day2)
    day2.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    rows = conn.execute("SELECT r, us, st FROM vmstat ORDER BY r").fetchall()
    assert rows == [(1, 10, 5), (2, 20, None)]


def test_added_column_types():
    conn = sqlite3.connect(":memory:")
    day1 = pd.DataFrame({"a": [1]})
    day1.to_sql("t", conn, if_exists="append", index=False)
    day2 = pd.DataFrame({"a": [2], "f": [1.5], "s": ["x"], "i": [7]})
    align_table_columns(conn, "t", day2)
    info = {row[1]: row[2] for row in conn.execute("PRAGMA table_info('t')").fetchall()}
    assert info["f"] == "REAL"
    assert info["s"] == "TEXT"
    assert info["i"] == "INTEGER"
