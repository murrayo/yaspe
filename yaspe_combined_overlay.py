# yaspe_combined_overlay.py
"""
Combined vmstat+mgstat overlay chart: one Plotly HTML with CPU stacked areas
and mgstat IO/routing lines. IO metrics share one right y-axis; each routing
metric gets its own independent right y-axis.
"""

import os
import sqlite3

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


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


def _load_dataframes(sql_path: str):
    """Return (mgstat_df, vmstat_df) from the SQLite at sql_path.
    Returns empty DataFrames if the table doesn't exist.
    Adds 'Total CPU' column to vmstat_df as 100 - id."""
    conn = sqlite3.connect(sql_path)
    mgstat_df = pd.DataFrame()
    vmstat_df = pd.DataFrame()
    try:
        mgstat_df = pd.read_sql("SELECT * FROM mgstat", conn)
    except Exception:
        pass
    try:
        vmstat_df = pd.read_sql("SELECT * FROM vmstat", conn)
        if "id" in vmstat_df.columns:
            vmstat_df["Total CPU"] = 100 - vmstat_df["id"]
    except Exception:
        pass
    conn.close()
    return mgstat_df, vmstat_df


def _detect_datetime_column(df: pd.DataFrame) -> str:
    """Return the name of the datetime column in df, or empty string if not found."""
    for candidate in ("datetime", "DateTime", "Date/Time", "RunDate"):
        if candidate in df.columns:
            return candidate
    for col in df.select_dtypes(include="object").columns:
        try:
            pd.to_datetime(df[col].iloc[0])
            return col
        except Exception:
            continue
    return ""


def run(sql_path: str, output_dir: str) -> None:
    """Public entry point. Called by yaspe.py when --combined is given."""
    raise NotImplementedError("run() not yet implemented")
