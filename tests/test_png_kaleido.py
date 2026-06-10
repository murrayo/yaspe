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


def test_linked_chart_no_time_writes_png_when_requested():
    import yaspe
    df = pd.DataFrame({"id_key": list(range(20)), "metric": [float(i) for i in range(20)]})
    with tempfile.TemporaryDirectory() as d:
        filepath = d + "/"
        yaspe.linked_chart_no_time(df, "metric", "Test Title", 20, filepath, "prefix_",
                                   write_png=True, png_path=filepath)
        png_file = os.path.join(d, "prefix_metric.png")
        assert os.path.exists(png_file), f"PNG missing: {png_file}"
        assert os.path.getsize(png_file) > 5000


def test_plotly_stacked_png_produces_file():
    import yaspe
    base = datetime.datetime(2024, 1, 1, 10, 0, 0)
    rows = []
    for i in range(20):
        dt = base + datetime.timedelta(minutes=i)
        rows.append({"datetime": dt.strftime("%m/%d/%Y %H:%M:%S"),
                     "datetime_parsed": dt,
                     "sy": float(i), "wa": 2.0, "us": float(20 - i)})
    df = pd.DataFrame(rows)
    with tempfile.TemporaryDirectory() as d:
        filepath = d + "/"
        yaspe._plotly_stacked_png(df, "CPU Title", 100, filepath, "prefix_")
        out = os.path.join(d, "prefix_z_Stacked CPU.png")
        assert os.path.exists(out), f"PNG missing: {out}"
        assert os.path.getsize(out) > 5000


def test_plotly_histogram_iostat_png_produces_files():
    import yaspe
    rng = list(range(1, 21))
    df = pd.DataFrame({
        "r_await": [float(v) for v in rng],
        "w_await": [float(v * 0.5) for v in rng],
        "r/s":     [float(v) for v in rng],
        "w/s":     [float(v) for v in rng],
    })
    columns_to_histogram = {"r_await": "r/s", "w_await": "w/s"}
    with tempfile.TemporaryDirectory() as d:
        filepath = d + "/"
        yaspe._plotly_histogram_iostat_png(df, columns_to_histogram, "sdb", "Latency", filepath, "prefix_")
        read_out = os.path.join(d, "prefix__sdb_z_Read Latency Histogram.png")
        write_out = os.path.join(d, "prefix__sdb_z_Write Latency Histogram.png")
        assert os.path.exists(read_out), f"Read PNG missing: {read_out}"
        assert os.path.exists(write_out), f"Write PNG missing: {write_out}"
