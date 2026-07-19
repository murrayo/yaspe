import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe import get_cpf_auto_disk_list


def _make_overview(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER PRIMARY KEY, field TEXT, value TEXT)")
    for field, value in rows:
        conn.execute("INSERT INTO overview (field, value) VALUES (?, ?)", (field, value))
    conn.commit()
    return conn


def test_auto_list_from_cpf_roles():
    conn = _make_overview([
        ("operating system", "Linux"),
        ("iris disk role Database 0", "dm-18"),
        ("iris disk role Database 1", "dm-17"),
        ("iris disk role Primary Journal", "dm-7"),
        ("iris disk role Alternate Journal", "dm-8"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["dm-18", "dm-17", "dm-7", "dm-8"]


def test_auto_list_dedupes_shared_device():
    conn = _make_overview([
        ("iris disk role Database 0", "dm-18"),
        ("iris disk role Primary Journal", "dm-18"),
        ("iris disk role WIJ", "dm-9"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["dm-18", "dm-9"]


def test_auto_list_empty_without_roles():
    conn = _make_overview([("operating system", "Linux")])
    assert get_cpf_auto_disk_list(conn) == []


def test_auto_list_stops_at_gap_in_database_index():
    # Database 0 present, Database 2 present but Database 1 missing:
    # iteration stops at the gap (matches charting-time behaviour).
    conn = _make_overview([
        ("iris disk role Database 0", "dm-18"),
        ("iris disk role Database 2", "dm-99"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["dm-18"]
