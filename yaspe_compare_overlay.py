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
        if "id" in vmstat_df.columns:
            vmstat_df["Total CPU"] = 100 - vmstat_df["id"]
    except Exception:
        pass
    conn.close()
    return mgstat_df, vmstat_df


def _build_overlay_charts(datasets: list, metric_type: str, output_dir: str) -> None:
    """Produce one Plotly HTML overlay chart per common numeric column.

    datasets: list of {"label": str, "df": pd.DataFrame, "datetime_col": str}
    metric_type: "mgstat" or "vmstat" (used only in chart titles)
    output_dir: directory where HTML files are written
    """
    os.makedirs(output_dir, exist_ok=True)

    if not datasets:
        return

    def _numeric_cols(ds):
        dt_col = ds["datetime_col"]
        return set(
            c for c in ds["df"].select_dtypes(include="number").columns
            if c != dt_col
        )

    common_cols = _numeric_cols(datasets[0])
    for ds in datasets[1:]:
        common_cols &= _numeric_cols(ds)

    if not common_cols:
        print(f"  No common numeric columns found for {metric_type}, skipping.")
        return

    for col in sorted(common_cols):
        _write_overlay_html(datasets, col, metric_type, output_dir)


def _write_overlay_html(datasets: list, column_name: str, metric_type: str, output_dir: str) -> None:
    """Write a single overlay HTML chart for column_name across all datasets."""
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
    )

    for i, ds in enumerate(datasets):
        df = ds["df"].copy()
        dt_col = ds["datetime_col"]
        label = ds["label"]
        color = _COLORS[i % len(_COLORS)]

        if column_name not in df.columns:
            continue

        df[dt_col] = pd.to_datetime(df[dt_col])
        df = df.sort_values(dt_col)

        series = pd.to_numeric(df[column_name], errors="coerce")
        win = max(2, min(len(series), 60))
        smoothed = series.rolling(window=win, center=True, min_periods=1).mean()

        x_ref = [_normalise_to_timeofday(ts) for ts in df[dt_col]]
        actual_times = [ts.strftime("%a %d-%b-%Y %H:%M:%S") for ts in df[dt_col]]

        fig.add_trace(go.Scatter(
            x=x_ref, y=smoothed.values,
            mode="lines", name=label,
            line=dict(width=1.5, color=color),
            customdata=actual_times,
            hovertemplate="%{customdata}<br>" + column_name + ": %{y:,.3g}<extra></extra>",
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=x_ref, y=smoothed.values,
            mode="lines", name=label,
            line=dict(width=0.8, color=color),
            showlegend=False,
            hoverinfo="skip",
        ), row=2, col=1)

    fig.update_layout(
        title=dict(
            text=f"{metric_type} — {column_name} — Instance Overlay",
            font=dict(size=16),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(title="Time of day", tickfont=dict(size=13), tickformat="%H:%M"),
        xaxis2=dict(
            title="Drag box here to zoom ↑   (double-click top chart to reset)",
            tickfont=dict(size=11),
            tickformat="%H:%M",
        ),
        yaxis=dict(title=column_name, tickfont=dict(size=13), rangemode="tozero"),
        yaxis2=dict(rangemode="tozero", showticklabels=False),
        legend=dict(
            bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1,
            font=dict(size=12), orientation="v",
            title=dict(text="Click to show/hide", font=dict(size=11, color="grey")),
        ),
        height=650,
        hovermode="x",
        template="plotly_white",
    )

    safe_col = column_name.replace("/", "_")
    out_path = os.path.join(output_dir, f"{safe_col}_overlay.html")
    fig.write_html(
        out_path,
        include_plotlyjs="cdn",
        post_script=_OVERVIEW_ZOOM_JS,
        full_html=True,
    )
    print(f"  Written: {out_path}")


def _detect_datetime_column(df: pd.DataFrame) -> str:
    """Return the name of the datetime column in df, or empty string if not found.
    Checks common names used by yaspe: 'DateTime', 'RunDate', 'Date/Time'."""
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


def run(directory: str) -> None:
    """Entry point called by yaspe.py when --compare-dir is given.

    1. Find all *.html files in directory.
    2. For each: extract to per-file SQLite (skip if already done).
    3. Load vmstat and mgstat DataFrames.
    4. Build overlay charts into compare_overlay/mgstat/ and compare_overlay/vmstat/.
    """
    directory = os.path.abspath(directory)
    html_files = sorted(Path(directory).glob("*.html"))

    if not html_files:
        print(f"No HTML files found in {directory}")
        return

    print(f"Found {len(html_files)} HTML file(s) in {directory}")

    mgstat_datasets = []
    vmstat_datasets = []

    for html_path in html_files:
        html_path_str = str(html_path)
        print(f"Processing: {html_path.name}")

        sql_path = _extract_to_sqlite(html_path_str)

        mgstat_df, vmstat_df = _load_dataframes(sql_path)

        instance_name = _extract_instance_name(html_path_str)

        if not mgstat_df.empty:
            dt_col = _detect_datetime_column(mgstat_df)
            if dt_col:
                first_ts = pd.to_datetime(mgstat_df[dt_col]).min()
                date_str = first_ts.strftime("%d-%b-%Y")
                label = f"{instance_name} {date_str}"
                mgstat_datasets.append({"label": label, "df": mgstat_df, "datetime_col": dt_col})

        if not vmstat_df.empty:
            dt_col = _detect_datetime_column(vmstat_df)
            if dt_col:
                first_ts = pd.to_datetime(vmstat_df[dt_col]).min()
                date_str = first_ts.strftime("%d-%b-%Y")
                label = f"{instance_name} {date_str}"
                vmstat_datasets.append({"label": label, "df": vmstat_df, "datetime_col": dt_col})

    overlay_base = os.path.join(directory, "compare_overlay")

    if mgstat_datasets:
        print(f"\nBuilding mgstat overlay charts ({len(mgstat_datasets)} traces)...")
        _build_overlay_charts(mgstat_datasets, "mgstat", os.path.join(overlay_base, "mgstat"))

    if vmstat_datasets:
        print(f"\nBuilding vmstat overlay charts ({len(vmstat_datasets)} traces)...")
        _build_overlay_charts(vmstat_datasets, "vmstat", os.path.join(overlay_base, "vmstat"))

    print(f"\nDone. Charts written to: {overlay_base}")
