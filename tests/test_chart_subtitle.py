import os
import sys
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe


def _make_simple_df():
    """Minimal DataFrame accepted by simple_chart."""
    times = pd.date_range("2024-01-15 09:00", periods=10, freq="1min")
    return pd.DataFrame({"datetime_parsed": times, "datetime": times, "metric": np.arange(10, dtype=float)})


def _make_no_time_df():
    """Minimal DataFrame for simple_chart_no_time."""
    return pd.DataFrame({"id_key": range(10), "metric": np.arange(10, dtype=float)})


# ---------------------------------------------------------------------------
# simple_chart: subtitle text element
# ---------------------------------------------------------------------------

def test_simple_chart_adds_subtitle_text(tmp_path):
    """Subtitle kwarg causes a text annotation below the title in the chart axes."""
    df = _make_simple_df()
    captured = {}

    def fake_savefig(*args, **kwargs):
        import matplotlib.pyplot as plt
        captured["ax"] = plt.gcf().get_axes()[0]

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), \
         patch("matplotlib.pyplot.close"):
        yaspe.simple_chart(df, "Glorefs", "Test Title", 0, str(tmp_path) + "/", "", subtitle="My subtitle")

    ax = captured["ax"]
    texts = [t.get_text() for t in ax.texts]
    assert "My subtitle" in texts


def test_simple_chart_no_subtitle_adds_no_extra_text(tmp_path):
    """When subtitle is omitted, no extra text annotation is added below the title."""
    df = _make_simple_df()
    captured = {}

    def fake_savefig(*args, **kwargs):
        import matplotlib.pyplot as plt
        captured["ax"] = plt.gcf().get_axes()[0]

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), \
         patch("matplotlib.pyplot.close"):
        yaspe.simple_chart(df, "Glorefs", "Test Title", 0, str(tmp_path) + "/", "")

    ax = captured["ax"]
    assert len(ax.texts) == 0


def test_simple_chart_subtitle_fontsize_smaller_than_title(tmp_path):
    """Subtitle font size is 2 points smaller than the main title (16 → 14)."""
    df = _make_simple_df()
    captured = {}

    def fake_savefig(*args, **kwargs):
        import matplotlib.pyplot as plt
        captured["ax"] = plt.gcf().get_axes()[0]

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), \
         patch("matplotlib.pyplot.close"):
        yaspe.simple_chart(df, "Glorefs", "Test Title", 0, str(tmp_path) + "/", "", subtitle="Sub")

    ax = captured["ax"]
    subtitle_text = next(t for t in ax.texts if t.get_text() == "Sub")
    assert subtitle_text.get_fontsize() == pytest.approx(14)


# ---------------------------------------------------------------------------
# linked_chart: Plotly subtitle
# ---------------------------------------------------------------------------

def test_linked_chart_subtitle_in_plotly_layout(tmp_path):
    """linked_chart passes subtitle into the Plotly figure title layout."""
    df = _make_simple_df()
    written_layouts = []

    def fake_write_html(self, *args, **kwargs):
        pass

    import plotly.graph_objects as go
    orig_update = go.Figure.update_layout

    def capturing_update_layout(self, *args, **kwargs):
        written_layouts.append(kwargs)
        return orig_update(self, *args, **kwargs)

    with patch("plotly.graph_objects.Figure.update_layout", capturing_update_layout), \
         patch("plotly.graph_objects.Figure.write_html", fake_write_html):
        yaspe.linked_chart(df, "Glorefs", "Test Title", 0, str(tmp_path) + "/", "",
                           write_html=True, subtitle="My subtitle")

    title_kwargs = next((d["title"] for d in written_layouts if "title" in d), None)
    assert title_kwargs is not None
    assert title_kwargs.get("subtitle", {}).get("text") == "My subtitle"


def test_linked_chart_no_subtitle_omits_subtitle_key(tmp_path):
    """When no subtitle, linked_chart title layout has no subtitle key."""
    df = _make_simple_df()
    written_layouts = []

    import plotly.graph_objects as go
    orig_update = go.Figure.update_layout

    def capturing_update_layout(self, *args, **kwargs):
        written_layouts.append(kwargs)
        return orig_update(self, *args, **kwargs)

    def fake_write_html(self, *args, **kwargs):
        pass

    with patch("plotly.graph_objects.Figure.update_layout", capturing_update_layout), \
         patch("plotly.graph_objects.Figure.write_html", fake_write_html):
        yaspe.linked_chart(df, "Glorefs", "Test Title", 0, str(tmp_path) + "/", "",
                           write_html=True)

    title_kwargs = next((d["title"] for d in written_layouts if "title" in d), None)
    assert title_kwargs is not None
    assert "subtitle" not in title_kwargs


# ---------------------------------------------------------------------------
# mainline: subtitle parameter exists
# ---------------------------------------------------------------------------

def test_mainline_accepts_subtitle_parameter():
    """mainline() signature includes subtitle kwarg."""
    import inspect
    sig = inspect.signature(yaspe.mainline)
    assert "subtitle" in sig.parameters


# ---------------------------------------------------------------------------
# chart_templates: chart_multi_line user_subtitle
# ---------------------------------------------------------------------------

def test_chart_multi_line_user_subtitle(tmp_path):
    """chart_multi_line renders user_subtitle text below the axes title."""
    import chart_templates

    times = pd.date_range("2024-01-15 09:00", periods=5, freq="1min")
    df = pd.DataFrame({"datetime": times, "val": [1.0, 2.0, 3.0, 2.0, 1.0]})
    df = df.set_index("datetime")

    site = {
        "Site Name": "TestSite",
        "Chart": {
            "chart style": "seaborn-v0_8-whitegrid",
            "dpi": 72,
            "width": 8,
            "height": 4,
            "format": "png",
            "line style": "-",
            "marker": "",
        },
    }

    captured = {}

    def fake_savefig(path, **kwargs):
        import matplotlib.pyplot as plt
        captured["ax"] = plt.gcf().get_axes()[0]

    with patch("matplotlib.figure.Figure.savefig", side_effect=fake_savefig), \
         patch("matplotlib.pyplot.close"):
        chart_templates.chart_multi_line(
            df, "val metric", ["val"], site,
            base_file_path=str(tmp_path),
            user_subtitle="Chart note",
        )

    ax = captured.get("ax")
    assert ax is not None
    texts = [t.get_text() for t in ax.texts]
    assert "Chart note" in texts
