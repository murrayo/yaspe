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

import sp_check


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


def _extract_to_sqlite(html_path: str) -> str:
    """Extract vmstat and mgstat from html_path into a per-file SQLite.

    Returns the path to the SQLite file.
    Re-uses yaspe's sp_check, create_overview, create_connection, and
    create_sections so all parsing logic stays in one place.
    """
    from yaspe import create_connection, create_overview, create_sections

    html_path = os.path.abspath(html_path)
    directory = os.path.dirname(html_path)
    html_basename = os.path.splitext(os.path.basename(html_path))[0]
    sql_path = os.path.join(directory, f"{html_basename}_SystemPerformance.sqlite")

    conn = create_connection(sql_path)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT count(name) FROM sqlite_master WHERE type='table' AND name='overview'"
    )
    overview_exists = cursor.fetchone()[0] == 1

    if not overview_exists:
        sp_dict = sp_check.system_check(html_path)
        create_overview(conn, sp_dict)
        create_sections(
            conn,
            html_path,
            False,
            False,
            html_basename,
            False,
            os.path.join(directory, f"{html_basename}_"),
            [],
            False,
        )

    conn.close()
    return sql_path


def _load_dataframes(sql_path: str):
    """Return (mgstat_df, vmstat_df) from the SQLite at sql_path.
    Returns empty DataFrames if the table doesn't exist."""
    conn = sqlite3.connect(sql_path)
    mgstat_df = pd.DataFrame()
    vmstat_df = pd.DataFrame()
    try:
        mgstat_df = pd.read_sql("SELECT * FROM mgstat", conn)
    except Exception:
        pass
    try:
        vmstat_df = pd.read_sql("SELECT * FROM vmstat", conn)
    except Exception:
        pass
    conn.close()
    return mgstat_df, vmstat_df


def run(directory: str) -> None:
    """Entry point called by yaspe.py when --compare-dir is given."""
    pass  # implemented in later tasks
