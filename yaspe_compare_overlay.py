"""
Compare overlay charts: process all HTML files in a directory and produce
one Plotly HTML overlay chart per vmstat/mgstat column.
"""

import os
import re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]

_OVERVIEW_ZOOM_JS = """
var gd = document.querySelector('.plotly-graph-div');
var syncing = false;
gd.on('plotly_relayout', function(eventdata) {
    if (syncing) return;
    var r0 = eventdata['xaxis2.range[0]'];
    var r1 = eventdata['xaxis2.range[1]'];
    if (r0 !== undefined && r1 !== undefined) {
        syncing = true;
        Plotly.relayout(gd, {
            'xaxis.range[0]': r0,
            'xaxis.range[1]': r1,
            'xaxis.autorange': false,
            'xaxis2.autorange': true
        }).then(function() { syncing = false; });
    } else if (eventdata['xaxis2.autorange'] === true) {
        syncing = true;
        Plotly.relayout(gd, {'xaxis.autorange': true})
            .then(function() { syncing = false; });
    }
});
"""


def _extract_instance_name(html_path: str) -> str:
    """Return the IRIS instance name from the HTML Configuration section.
    Falls back to the filename stem if not found."""
    with open(html_path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    m = re.search(r'up\s*>\s*(\S+)', text)
    if m:
        return m.group(1)
    return Path(html_path).stem


def _normalise_to_timeofday(ts: pd.Timestamp) -> pd.Timestamp:
    """Map any timestamp to 2000-01-01 HH:MM:SS so all traces share one x-axis."""
    return pd.Timestamp("2000-01-01") + (ts - ts.normalize())


def run(directory: str) -> None:
    """Entry point called by yaspe.py when --compare-dir is given."""
    pass  # implemented in later tasks
