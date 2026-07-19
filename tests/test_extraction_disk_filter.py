import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe
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


def test_auto_list_windows_drive_letters():
    conn = _make_overview([
        ("operating system", "Windows"),
        ("iris disk role Database 0", "C:"),
        ("iris disk role Database 1", "G:"),
        ("iris disk role Primary Journal", "J:"),
        ("iris disk role WIJ", "W:"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["C:", "G:", "J:", "W:"]


def _stub_extract_sections_recording(recorded):
    """Return a stub matching extract_sections' signature that records the
    disk_list it was called with and returns 7 empty DataFrames, so
    create_sections skips all to_sql/csv work downstream."""

    def _stub(operating_system, input_file, include_iostat, include_nfsiostat, html_filename, disk_list):
        recorded["disk_list"] = disk_list
        empty = pd.DataFrame({"empty": []})
        return empty, empty, empty, empty, empty, empty, empty

    return _stub


def test_create_sections_wires_windows_auto_disk_list(monkeypatch):
    conn = _make_overview([
        ("operating system", "Windows"),
        ("iris disk role Database 0", "C:"),
        ("iris disk role Primary Journal", "J:"),
    ])
    recorded = {}
    monkeypatch.setattr(yaspe, "extract_sections", _stub_extract_sections_recording(recorded))

    yaspe.create_sections(conn, "unused.html", True, False, "t.html", False, "/tmp/unused_", [], False)

    assert recorded["disk_list"] == ["C:", "J:"]


def test_create_sections_wires_linux_auto_disk_list(monkeypatch):
    conn = _make_overview([
        ("operating system", "Linux"),
        ("iris disk role Database 0", "dm-1"),
    ])
    recorded = {}
    monkeypatch.setattr(yaspe, "extract_sections", _stub_extract_sections_recording(recorded))

    yaspe.create_sections(conn, "unused.html", True, False, "t.html", False, "/tmp/unused_", [], False)

    assert recorded["disk_list"] == ["dm-1"]


def test_create_sections_all_disks_suppresses_auto_list(monkeypatch):
    conn = _make_overview([
        ("operating system", "Windows"),
        ("iris disk role Database 0", "C:"),
        ("iris disk role Primary Journal", "J:"),
    ])
    recorded = {}
    monkeypatch.setattr(yaspe, "extract_sections", _stub_extract_sections_recording(recorded))

    yaspe.create_sections(conn, "unused.html", True, False, "t.html", False, "/tmp/unused_", [], False, True)

    assert recorded["disk_list"] == []
