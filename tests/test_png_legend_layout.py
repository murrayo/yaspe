import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe

LONG = "Threads 112 (above = tasks waiting for any CPU): 0.3% of samples above, peak 137 at 18-Feb 12:22"


def _df(periods=600):
    times = pd.date_range("2024-01-15 09:00", periods=periods, freq="1min")
    return pd.DataFrame({"datetime_parsed": times, "datetime": times,
                         "metric": np.linspace(1, 130, periods)})


def _render(tmp_path, threshold):
    captured = {}

    def fake_savefig(*a, **k):
        import matplotlib.pyplot as plt
        if captured:
            return
        fig = plt.gcf()
        ax = fig.axes[0]
        captured["axes_width"] = ax.get_position().width
        captured["labels"] = [t.get_text() for t in ax.get_legend().get_texts()]
        renderer = fig.canvas.get_renderer()
        saved = fig.get_tightbbox(renderer)
        legend = ax.get_legend().get_window_extent(renderer).transformed(fig.dpi_scale_trans.inverted())
        captured["legend_inside"] = saved.x1 >= legend.x1 - 0.01

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), patch("matplotlib.pyplot.close"):
        yaspe.simple_chart(_df(), "r", "T", 0, str(tmp_path) + "/", "", min_max=True, threshold=threshold)
    import matplotlib.pyplot as plt
    plt.close("all")
    return captured


def test_long_legend_label_is_wrapped(tmp_path):
    c = _render(tmp_path, [(112, LONG)])
    wrapped = [t for t in c["labels"] if t.startswith("Threads 112")][0]
    assert "\n" in wrapped
    assert max(len(line) for line in wrapped.split("\n")) <= 50


def test_long_legend_does_not_shrink_plot(tmp_path):
    short = _render(tmp_path, [(112, "Threads 112")])
    long = _render(tmp_path, [(112, LONG), (56, LONG.replace("Threads 112", "Physical cores 56"))])
    assert long["axes_width"] >= short["axes_width"] - 0.01
    assert long["axes_width"] > 0.8


def test_legend_is_inside_saved_image(tmp_path):
    c = _render(tmp_path, [(112, LONG)])
    assert c["legend_inside"]
