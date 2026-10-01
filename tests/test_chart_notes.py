import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe
from chart_notes import (column_note, VMSTAT_COLUMN_NOTES, MGSTAT_COLUMN_NOTES,
                         FREE_MEMORY_COLUMN_NOTES, IOSTAT_COLUMN_NOTES)


def test_column_note_two_lines():
    note = column_note(VMSTAT_COLUMN_NOTES, "so")
    what, look_for = note.split("\n")
    assert "swap" in what
    assert look_for.startswith("Should be 0")


def test_column_note_unknown_is_empty():
    assert column_note(VMSTAT_COLUMN_NOTES, "not_a_column") == ""


def test_cpu_and_run_queue_columns_not_overridden():
    for col in ("Total CPU", "r", "us", "sy", "r per core"):
        assert col not in VMSTAT_COLUMN_NOTES


def test_aliases_expanded():
    assert IOSTAT_COLUMN_NOTES["aqu-sz"] == IOSTAT_COLUMN_NOTES["avgqu-sz"]
    assert MGSTAT_COLUMN_NOTES["pGblNsz"] == MGSTAT_COLUMN_NOTES["pObjNsz"]
    assert "buf/cache" in FREE_MEMORY_COLUMN_NOTES


def test_wrap_lines_keeps_line_breaks():
    lines = yaspe._wrap_lines("first line\nsecond line", 180)
    assert lines == ["first line", "second line"]


def test_wrap_lines_wraps_each_line():
    lines = yaspe._wrap_lines(("a " * 100) + "\nshort", 50)
    assert lines[-1] == "short"
    assert len(lines) > 2


def test_plotly_footnote_height_counts_both_lines():
    import plotly.graph_objects as go
    fig = go.Figure()
    height = yaspe._add_plotly_footnote(fig, "one\ntwo", 500)
    assert height == 500 + 16 * 2 + 10
    assert fig.layout.annotations[0].text == "one<br>two"
