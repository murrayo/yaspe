import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe

FOOT = "CPU topology (lscpu): test footnote. Review the processor architecture before making capacity assumptions."


def _df(periods=10, freq="1min"):
    times = pd.date_range("2024-01-15 09:00", periods=periods, freq=freq)
    return pd.DataFrame({"datetime_parsed": times, "datetime": times, "metric": np.arange(periods, dtype=float)})


def _capture_png(fn, *args, **kwargs):
    captured = {}

    def fake_savefig(*a, **k):
        import matplotlib.pyplot as plt
        captured["fig_texts"] = [t.get_text() for t in plt.gcf().texts]
        captured["savefig_kwargs"] = k

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), patch("matplotlib.pyplot.close"):
        fn(*args, **kwargs)
    return captured


def test_png_footnote_helper_adds_wrapped_text():
    import matplotlib.pyplot as plt
    fig, _ = plt.subplots()
    yaspe._add_png_footnote(fig, "word " * 100)
    assert len(fig.texts) == 1
    assert "\n" in fig.texts[0].get_text()
    plt.close(fig)


def test_png_footnote_helper_empty_is_noop():
    import matplotlib.pyplot as plt
    fig, _ = plt.subplots()
    yaspe._add_png_footnote(fig, "")
    assert fig.texts == []
    plt.close(fig)


def test_simple_chart_footnote(tmp_path):
    c = _capture_png(yaspe.simple_chart, _df(), "Total CPU", "T", 100, str(tmp_path) + "/", "", footnote=FOOT)
    assert any("test footnote" in t for t in c["fig_texts"])


def test_simple_chart_without_footnote_unchanged(tmp_path):
    c = _capture_png(yaspe.simple_chart, _df(), "Total CPU", "T", 100, str(tmp_path) + "/", "")
    assert not any("footnote" in t for t in c["fig_texts"])


def test_simple_chart_forwards_footnote_to_peak_chart(tmp_path):
    with patch.object(yaspe, "_create_peak_60_chart", return_value=(None, None)) as peak, \
         patch.object(yaspe, "_create_business_hours_peak_chart") as bh:
        _capture_png(yaspe.simple_chart, _df(periods=600), "Total CPU", "T", 100, str(tmp_path) + "/", "",
                     min_max=True, peak_chart=True, business_hours_chart=True, footnote=FOOT)
    assert peak.call_args.kwargs.get("footnote") == FOOT
    assert bh.call_args.kwargs.get("footnote") == FOOT


def test_stacked_chart_footnote_and_tight_bbox(tmp_path):
    times = pd.date_range("2024-01-15 09:00", periods=10, freq="1min")
    df = pd.DataFrame({"datetime_parsed": times, "datetime": times,
                       "sy": np.ones(10), "wa": np.ones(10), "us": np.ones(10)})
    c = _capture_png(yaspe.simple_chart_stacked, df, "sy, wa, us", "T", 100, str(tmp_path) + "/", "", footnote=FOOT)
    assert any("test footnote" in t for t in c["fig_texts"])
    assert c["savefig_kwargs"].get("bbox_inches") == "tight"


def test_plotly_footnote_helper():
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.update_layout(height=650)
    new_height = yaspe._add_plotly_footnote(fig, FOOT, 650)
    assert new_height > 650
    assert fig.layout.height == new_height
    assert any("test footnote" in a.text for a in fig.layout.annotations)
    assert fig.layout.margin.b > 80


def test_plotly_footnote_helper_empty_is_noop():
    import plotly.graph_objects as go
    fig = go.Figure()
    assert yaspe._add_plotly_footnote(fig, "", 650) == 650
    assert len(fig.layout.annotations) == 0


def test_linked_chart_html_footnote(tmp_path):
    captured = {}

    def fake_write_html(self, *a, **k):
        captured["fig"] = self

    with patch("plotly.graph_objects.Figure.write_html", fake_write_html):
        yaspe.linked_chart(_df(), "Total CPU", "T", 100, str(tmp_path) + "/", "", footnote=FOOT)
    fig = captured["fig"]
    assert any("test footnote" in a.text for a in fig.layout.annotations)


import sqlite3
from unittest.mock import MagicMock


def _db(overview_rows, with_vmstat=True):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id INTEGER PRIMARY KEY AUTOINCREMENT, field TEXT NOT NULL, value TEXT)")
    conn.executemany("INSERT INTO overview (field, value) VALUES (?, ?)", overview_rows)
    if with_vmstat:
        times = pd.date_range("2024-01-15 09:00", periods=10, freq="1min")
        df = pd.DataFrame({
            "RunDate": times.strftime("%m/%d/%Y"), "RunTime": times.strftime("%H:%M:%S"),
            "r": np.ones(10), "us": np.full(10, 20.0), "sy": np.full(10, 5.0),
            "wa": np.ones(10), "id": np.full(10, 74.0),
        })
        df.to_sql("vmstat", conn, index=False)
    conn.commit()
    return conn


BARE_ROWS = [
    ("customer", "Acme"), ("operating system", "Linux"), ("processor model", "Intel(R) Xeon(R) Gold 6448H"),
    ("number cpus", "256"), ("lscpu cpus", "256"), ("lscpu sockets", "4"),
    ("lscpu cores per socket", "32"), ("lscpu threads per core", "2"),
    ("cpu host type", "bare metal"), ("cpu topology source", "lscpu"),
]


def test_get_overview_dict_first_occurrence_wins():
    conn = _db([("number cpus", "16"), ("number cpus", "32")], with_vmstat=False)
    assert yaspe.get_overview_dict(conn)["number cpus"] == "16"


def test_get_overview_dict_missing_table():
    conn = sqlite3.connect(":memory:")
    assert yaspe.get_overview_dict(conn) == {}


def _run_vmstat(conn, tmp_path):
    with patch.object(yaspe, "simple_chart") as sc, \
         patch.object(yaspe, "simple_chart_stacked") as st, \
         patch.object(yaspe, "linked_chart") as lc:
        yaspe.chart_vmstat(conn, str(tmp_path) + "/", "", True, False)
    return sc, st, lc


def test_chart_vmstat_bare_metal_labels_and_footnotes(tmp_path):
    sc, st, _ = _run_vmstat(_db(BARE_ROWS), tmp_path)
    stacked_title = st.call_args.args[2]
    assert "256 threads (4 sockets x 32 cores x 2 HT) (Intel(R) Xeon(R) Gold 6448H)" in stacked_title
    assert "Physical server" in st.call_args.kwargs["footnote"]

    calls = {c.args[1]: c for c in sc.call_args_list}
    for col in ("Total CPU", "r", "us", "sy"):
        assert "256 threads (4 sockets x 32 cores x 2 HT)" in calls[col].args[2]
    for col in ("Total CPU", "us", "sy"):
        assert "Physical server" in calls[col].kwargs["footnote"]
    assert calls["r"].kwargs["footnote"].startswith("r counts tasks running or waiting for a CPU.")
    assert "Physical server" not in calls["wa"].kwargs["footnote"]
    assert calls["wa"].kwargs["footnote"].startswith("CPU % spent idle while waiting for disk I/O.\n")
    assert "threads" not in calls["wa"].args[2]


def test_chart_vmstat_unknown_topology_label(tmp_path):
    rows = [("customer", "Acme"), ("operating system", "Linux"),
            ("processor model", "Some CPU"), ("number cpus", "8")]
    sc, st, _ = _run_vmstat(_db(rows), tmp_path)
    assert "8 logical CPUs (Some CPU)" in st.call_args.args[2]
    assert st.call_args.kwargs["footnote"].startswith("CPU details are not in this file. IRIS reports 8 CPUs")


def test_chart_vmstat_html_passes_footnote(tmp_path):
    with patch.object(yaspe, "linked_chart") as lc:
        yaspe.chart_vmstat(_db(BARE_ROWS), str(tmp_path) + "/", "", False, False)
    calls = {c.args[1]: c for c in lc.call_args_list}
    assert "Physical server" in calls["Total CPU"].kwargs["footnote"]
