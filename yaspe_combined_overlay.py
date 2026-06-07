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


_OVERVIEW_ZOOM_JS = """
(function() {
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
})();
"""

_AXIS_TOGGLE_JS = """
(function() {
    var gd = document.querySelector('.plotly-graph-div');
    var routingAxes = ['y3', 'y4', 'y5', 'y6', 'y7'];

    function updateOverlayAxes() {
        var axisHasVisible = {};
        gd.data.forEach(function(trace) {
            var yax = trace.yaxis || 'y';
            var visible = trace.visible !== 'legendonly' && trace.visible !== false;
            axisHasVisible[yax] = (axisHasVisible[yax] || false) || visible;
        });

        var update = {};

        // IO axis: show/hide as a unit
        update['yaxis2.visible'] = !!axisHasVisible['y2'];

        // Routing axes: hide invisible ones, repack shifts on the rest
        var shiftIdx = 0;
        routingAxes.forEach(function(yid) {
            var layoutKey = 'yaxis' + yid.slice(1);
            if (axisHasVisible[yid]) {
                update[layoutKey + '.visible'] = true;
                update[layoutKey + '.shift'] = (shiftIdx + 1) * 80;
                shiftIdx++;
            } else {
                update[layoutKey + '.visible'] = false;
            }
        });

        // Shrink/grow right margin to match remaining visible axes
        update['margin.r'] = Math.max(60, shiftIdx * 80 + 160);
        Plotly.relayout(gd, update);
    }

    // plotly_restyle fires after Plotly has committed the new visibility state,
    // so gd.data reflects the correct values when updateOverlayAxes reads it.
    gd.on('plotly_restyle', function() { updateOverlayAxes(); });
})();
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


def _smooth(series: pd.Series, dt_series: pd.Series, smooth_minutes: float) -> pd.Series:
    """Return a centred rolling mean over smooth_minutes of data.
    Window size is inferred from the median sample interval."""
    if smooth_minutes <= 0 or len(series) < 2:
        return series
    diffs = dt_series.diff().dropna()
    median_secs = diffs.median().total_seconds()
    if median_secs <= 0:
        return series
    window = max(1, round(smooth_minutes * 60 / median_secs))
    return series.rolling(window=window, center=True, min_periods=1).mean()


# Column groups
_CPU_COLS = ["wa", "us", "sy"]
_IO_COLS  = ["WIJwri", "PhyRds", "PhyWrs", "Jrnwrts"]
# Each routing metric gets its own y-axis (y3..y7)
_ROU_COLS = ["Rourefs", "RouLaS", "RouCMs", "Gloupds", "Glorefs"]

_ROU_YAXIS = {col: f"y{i + 3}" for i, col in enumerate(_ROU_COLS)}

_DEFAULT_VISIBLE = {"Glorefs", "Total CPU"}

_CPU_COLORS = {"wa": "#d62728", "us": "#1f77b4", "sy": "#ff7f0e"}
_IO_COLORS  = {"WIJwri": "#2ca02c", "PhyRds": "#9467bd",
               "PhyWrs": "#8c564b", "Jrnwrts": "#e377c2"}
_ROU_COLORS = {"Rourefs": "#17becf", "RouLaS": "#bcbd22",
               "RouCMs": "#7f7f7f", "Gloupds": "#aec7e8",
               "Glorefs": "#ffbb78"}


def _build_combined_chart(
    mgstat_df: pd.DataFrame,
    vmstat_df: pd.DataFrame,
    mg_dt_col: str,
    vm_dt_col: str,
    output_path: str,
    smooth_minutes: float = 5,
) -> None:
    """Build and write the combined Plotly HTML chart.

    Axis layout (manual domains — no make_subplots, which would claim yaxis2):
      xaxis / yaxis        — main row left: CPU % stacked areas, domain y [0.30, 1.0]
      xaxis / yaxis2       — main row right: IO shared axis (overlaying y)
      xaxis / yaxis3..7    — main row right: one per routing metric (overlaying y, shifted)
      xaxis2 / yaxis8      — overview row: CPU stacked areas, domain y [0.0, 0.22]
    """
    fig = go.Figure()

    # Parse and sort datetimes
    vmstat_df = vmstat_df.copy()
    mgstat_df = mgstat_df.copy()
    vmstat_df[vm_dt_col] = pd.to_datetime(vmstat_df[vm_dt_col])
    vmstat_df = vmstat_df.sort_values(vm_dt_col)
    mgstat_df[mg_dt_col] = pd.to_datetime(mgstat_df[mg_dt_col])
    mgstat_df = mgstat_df.sort_values(mg_dt_col)

    # --- CPU stacked areas on yaxis (left, main row) ---
    for col in _CPU_COLS:
        if col not in vmstat_df.columns:
            print(f"  Skipping missing column: {col}")
            continue
        series = _smooth(pd.to_numeric(vmstat_df[col], errors="coerce"),
                         vmstat_df[vm_dt_col], smooth_minutes)
        color = _CPU_COLORS[col]
        fig.add_trace(go.Scatter(
            x=vmstat_df[vm_dt_col],
            y=series,
            mode="lines",
            name=col,
            xaxis="x", yaxis="y",
            stackgroup="cpu",
            visible=True if col in _DEFAULT_VISIBLE else "legendonly",
            line=dict(width=0.5, color=color),
            hovertemplate="%{x}<br>" + col + ": %{y:,.3g}<extra></extra>",
        ))
        # Overview panel: mirror CPU stacked area
        fig.add_trace(go.Scatter(
            x=vmstat_df[vm_dt_col],
            y=series,
            mode="lines",
            name=col,
            xaxis="x2", yaxis="y8",
            stackgroup="cpu_overview",
            showlegend=False,
            line=dict(width=0.8, color=color),
            hoverinfo="skip",
        ))

    # --- Total CPU line on yaxis (left, main row) ---
    if "Total CPU" in vmstat_df.columns:
        series = _smooth(pd.to_numeric(vmstat_df["Total CPU"], errors="coerce"),
                         vmstat_df[vm_dt_col], smooth_minutes)
        fig.add_trace(go.Scatter(
            x=vmstat_df[vm_dt_col],
            y=series,
            mode="lines",
            name="Total CPU",
            xaxis="x", yaxis="y",
            visible=True if "Total CPU" in _DEFAULT_VISIBLE else "legendonly",
            line=dict(width=2, color="#111111"),
            hovertemplate="%{x}<br>Total CPU: %{y:,.3g}<extra></extra>",
        ))
    else:
        print("  Skipping missing column: Total CPU")

    # --- IO metrics on yaxis2 (right, shared, main row) ---
    for col in _IO_COLS:
        if col not in mgstat_df.columns:
            print(f"  Skipping missing column: {col}")
            continue
        series = _smooth(pd.to_numeric(mgstat_df[col], errors="coerce"),
                         mgstat_df[mg_dt_col], smooth_minutes)
        fig.add_trace(go.Scatter(
            x=mgstat_df[mg_dt_col],
            y=series,
            mode="lines",
            name=col,
            xaxis="x", yaxis="y2",
            visible=True if col in _DEFAULT_VISIBLE else "legendonly",
            line=dict(width=1.5, color=_IO_COLORS[col]),
            hovertemplate="%{x}<br>" + col + ": %{y:,.3g}<extra></extra>",
        ))

    # --- Routing metrics: one independent y-axis each (y3..y7, main row) ---
    for col in _ROU_COLS:
        if col not in mgstat_df.columns:
            print(f"  Skipping missing column: {col}")
            continue
        series = _smooth(pd.to_numeric(mgstat_df[col], errors="coerce"),
                         mgstat_df[mg_dt_col], smooth_minutes)
        fig.add_trace(go.Scatter(
            x=mgstat_df[mg_dt_col],
            y=series,
            mode="lines",
            name=col,
            xaxis="x", yaxis=_ROU_YAXIS[col],
            visible=True if col in _DEFAULT_VISIBLE else "legendonly",
            line=dict(width=1.5, color=_ROU_COLORS[col]),
            hovertemplate="%{x}<br>" + col + ": %{y:,.3g}<extra></extra>",
        ))

    # Build routing axis definitions — hidden axes start invisible, visible ones
    # get contiguous shifts so there are no gaps on initial render.
    routing_axes = {}
    shift_idx = 0
    for i, col in enumerate(_ROU_COLS):
        is_visible = col in _DEFAULT_VISIBLE
        if is_visible:
            shift = (shift_idx + 1) * 80
            shift_idx += 1
        else:
            shift = 80  # irrelevant — axis is hidden
        routing_axes[f"yaxis{i + 3}"] = dict(
            title=col,
            overlaying="y",
            side="right",
            anchor="free",
            shift=shift,
            rangemode="tozero",
            tickfont=dict(size=10),
            showgrid=False,
            visible=is_visible,
        )

    io_visible = any(col in _DEFAULT_VISIBLE for col in _IO_COLS)
    n_visible_rou = sum(1 for col in _ROU_COLS if col in _DEFAULT_VISIBLE)
    initial_margin_r = max(60, n_visible_rou * 80 + 160)

    fig.update_layout(
        title=dict(
            text=f"vmstat CPU + mgstat IO — Combined Overlay"
                 + (f" ({smooth_minutes:.0f} min avg)" if smooth_minutes > 0 else ""),
            font=dict(size=16),
            x=0.5,
            xanchor="center",
        ),
        # Main row axes
        xaxis=dict(tickfont=dict(size=11), anchor="y"),
        yaxis=dict(
            title="CPU %",
            tickfont=dict(size=12),
            domain=[0.30, 1.0],
            range=[0, 100],
            side="left",
        ),
        yaxis2=dict(
            title="mgstat IO",
            tickfont=dict(size=12),
            overlaying="y",
            side="right",
            rangemode="tozero",
            visible=io_visible,
        ),
        **routing_axes,
        # Overview row axes
        xaxis2=dict(
            title="Drag box here to zoom ↑   (double-click top chart to reset)",
            tickfont=dict(size=11),
            anchor="y8",
        ),
        yaxis8=dict(
            domain=[0.0, 0.22],
            showticklabels=False,
            rangemode="tozero",
        ),
        legend=dict(
            bgcolor="rgba(240,240,240,0.85)", bordercolor="gray", borderwidth=1,
            font=dict(size=12), orientation="v",
            title=dict(text="Click to show/hide", font=dict(size=11, color="grey")),
            x=0.99, y=0.99, xanchor="right", yanchor="top",
        ),
        margin=dict(r=initial_margin_r),
        height=800,
        hovermode="x unified",
        template="plotly_white",
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fig.write_html(
        output_path,
        include_plotlyjs="cdn",
        post_script=_OVERVIEW_ZOOM_JS + _AXIS_TOGGLE_JS,
        full_html=True,
    )
    print(f"  Written: {output_path}")


def run(sql_path: str, output_dir: str, smooth_minutes: float = 5) -> None:
    """Public entry point. Called by yaspe.py when --combined is given."""
    mgstat_df, vmstat_df = _load_dataframes(sql_path)

    if mgstat_df.empty:
        print("  No mgstat data found in database — cannot build combined chart.")
        return
    if vmstat_df.empty:
        print("  No vmstat data found in database — cannot build combined chart.")
        return

    mg_dt_col = _detect_datetime_column(mgstat_df)
    vm_dt_col = _detect_datetime_column(vmstat_df)

    if not mg_dt_col:
        print("  Could not detect datetime column in mgstat — skipping.")
        return
    if not vm_dt_col:
        print("  Could not detect datetime column in vmstat — skipping.")
        return

    output_path = os.path.join(output_dir, "combined_overlay.html")
    _build_combined_chart(mgstat_df, vmstat_df, mg_dt_col, vm_dt_col,
                          output_path, smooth_minutes=smooth_minutes)
