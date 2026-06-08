# Combined vmstat+mgstat Overlay Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `-B`/`--combined` CLI flag to `yaspe.py` that reads an existing SQLite and writes a single interactive Plotly HTML chart (`combined_overlay.html`) showing vmstat CPU breakdown (stacked filled areas) and mgstat IO/routing metrics on seven y-axes (CPU left, IO right shared, one independent right axis per routing metric) with an overview/zoom panel.

**Architecture:** New module `yaspe_combined_overlay.py` mirrors the structure of `yaspe_compare_overlay.py` — `_load_dataframes`, `_detect_datetime_column`, and `_build_combined_chart` are private helpers; `run(sql_path, output_dir)` is the public entry point. `yaspe.py` grows one new argument (`-B`/`--combined`) and one `if args.combined_overlay` branch before the existing input-validation block, calling `yaspe_combined_overlay.run(...)` and then `sys.exit(0)`.

**Tech Stack:** Python 3, pandas, plotly (graph_objects + make_subplots), sqlite3 (stdlib), pytest

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `yaspe_combined_overlay.py` | **Create** | All chart logic for the combined overlay |
| `tests/test_combined_overlay.py` | **Create** | Unit tests for the new module |
| `yaspe.py` | **Modify** | Add `-B` argument + dispatch branch |

---

### Task 1: Scaffold the new module with `_load_dataframes` and `_detect_datetime_column`

**Files:**
- Create: `yaspe_combined_overlay.py`
- Create: `tests/test_combined_overlay.py`

These two helpers are identical in contract to the same-named functions in `yaspe_compare_overlay.py`, so they make an ideal starting seam and can be fully tested without Plotly.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_combined_overlay.py
import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaspe_combined_overlay as yco


def test_load_dataframes_empty_for_missing_tables():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.close()
        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert mgstat_df.empty
        assert vmstat_df.empty
    finally:
        os.unlink(db_path)


def test_load_dataframes_reads_mgstat_and_computes_total_cpu():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE mgstat (id INTEGER PRIMARY KEY, datetime TEXT, Glorefs REAL)"
        )
        conn.execute("INSERT INTO mgstat VALUES (1, '2026-04-30 10:00:00', 99.0)")
        conn.execute(
            "CREATE TABLE vmstat (id INTEGER PRIMARY KEY, datetime TEXT, us REAL, sy REAL, id REAL, wa REAL)"
        )
        conn.execute("INSERT INTO vmstat VALUES (1, '2026-04-30 10:00:00', 10.0, 5.0, 80.0, 5.0)")
        conn.commit()
        conn.close()

        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert len(mgstat_df) == 1
        assert len(vmstat_df) == 1
        # Total CPU = 100 - id
        assert vmstat_df["Total CPU"].iloc[0] == 20.0
    finally:
        os.unlink(db_path)


def test_detect_datetime_column_finds_datetime_lowercase():
    df = pd.DataFrame({"datetime": ["2026-04-30 10:00:00"], "val": [1.0]})
    assert yco._detect_datetime_column(df) == "datetime"


def test_detect_datetime_column_finds_DateTime():
    df = pd.DataFrame({"DateTime": ["2026-04-30 10:00:00"], "val": [1.0]})
    assert yco._detect_datetime_column(df) == "DateTime"


def test_detect_datetime_column_returns_empty_when_not_found():
    df = pd.DataFrame({"value": [1.0], "count": [2.0]})
    assert yco._detect_datetime_column(df) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -m pytest tests/test_combined_overlay.py -v
```

Expected: `ModuleNotFoundError: No module named 'yaspe_combined_overlay'`

- [ ] **Step 3: Create the module with the two helpers**

```python
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
```

- [ ] **Step 4: Run tests to verify helpers pass**

```bash
python -m pytest tests/test_combined_overlay.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add yaspe_combined_overlay.py tests/test_combined_overlay.py
git commit -m "feat: scaffold yaspe_combined_overlay with _load_dataframes and _detect_datetime_column"
```

---

### Task 2: Implement `_build_combined_chart`

**Files:**
- Modify: `yaspe_combined_overlay.py`
- Modify: `tests/test_combined_overlay.py`

The chart has two subplot rows (75%/25%), seven y-axes on row 1 (CPU left, IO right shared, one per routing metric right stacked), and a full CPU stacked area overview in row 2. Missing columns are skipped silently.

Axis layout:
- `y` (left): `wa`, `us`, `sy` stacked filled areas
- `y2` (right, anchored): `WIJwri`, `PhyRds`, `PhyWrs`, `Jrnwrts` solid lines — shared IO axis
- `y3`–`y7` (right, free, 80px apart): one per routing metric — `Rourefs`, `RouLaS`, `RouCMs`, `Gloupds`, `Glorefs` as dashed lines

- [ ] **Step 1: Add failing tests for `_build_combined_chart`**

Append to `tests/test_combined_overlay.py`:

```python
def _make_mgstat_df():
    return pd.DataFrame({
        "datetime": pd.date_range("2026-04-30 10:00", periods=5, freq="min").astype(str),
        "WIJwri":  [1.0, 2.0, 3.0, 4.0, 5.0],
        "PhyRds":  [10.0, 11.0, 12.0, 13.0, 14.0],
        "PhyWrs":  [5.0, 6.0, 7.0, 8.0, 9.0],
        "Jrnwrts": [0.1, 0.2, 0.3, 0.4, 0.5],
        "Rourefs": [100.0, 110.0, 120.0, 130.0, 140.0],
        "RouLaS":  [2.0, 2.1, 2.2, 2.3, 2.4],
        "RouCMs":  [0.0, 0.0, 0.1, 0.0, 0.0],
        "Gloupds": [50.0, 51.0, 52.0, 53.0, 54.0],
        "Glorefs": [200.0, 210.0, 220.0, 230.0, 240.0],
    })


def _make_vmstat_df():
    df = pd.DataFrame({
        "datetime": pd.date_range("2026-04-30 10:00", periods=5, freq="min").astype(str),
        "us": [10.0, 12.0, 11.0, 13.0, 10.0],
        "sy": [3.0, 4.0, 3.0, 5.0, 3.0],
        "wa": [2.0, 1.0, 2.0, 1.0, 2.0],
        "id": [85.0, 83.0, 84.0, 81.0, 85.0],
    })
    df["Total CPU"] = 100 - df["id"]
    return df


def test_build_combined_chart_writes_html():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "combined_overlay.html")
        yco._build_combined_chart(
            _make_mgstat_df(),
            _make_vmstat_df(),
            "datetime",
            "datetime",
            out_path,
        )
        assert os.path.exists(out_path)
        with open(out_path) as f:
            html = f.read()
        assert "WIJwri" in html
        assert "Rourefs" in html
        assert "Glorefs" in html
        assert "wa" in html


def test_build_combined_chart_skips_missing_columns(capsys):
    mg = _make_mgstat_df().drop(columns=["PhyWrs"])
    vm = _make_vmstat_df()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "combined_overlay.html")
        yco._build_combined_chart(mg, vm, "datetime", "datetime", out_path)
        captured = capsys.readouterr()
        assert "PhyWrs" in captured.out
        assert os.path.exists(out_path)


def test_build_combined_chart_skips_missing_vmstat_column(capsys):
    mg = _make_mgstat_df()
    vm = _make_vmstat_df().drop(columns=["wa"])
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "combined_overlay.html")
        yco._build_combined_chart(mg, vm, "datetime", "datetime", out_path)
        captured = capsys.readouterr()
        assert "wa" in captured.out
        assert os.path.exists(out_path)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_combined_overlay.py::test_build_combined_chart_writes_html -v
```

Expected: `AttributeError: module 'yaspe_combined_overlay' has no attribute '_build_combined_chart'`

- [ ] **Step 3: Implement `_build_combined_chart`**

Add the following block to `yaspe_combined_overlay.py` after `_detect_datetime_column`, before `run`:

```python
# Column groups
_CPU_COLS = ["wa", "us", "sy"]
_IO_COLS  = ["WIJwri", "PhyRds", "PhyWrs", "Jrnwrts"]
# Each routing metric gets its own y-axis (y3..y7)
_ROU_COLS = ["Rourefs", "RouLaS", "RouCMs", "Gloupds", "Glorefs"]

_ROU_YAXIS = {col: f"y{i + 3}" for i, col in enumerate(_ROU_COLS)}
# {"Rourefs": "y3", "RouLaS": "y4", "RouCMs": "y5", "Gloupds": "y6", "Glorefs": "y7"}

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
) -> None:
    """Build and write the combined Plotly HTML chart."""
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]],
    )

    # Parse and sort datetimes
    vmstat_df = vmstat_df.copy()
    mgstat_df = mgstat_df.copy()
    vmstat_df[vm_dt_col] = pd.to_datetime(vmstat_df[vm_dt_col])
    vmstat_df = vmstat_df.sort_values(vm_dt_col)
    mgstat_df[mg_dt_col] = pd.to_datetime(mgstat_df[mg_dt_col])
    mgstat_df = mgstat_df.sort_values(mg_dt_col)

    # --- CPU stacked areas on yaxis (left) ---
    for col in _CPU_COLS:
        if col not in vmstat_df.columns:
            print(f"  Skipping missing column: {col}")
            continue
        series = pd.to_numeric(vmstat_df[col], errors="coerce")
        color = _CPU_COLORS[col]
        fig.add_trace(go.Scatter(
            x=vmstat_df[vm_dt_col],
            y=series,
            mode="lines",
            name=col,
            stackgroup="cpu",
            line=dict(width=0.5, color=color),
            hovertemplate="%{x}<br>" + col + ": %{y:,.3g}<extra></extra>",
        ), row=1, col=1)
        # Overview panel: mirror full CPU stacked area (all three traces)
        fig.add_trace(go.Scatter(
            x=vmstat_df[vm_dt_col],
            y=series,
            mode="lines",
            name=col,
            stackgroup="cpu_overview",
            showlegend=False,
            line=dict(width=0.8, color=color),
            hoverinfo="skip",
        ), row=2, col=1)

    # --- IO metrics on yaxis2 (right, shared) ---
    for col in _IO_COLS:
        if col not in mgstat_df.columns:
            print(f"  Skipping missing column: {col}")
            continue
        series = pd.to_numeric(mgstat_df[col], errors="coerce")
        fig.add_trace(go.Scatter(
            x=mgstat_df[mg_dt_col],
            y=series,
            mode="lines",
            name=col,
            yaxis="y2",
            line=dict(width=1.5, color=_IO_COLORS[col]),
            hovertemplate="%{x}<br>" + col + ": %{y:,.3g}<extra></extra>",
        ), row=1, col=1)

    # --- Routing metrics: one independent y-axis each (y3..y7) ---
    for col in _ROU_COLS:
        if col not in mgstat_df.columns:
            print(f"  Skipping missing column: {col}")
            continue
        series = pd.to_numeric(mgstat_df[col], errors="coerce")
        fig.add_trace(go.Scatter(
            x=mgstat_df[mg_dt_col],
            y=series,
            mode="lines",
            name=col,
            yaxis=_ROU_YAXIS[col],
            line=dict(width=1.5, color=_ROU_COLORS[col], dash="dash"),
            hovertemplate="%{x}<br>" + col + ": %{y:,.3g}<extra></extra>",
        ), row=1, col=1)

    # Build routing axis definitions dynamically (y3..y7, stacked 80px apart)
    routing_axes = {
        f"yaxis{i + 3}": dict(
            title=col,
            overlaying="y",
            side="right",
            anchor="free",
            shift=i * 80,
            rangemode="tozero",
            tickfont=dict(size=10),
            showgrid=False,
        )
        for i, col in enumerate(_ROU_COLS)
    }

    fig.update_layout(
        title=dict(
            text="vmstat CPU + mgstat IO/Routing — Combined Overlay",
            font=dict(size=16),
        ),
        xaxis=dict(title="Time", tickfont=dict(size=13)),
        xaxis2=dict(
            title="Drag box here to zoom ↑   (double-click top chart to reset)",
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            title="CPU %",
            tickfont=dict(size=12),
            rangemode="tozero",
        ),
        yaxis2=dict(
            title="mgstat IO",
            tickfont=dict(size=12),
            anchor="x",
            overlaying="y",
            side="right",
            rangemode="tozero",
        ),
        **routing_axes,
        legend=dict(
            bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1,
            font=dict(size=12), orientation="v",
            title=dict(text="Click to show/hide", font=dict(size=11, color="grey")),
        ),
        margin=dict(r=460),
        height=800,
        hovermode="x unified",
        template="plotly_white",
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fig.write_html(
        output_path,
        include_plotlyjs="cdn",
        post_script=_OVERVIEW_ZOOM_JS,
        full_html=True,
    )
    print(f"  Written: {output_path}")
```

- [ ] **Step 4: Run tests to confirm chart tests pass**

```bash
python -m pytest tests/test_combined_overlay.py -v
```

Expected: all 8 tests PASS (5 from Task 1 + 3 new)

- [ ] **Step 5: Commit**

```bash
git add yaspe_combined_overlay.py tests/test_combined_overlay.py
git commit -m "feat: implement _build_combined_chart with independent y-axis per routing metric"
```

---

### Task 3: Implement `run()` and add a test for the full entry point

**Files:**
- Modify: `yaspe_combined_overlay.py`
- Modify: `tests/test_combined_overlay.py`

`run()` wires `_load_dataframes` → `_detect_datetime_column` → `_build_combined_chart` and handles the empty-dataframe edge case.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_combined_overlay.py`:

```python
def test_run_writes_combined_overlay_html():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE mgstat (id INTEGER PRIMARY KEY, datetime TEXT, "
            "WIJwri REAL, PhyRds REAL, PhyWrs REAL, Jrnwrts REAL, "
            "Rourefs REAL, RouLaS REAL, RouCMs REAL, Gloupds REAL, Glorefs REAL)"
        )
        for i in range(5):
            ts = f"2026-04-30 10:0{i}:00"
            conn.execute(
                "INSERT INTO mgstat VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (i + 1, ts, float(i), float(i * 10), float(i * 5),
                 float(i * 0.1), float(i * 100), float(i * 2),
                 float(i * 0.05), float(i * 50), float(i * 200)),
            )
        conn.execute(
            "CREATE TABLE vmstat (id INTEGER PRIMARY KEY, datetime TEXT, "
            "us REAL, sy REAL, wa REAL, id_col REAL)"
        )
        for i in range(5):
            ts = f"2026-04-30 10:0{i}:00"
            conn.execute(
                "INSERT INTO vmstat VALUES (?, ?, ?, ?, ?, ?)",
                (i + 1, ts, 10.0 + i, 3.0, 2.0, 85.0 - i),
            )
        conn.commit()
        conn.close()

        with tempfile.TemporaryDirectory() as tmpdir:
            yco.run(db_path, tmpdir)
            out_path = os.path.join(tmpdir, "combined_overlay.html")
            assert os.path.exists(out_path)
    finally:
        os.unlink(db_path)


def test_run_exits_gracefully_on_empty_dataframes(capsys):
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.close()
        with tempfile.TemporaryDirectory() as tmpdir:
            yco.run(db_path, tmpdir)
            captured = capsys.readouterr()
            assert "No mgstat" in captured.out or "No vmstat" in captured.out
            out_path = os.path.join(tmpdir, "combined_overlay.html")
            assert not os.path.exists(out_path)
    finally:
        os.unlink(db_path)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_combined_overlay.py::test_run_writes_combined_overlay_html tests/test_combined_overlay.py::test_run_exits_gracefully_on_empty_dataframes -v
```

Expected: both FAIL with `NotImplementedError`

- [ ] **Step 3: Implement `run()`**

Replace the `run()` stub in `yaspe_combined_overlay.py`:

```python
def run(sql_path: str, output_dir: str) -> None:
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
    _build_combined_chart(mgstat_df, vmstat_df, mg_dt_col, vm_dt_col, output_path)
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_combined_overlay.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add yaspe_combined_overlay.py tests/test_combined_overlay.py
git commit -m "feat: implement run() entry point with empty-dataframe guard"
```

---

### Task 4: Wire `-B`/`--combined` into `yaspe.py`

**Files:**
- Modify: `yaspe.py` (two small edits — one `add_argument`, one dispatch branch)

- [ ] **Step 1: Add the import at the top of `yaspe.py`**

Find the existing import line (around line 34):

```python
import yaspe_compare_overlay
```

Add immediately after it:

```python
import yaspe_combined_overlay
```

- [ ] **Step 2: Add the argument to the parser**

Find the existing `-C`/`--compare-dir` block (around line 2920):

```python
    parser.add_argument(
        "-C",
        "--compare-dir",
        dest="compare_dir",
        help="Compare all HTML files in a directory: produce vmstat and mgstat overlay charts.",
        action="store",
        metavar='"/path/to/directory"',
    )
```

Add the new argument immediately after it:

```python
    parser.add_argument(
        "-B",
        "--combined",
        dest="combined_overlay",
        help="Create a combined vmstat+mgstat overlay HTML chart from an existing database (requires -e).",
        action="store_true",
    )
```

- [ ] **Step 3: Add the dispatch branch**

Find the existing compare-dir dispatch (around line 2931):

```python
    if args.compare_dir is not None:
        yaspe_compare_overlay.run(args.compare_dir)
        sys.exit(0)
```

Add immediately after it:

```python
    if args.combined_overlay:
        if args.existing_database is None:
            print('Error: --combined requires -e with an existing database path.')
            sys.exit(1)
        output_dir = os.path.dirname(os.path.abspath(args.existing_database))
        yaspe_combined_overlay.run(args.existing_database, output_dir)
        sys.exit(0)
```

- [ ] **Step 4: Verify the import and argument exist**

```bash
python -c "import yaspe; print('import ok')"
python yaspe.py --help | grep -E "\-B|combined"
```

Expected:
```
import ok
  -B, --combined        Create a combined vmstat+mgstat overlay HTML chart from
```

- [ ] **Step 5: Smoke-test with real SQLite**

```bash
python yaspe.py -e test_samples/RHEL/yaspe_test_SystemPerformance.sqlite -B
ls test_samples/RHEL/combined_overlay.html
```

Expected: lines like `  Skipping missing column: ...` for any absent columns, `  Written: test_samples/RHEL/combined_overlay.html`, and file exists.

- [ ] **Step 6: Confirm error path works**

```bash
python yaspe.py -B
echo "exit code: $?"
```

Expected: `Error: --combined requires -e with an existing database path.` and `exit code: 1`

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS (existing compare_overlay tests + new combined_overlay tests)

- [ ] **Step 8: Commit**

```bash
git add yaspe.py
git commit -m "feat: add -B/--combined CLI flag to yaspe.py"
```

---

### Task 5: Manual verification and cleanup

**Files:**
- Read-only verification

- [ ] **Step 1: Open the HTML in a browser**

```bash
open test_samples/RHEL/combined_overlay.html
```

Verify:
- Chart loads with Plotly CDN (no local JS dependency)
- Left y-axis labelled "CPU %" — `wa`, `us`, `sy` appear as stacked filled areas
- Right y-axis labelled "mgstat IO" — `WIJwri`, `PhyRds`, `PhyWrs`, `Jrnwrts` as solid lines
- Five independent right y-axes, one each for `Rourefs`, `RouLaS`, `RouCMs`, `Gloupds`, `Glorefs`, displayed as dashed lines and stacked to the right of the IO axis
- Legend items are individually clickable (show/hide per trace)
- Overview panel at bottom; dragging a selection box updates the zoom on the main chart
- Hovering shows values for all visible traces

- [ ] **Step 2: Ensure `combined_overlay.html` is gitignored**

```bash
grep combined_overlay .gitignore
```

If not present:

```bash
echo "combined_overlay.html" >> .gitignore
git add .gitignore
git commit -m "chore: ignore generated combined_overlay.html"
```

- [ ] **Step 3: Final test run**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS
