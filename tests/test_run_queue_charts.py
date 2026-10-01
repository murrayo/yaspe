import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe


def _df(periods=10):
    times = pd.date_range("2024-01-15 09:00", periods=periods, freq="1min")
    return pd.DataFrame({"datetime_parsed": times, "datetime": times, "metric": np.arange(periods, dtype=float)})


def _capture_png(fn, *args, **kwargs):
    captured = {}

    def fake_savefig(*a, **k):
        import matplotlib.pyplot as plt
        ax = plt.gcf().axes[0]
        legend = ax.get_legend()
        captured["legend"] = [t.get_text() for t in legend.get_texts()] if legend else []
        captured["ylabel"] = ax.get_ylabel()
        captured["hlines"] = [ln.get_ydata()[0] for ln in ax.get_lines() if len(ln.get_ydata()) == 2
                              and ln.get_ydata()[0] == ln.get_ydata()[1]]

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), patch("matplotlib.pyplot.close"):
        fn(*args, **kwargs)
    return captured


def test_threshold_list_normalises():
    assert yaspe._threshold_list(None) == []
    assert yaspe._threshold_list((5, "A")) == [(5, "A")]
    assert yaspe._threshold_list([(5, "A"), (None, "B")]) == [(5, "A"), (None, "B")]


def test_simple_chart_single_threshold_unchanged(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r", "T", 10, str(tmp_path) + "/", "", threshold=(5, "Five"))
    assert "Five" in cap["legend"]
    assert 5 in cap["hlines"]


def test_simple_chart_threshold_list_with_legend_only(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r", "T", 10, str(tmp_path) + "/", "",
                       threshold=[(5, "Line one"), (8, "Line two"), (None, "Off scale line")])
    assert {"Line one", "Line two", "Off scale line"} <= set(cap["legend"])
    assert 5 in cap["hlines"] and 8 in cap["hlines"]


def test_simple_chart_y_label(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r per core", "T", 2, str(tmp_path) + "/", "",
                       y_label="r ÷ 128 physical cores")
    assert cap["ylabel"] == "r ÷ 128 physical cores"


def test_simple_chart_default_y_label(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r", "T", 10, str(tmp_path) + "/", "")
    assert cap["ylabel"] == "r"


def test_apply_ref_lines_threshold_list():
    fig = go.Figure()
    yaspe._apply_ref_lines(fig, _df(), False, [(5, "A"), (8, "B"), (None, "C off scale")], row=None)
    assert [s.y0 for s in fig.layout.shapes] == [5, 8]
    assert [t.name for t in fig.data] == ["C off scale"]


def test_apply_ref_lines_single_tuple_unchanged():
    fig = go.Figure()
    yaspe._apply_ref_lines(fig, _df(), False, (80, "80% CPU threshold"), row=None)
    assert [s.y0 for s in fig.layout.shapes] == [80]
    assert fig.layout.shapes[0].line.dash == "dashdot"


def test_linked_chart_html_y_label_and_lines(tmp_path):
    captured = {}

    def fake_write_html(self, *a, **k):
        captured["fig"] = self

    with patch("plotly.graph_objects.Figure.write_html", fake_write_html):
        yaspe.linked_chart(_df(), "r per core", "T", 2, str(tmp_path) + "/", "",
                           threshold=[(1.0, "Saturated"), (None, "Threads off scale")],
                           y_label="r ÷ 128 physical cores")
    fig = captured["fig"]
    assert fig.layout.yaxis.title.text == "r ÷ 128 physical cores"
    assert [s.y0 for s in fig.layout.shapes] == [1.0]
    assert "Threads off scale" in [t.name for t in fig.data]


import sqlite3


def _db(overview_rows, r_values):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id INTEGER PRIMARY KEY AUTOINCREMENT, field TEXT NOT NULL, value TEXT)")
    conn.executemany("INSERT INTO overview (field, value) VALUES (?, ?)", overview_rows)
    n = len(r_values)
    times = pd.date_range("2024-01-15 09:00", periods=n, freq="1min")
    pd.DataFrame({
        "RunDate": times.strftime("%m/%d/%Y"), "RunTime": times.strftime("%H:%M:%S"),
        "r": r_values, "us": np.full(n, 80.0), "sy": np.full(n, 15.0),
        "wa": np.ones(n), "id": np.full(n, 5.0),
    }).to_sql("vmstat", conn, index=False)
    conn.commit()
    return conn


BARE_ROWS = [
    ("customer", "Acme"), ("operating system", "Linux"), ("processor model", "Intel(R) Xeon(R) Gold 6448H"),
    ("number cpus", "256"), ("lscpu cpus", "256"), ("lscpu sockets", "4"),
    ("lscpu cores per socket", "32"), ("lscpu threads per core", "2"),
    ("cpu host type", "bare metal"), ("cpu topology source", "lscpu"),
]


def _run_vmstat(conn, tmp_path, png=True):
    with patch.object(yaspe, "simple_chart") as sc, \
         patch.object(yaspe, "simple_chart_stacked"), \
         patch.object(yaspe, "linked_chart") as lc:
        yaspe.chart_vmstat(conn, str(tmp_path) + "/", "", png, False)
    return {c.args[1]: c for c in sc.call_args_list}, {c.args[1]: c for c in lc.call_args_list}


def test_chart_vmstat_r_gets_lines_and_verdict(tmp_path):
    png, _ = _run_vmstat(_db(BARE_ROWS, [10.0] * 90 + [200.0] * 10), tmp_path)
    r_call = png["r"]
    thresholds = r_call.kwargs["threshold"]
    assert [t[0] for t in thresholds] == [128, None]
    assert thresholds[0][1].startswith("Physical cores 128 (above = cores running two tasks via HT): 10.0% of samples above")
    assert r_call.args[3] == 200 * 1.05
    assert "bare metal" in r_call.kwargs["footnote"]
    assert "the CPU was 95% busy — the server is short of CPU." in r_call.kwargs["footnote"]


def test_chart_vmstat_r_per_core_chart(tmp_path):
    png, _ = _run_vmstat(_db(BARE_ROWS, [10.0] * 90 + [200.0] * 10), tmp_path)
    pc = png["r per core"]
    assert pc.kwargs["y_label"] == "r ÷ 128 physical cores"
    assert pc.kwargs["threshold"][0] == (1.0, "1.0 = r equals 128 physical cores (saturated)")
    assert pc.kwargs["min_max"] is False
    assert "256 threads (4 sockets x 32 cores x 2 HT)" in pc.args[2]
    assert "Run queue:" in pc.kwargs["footnote"]
    assert pc.args[0]["metric"].max() == 200.0 / 128


def test_chart_vmstat_html_r_per_core(tmp_path):
    _, html = _run_vmstat(_db(BARE_ROWS, [10.0] * 100), tmp_path, png=False)
    assert html["r per core"].kwargs["y_label"] == "r ÷ 128 physical cores"
    assert html["r"].kwargs["threshold"][0][0] is None


def test_chart_vmstat_no_cpu_count_no_per_core(tmp_path):
    rows = [("customer", "Acme"), ("operating system", "Linux"), ("processor model", "Some CPU")]
    png, _ = _run_vmstat(_db(rows, [3.0] * 10), tmp_path)
    assert "r per core" not in png
    assert png["r"].kwargs.get("threshold") is None
    assert png["r"].args[3] == 3.0


def test_chart_vmstat_other_columns_untouched(tmp_path):
    png, _ = _run_vmstat(_db(BARE_ROWS, [10.0] * 100), tmp_path)
    assert png["Total CPU"].kwargs["threshold"] == (80, "80% CPU threshold")
    assert "Run queue" not in png["Total CPU"].kwargs["footnote"]


import matplotlib.pyplot as plt


def test_draw_extra_horizontal_tuple_and_list():
    import chart_templates
    fig, ax = plt.subplots()
    chart_templates._draw_extra_horizontal(ax, (5, "Five"), 10)
    chart_templates._draw_extra_horizontal(ax, [(128, "Cores"), (256, "Threads")], 10)
    chart_templates._draw_extra_horizontal(ax, (0, ""), 10)
    labels = [ln.get_label() for ln in ax.get_lines()]
    assert labels == ["Five", "Cores", "Threads"]
    plt.close(fig)


def test_chart_output_r_uses_topology_lines():
    import chart_output
    captured = []
    times = pd.date_range("2024-01-15 09:00", periods=5, freq="1min")
    df = pd.DataFrame({"r": [1.0] * 5, "Total CPU": [10.0] * 5}, index=times)
    topology = {"cpu host type": "bare metal", "lscpu sockets": 4, "lscpu cores per socket": 32,
                "lscpu threads per core": 2, "number cpus": 256}
    with patch("chart_templates.chart_multi_line", side_effect=lambda *a, **k: captured.append(k)):
        chart_output.chart_vmstat(df, {"vmstat columns": ["r"]}, number_cpus=256, topology=topology)
    r_call = [k for k in captured if k["left_y_axis_label"] == "r"][0]
    assert r_call["extra_horizontal"] == [(128, "Physical cores 128 (above = cores running two tasks via HT)"),
                                          (256, "Threads 256 (above = tasks waiting for any CPU)")]


def test_system_review_passes_topology():
    import system_review
    overview = system_review.yaml_cpu_overview({"CPUs": 256, "CPU host type": "bare metal", "Sockets": 4,
                                                "Cores per socket": 32, "Threads per core": 2})
    from yaspe_utilities import run_queue_lines
    assert [ln.value for ln in run_queue_lines(overview)] == [128, 256]
