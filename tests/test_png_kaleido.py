import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plotly.graph_objects as go


def test_kaleido_write_image_produces_png():
    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[4, 5, 6]))
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "test.png")
        fig.write_image(out, scale=2, width=1400, height=650)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 1000


import pandas as pd
import datetime


def _make_sample_df():
    base = datetime.datetime(2024, 1, 1, 10, 0, 0)
    rows = [{"datetime": (base + datetime.timedelta(minutes=i)).strftime("%m/%d/%Y %H:%M:%S"),
             "metric": float(i * 10)} for i in range(20)]
    df = pd.DataFrame(rows)
    df["datetime_parsed"] = pd.to_datetime(df["datetime"], format="%m/%d/%Y %H:%M:%S")
    return df


def test_linked_chart_writes_png_when_requested():
    import yaspe
    df = _make_sample_df()
    with tempfile.TemporaryDirectory() as d:
        filepath = d + "/"
        yaspe.linked_chart(df, "metric", "Test Title", 200, filepath, "prefix_",
                           write_png=True, png_path=filepath)
        html_file = os.path.join(d, "prefix_metric.html")
        png_file = os.path.join(d, "prefix_metric.png")
        assert os.path.exists(html_file), f"HTML missing: {html_file}"
        assert os.path.exists(png_file), f"PNG missing: {png_file}"
        assert os.path.getsize(png_file) > 5000


def test_linked_chart_no_png_by_default():
    import yaspe
    df = _make_sample_df()
    with tempfile.TemporaryDirectory() as d:
        filepath = d + "/"
        yaspe.linked_chart(df, "metric", "Test Title", 200, filepath, "prefix_")
        png_file = os.path.join(d, "prefix_metric.png")
        assert not os.path.exists(png_file), "PNG should not be written by default"
