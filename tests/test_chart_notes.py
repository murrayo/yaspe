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
    assert IOSTAT_COLUMN_NOTES["rareq-sz"] == IOSTAT_COLUMN_NOTES["wareq-sz"]
    assert "buf/cache" in FREE_MEMORY_COLUMN_NOTES


def test_seize_columns_follow_the_mgstat_docs():
    # ^mgstat docs: GblSz = seizes on the global resource, pGblNsz/pGblAsz = % NSeizes / % ASeizes
    for res in ("Gbl", "Rou", "Obj", "BDB"):
        assert "seize" in MGSTAT_COLUMN_NOTES[f"{res}Sz"][0].lower()
        assert "buffer" not in MGSTAT_COLUMN_NOTES[f"{res}Sz"][0].lower()
        assert "sleep" in MGSTAT_COLUMN_NOTES[f"p{res}Nsz"][0]
        assert "spin" in MGSTAT_COLUMN_NOTES[f"p{res}Asz"][0]
    assert MGSTAT_COLUMN_NOTES["pGblNsz"] != MGSTAT_COLUMN_NOTES["pObjNsz"]
    assert "undocumented" in MGSTAT_COLUMN_NOTES["BDBSz"][0]


def test_write_daemon_columns_follow_the_mgstat_docs():
    assert MGSTAT_COLUMN_NOTES["IJUcnt"][0].startswith("Jobs the write daemon is waiting for")
    assert "IRISTEMP" in MGSTAT_COLUMN_NOTES["WDtmpq"][0]
    assert "5" in MGSTAT_COLUMN_NOTES["WDphase"][0] and "8" in MGSTAT_COLUMN_NOTES["WDphase"][0]
    assert "running count" in MGSTAT_COLUMN_NOTES["WDpass"][0]
    assert "256 KB" in MGSTAT_COLUMN_NOTES["WIJwri"][0]
    assert "short of global buffers" in MGSTAT_COLUMN_NOTES["PrgBufL"][0]
    assert "or sooner" in MGSTAT_COLUMN_NOTES["PhyWrs"][1]


def test_vmstat_factual_corrections():
    assert "VMware" in VMSTAT_COLUMN_NOTES["st"][1]
    assert "averaged over all CPUs" in VMSTAT_COLUMN_NOTES["wa"][1]
    assert "1 block = 1 KB" in VMSTAT_COLUMN_NOTES["bi"][0]
    assert "1 block = 1 KB" in VMSTAT_COLUMN_NOTES["bo"][0]


def test_aix_vmstat_columns_have_notes():
    for col in ("avm", "fre", "pi", "po", "fr", "sr", "pc", "ec"):
        assert col in VMSTAT_COLUMN_NOTES, col
        assert "AIX" in VMSTAT_COLUMN_NOTES[col][0]


def test_aix_iostat_columns_have_notes():
    for col in ("xfer tm act", "xfer bps", "xfer tps", "xfer bread", "xfer bwrtn",
                "read min serv", "write min serv", "queue min time", "queue max time"):
        assert col in IOSTAT_COLUMN_NOTES, col


def test_request_size_units_differ_between_iostat_versions():
    assert "KB" in IOSTAT_COLUMN_NOTES["rareq-sz"][0]
    assert "sectors" in IOSTAT_COLUMN_NOTES["avgrq-sz"][0]
    assert "16 sectors" in IOSTAT_COLUMN_NOTES["avgrq-sz"][1]


def test_read_and_write_latency_notes_differ():
    assert IOSTAT_COLUMN_NOTES["r_await"][1] != IOSTAT_COLUMN_NOTES["w_await"][1]
    assert "journal" in IOSTAT_COLUMN_NOTES["w_await"][1].lower()
    assert IOSTAT_COLUMN_NOTES["read avg serv"][1] == IOSTAT_COLUMN_NOTES["r_await"][1]
    assert IOSTAT_COLUMN_NOTES["write avg serv"][1] == IOSTAT_COLUMN_NOTES["w_await"][1]


def test_no_vague_filler_phrases():
    all_notes = {**VMSTAT_COLUMN_NOTES, **MGSTAT_COLUMN_NOTES, **FREE_MEMORY_COLUMN_NOTES, **IOSTAT_COLUMN_NOTES}
    for col, (what, look) in all_notes.items():
        assert look != "Informational.", col
        assert not look.startswith("Tracks with"), col


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
