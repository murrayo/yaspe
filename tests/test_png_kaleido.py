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
