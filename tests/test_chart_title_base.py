import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe


def _make_db(rows):
    """Create an in-memory SQLite DB with an overview table populated from rows dict."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id INTEGER PRIMARY KEY AUTOINCREMENT, field TEXT NOT NULL, value TEXT)")
    for field, value in rows.items():
        conn.execute("INSERT INTO overview (field, value) VALUES (?, ?)", (field, value))
    conn.commit()
    return conn


def test_all_fields_present():
    conn = _make_db({"customer": "AcmeCorp", "linux hostname": "server01", "instance": "IRIS"})
    assert yaspe.get_chart_title_base(conn) == "AcmeCorp (server01 / IRIS)"


def test_no_instance():
    conn = _make_db({"customer": "AcmeCorp", "linux hostname": "server01"})
    assert yaspe.get_chart_title_base(conn) == "AcmeCorp (server01)"


def test_instance_empty_string():
    conn = _make_db({"customer": "AcmeCorp", "linux hostname": "server01", "instance": ""})
    assert yaspe.get_chart_title_base(conn) == "AcmeCorp (server01)"


def test_windows_hostname_fallback():
    conn = _make_db({"customer": "AcmeCorp", "windows host name": "WIN-SERVER", "instance": "CACHE"})
    assert yaspe.get_chart_title_base(conn) == "AcmeCorp (WIN-SERVER / CACHE)"


def test_no_hostname():
    conn = _make_db({"customer": "AcmeCorp"})
    assert yaspe.get_chart_title_base(conn) == "AcmeCorp"


def test_no_customer():
    conn = _make_db({"linux hostname": "server01", "instance": "IRIS"})
    assert yaspe.get_chart_title_base(conn) == ""


def test_empty_db():
    conn = _make_db({})
    assert yaspe.get_chart_title_base(conn) == ""
