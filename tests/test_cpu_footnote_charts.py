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
