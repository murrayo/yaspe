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
