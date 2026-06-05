# Multi-Instance Overlay Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--compare-dir/-C` flag to `yaspe.py` that reads all HTML SystemPerformance files from a directory, extracts vmstat and mgstat into per-file SQLites, then produces one interactive Plotly HTML overlay chart per metric column with all instances on a shared HH:MM x-axis.

**Architecture:** All compare logic lives in a new `yaspe_compare_overlay.py` module. `yaspe.py` adds one argparse flag and delegates immediately to `yaspe_compare_overlay.run(directory)` — no existing code paths are touched. The new module calls the existing `sp_check.system_check()`, `create_overview()`, and `extract_sections()` functions from `yaspe.py` (imported directly) to avoid duplicating extraction logic.

**Tech Stack:** Python 3, plotly, pandas, sqlite3, re, pathlib — all already used in the project.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `yaspe_compare_overlay.py` | **Create** | All compare logic: HTML discovery, extraction, instance name parsing, SQLite management, overlay charting |
| `yaspe.py` | **Modify** | Add `-C/--compare-dir` argparse argument; call `yaspe_compare_overlay.run()` when set |
| `tests/test_compare_overlay.py` | **Create** | Unit tests for instance name extraction and x-axis normalisation |

---

## Task 1: Create the new branch

- [ ] **Step 1: Create and switch to feature branch**

```bash
git checkout -b feature/compare-dir-overlay
```

Expected: `Switched to a new branch 'feature/compare-dir-overlay'`

- [ ] **Step 2: Verify clean state**

```bash
git status
```

Expected: `nothing to commit, working tree clean`

---

## Task 2: Scaffold `yaspe_compare_overlay.py` with instance name extraction

**Files:**
- Create: `yaspe_compare_overlay.py`
- Create: `tests/test_compare_overlay.py`

- [ ] **Step 1: Write the failing test for `_extract_instance_name`**

Create `tests/test_compare_overlay.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe_compare_overlay as yco


def test_extract_instance_name_from_html():
    html = """
    Instance Name     Version ID        Port   Directory
    ----------------  ----------------  -----  --------------------------------
up >MCMELIVETCC       2024.1.1.347.0.2  56772  /trak/mcme/live/tc/hs
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        path = f.name
    try:
        assert yco._extract_instance_name(path) == "MCMELIVETCC"
    finally:
        os.unlink(path)


def test_extract_instance_name_fallback():
    html = "<html><body>no instance here</body></html>"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False,
                                     prefix="MY_SERVER_") as f:
        f.write(html)
        path = f.name
    try:
        result = yco._extract_instance_name(path)
        assert result == os.path.splitext(os.path.basename(path))[0]
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe && python -m pytest tests/test_compare_overlay.py -v
```

Expected: `ModuleNotFoundError: No module named 'yaspe_compare_overlay'`

- [ ] **Step 3: Create `yaspe_compare_overlay.py` with `_extract_instance_name`**

```python
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


def run(directory: str) -> None:
    """Entry point called by yaspe.py when --compare-dir is given."""
    pass  # implemented in later tasks
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_compare_overlay.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add yaspe_compare_overlay.py tests/test_compare_overlay.py
git commit -m "feat: scaffold yaspe_compare_overlay with instance name extraction"
```

---

## Task 3: Add x-axis normalisation test and helper

**Files:**
- Modify: `yaspe_compare_overlay.py`
- Modify: `tests/test_compare_overlay.py`

- [ ] **Step 1: Add failing test for `_normalise_to_timeofday`**

Append to `tests/test_compare_overlay.py`:

```python
def test_normalise_to_timeofday():
    ts = pd.Timestamp("2026-02-12 14:30:00")
    result = yco._normalise_to_timeofday(ts)
    assert result == pd.Timestamp("2000-01-01 14:30:00")


def test_normalise_preserves_seconds():
    ts = pd.Timestamp("2026-03-31 00:01:30")
    result = yco._normalise_to_timeofday(ts)
    assert result == pd.Timestamp("2000-01-01 00:01:30")
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_compare_overlay.py::test_normalise_to_timeofday -v
```

Expected: `AttributeError: module 'yaspe_compare_overlay' has no attribute '_normalise_to_timeofday'`

- [ ] **Step 3: Add `_normalise_to_timeofday` to `yaspe_compare_overlay.py`**

Add after `_extract_instance_name`:

```python
def _normalise_to_timeofday(ts: pd.Timestamp) -> pd.Timestamp:
    """Map any timestamp to 2000-01-01 HH:MM:SS so all traces share one x-axis."""
    return pd.Timestamp("2000-01-01") + (ts - ts.normalize())
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_compare_overlay.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add yaspe_compare_overlay.py tests/test_compare_overlay.py
git commit -m "feat: add x-axis normalisation helper"
```

---

## Task 4: Implement `_extract_to_sqlite` — per-file extraction

**Files:**
- Modify: `yaspe_compare_overlay.py`

This task wires up the existing `sp_check`, `create_overview`, `create_connection`, and `create_sections` from `yaspe.py`. We import them directly to avoid duplication.

- [ ] **Step 1: Add imports to top of `yaspe_compare_overlay.py`**

Replace the existing import block with:

```python
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
```

- [ ] **Step 2: Add `_extract_to_sqlite` after `_normalise_to_timeofday`**

```python
def _extract_to_sqlite(html_path: str) -> str:
    """Extract vmstat and mgstat from html_path into a per-file SQLite.

    Returns the path to the SQLite file.
    Re-uses yaspe's sp_check, create_overview, create_connection, and
    create_sections so all parsing logic stays in one place.
    """
    # Import here to avoid circular imports at module level
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
            include_iostat=False,
            include_nfsiostat=False,
            html_filename=html_basename,
            csv_out=False,
            output_filepath_prefix=os.path.join(directory, f"{html_basename}_"),
            disk_list=[],
            csv_date_format=False,
        )

    conn.close()
    return sql_path
```

- [ ] **Step 3: Verify the module still imports cleanly**

```bash
python -c "import yaspe_compare_overlay; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Run existing tests to confirm no regression**

```bash
python -m pytest tests/test_compare_overlay.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add yaspe_compare_overlay.py
git commit -m "feat: add _extract_to_sqlite using existing yaspe extraction pipeline"
```

---

## Task 5: Implement `_load_dataframes` — read vmstat/mgstat from SQLite

**Files:**
- Modify: `yaspe_compare_overlay.py`
- Modify: `tests/test_compare_overlay.py`

- [ ] **Step 1: Add failing test for `_load_dataframes`**

Append to `tests/test_compare_overlay.py`:

```python
def test_load_dataframes_returns_empty_for_missing_tables():
    import tempfile, sqlite3 as sql
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sql.connect(db_path)
        conn.close()
        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert mgstat_df.empty
        assert vmstat_df.empty
    finally:
        os.unlink(db_path)


def test_load_dataframes_reads_tables():
    import tempfile, sqlite3 as sql
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sql.connect(db_path)
        conn.execute(
            "CREATE TABLE mgstat (id INTEGER PRIMARY KEY, DateTime TEXT, metric REAL)"
        )
        conn.execute(
            "INSERT INTO mgstat VALUES (1, '2026-02-12 10:00:00', 42.0)"
        )
        conn.commit()
        conn.close()

        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert len(mgstat_df) == 1
        assert vmstat_df.empty
    finally:
        os.unlink(db_path)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_compare_overlay.py::test_load_dataframes_returns_empty_for_missing_tables -v
```

Expected: `AttributeError: module 'yaspe_compare_overlay' has no attribute '_load_dataframes'`

- [ ] **Step 3: Add `_load_dataframes` to `yaspe_compare_overlay.py`**

Add after `_extract_to_sqlite`:

```python
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
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_compare_overlay.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add yaspe_compare_overlay.py tests/test_compare_overlay.py
git commit -m "feat: add _load_dataframes to read vmstat/mgstat from SQLite"
```

---

## Task 6: Implement `_build_overlay_charts`

**Files:**
- Modify: `yaspe_compare_overlay.py`

This produces one HTML chart per numeric column that is present in all datasets.

- [ ] **Step 1: Add `_build_overlay_charts` to `yaspe_compare_overlay.py`**

Add after `_load_dataframes`:

```python
def _build_overlay_charts(datasets: list, metric_type: str, output_dir: str) -> None:
    """Produce one Plotly HTML overlay chart per common numeric column.

    datasets: list of {"label": str, "df": pd.DataFrame, "datetime_col": str}
    metric_type: "mgstat" or "vmstat" (used only in chart titles)
    output_dir: directory where HTML files are written
    """
    os.makedirs(output_dir, exist_ok=True)

    if not datasets:
        return

    # Find numeric columns present in every dataset (exclude the datetime column itself)
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
```

- [ ] **Step 2: Verify module imports cleanly**

```bash
python -c "import yaspe_compare_overlay; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Run all tests**

```bash
python -m pytest tests/test_compare_overlay.py -v
```

Expected: `6 passed`

- [ ] **Step 4: Commit**

```bash
git add yaspe_compare_overlay.py
git commit -m "feat: implement _build_overlay_charts and _write_overlay_html"
```

---

## Task 7: Implement `run()` — the main entry point

**Files:**
- Modify: `yaspe_compare_overlay.py`

- [ ] **Step 1: Replace the stub `run()` with the full implementation**

Replace:

```python
def run(directory: str) -> None:
    """Entry point called by yaspe.py when --compare-dir is given."""
    pass  # implemented in later tasks
```

With:

```python
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
```

- [ ] **Step 2: Add `_detect_datetime_column` helper (needed by `run()`)**

Add before `run()`:

```python
def _detect_datetime_column(df: pd.DataFrame) -> str:
    """Return the name of the datetime column in df, or empty string if not found.
    Checks common names used by yaspe: 'DateTime', 'RunDate', 'Date/Time'."""
    for candidate in ("DateTime", "RunDate", "Date/Time", "datetime"):
        if candidate in df.columns:
            return candidate
    # Fallback: first object column that looks like a datetime
    for col in df.select_dtypes(include="object").columns:
        try:
            pd.to_datetime(df[col].iloc[0])
            return col
        except Exception:
            continue
    return ""
```

- [ ] **Step 3: Run all tests**

```bash
python -m pytest tests/test_compare_overlay.py -v
```

Expected: `6 passed`

- [ ] **Step 4: Commit**

```bash
git add yaspe_compare_overlay.py
git commit -m "feat: implement run() entry point with full directory processing pipeline"
```

---

## Task 8: Wire `--compare-dir` flag into `yaspe.py`

**Files:**
- Modify: `yaspe.py:2912-2919` (after the last `add_argument` call, before `args = parser.parse_args()`)

- [ ] **Step 1: Add the import at the top of `yaspe.py`**

Find the existing import block (around line 31):

```python
from extract_sections import extract_sections
from extract_mgstat import extract_mgstat
import system_review
```

Add one line after it:

```python
import yaspe_compare_overlay
```

- [ ] **Step 2: Add the argparse argument**

Find the last `add_argument` call before `args = parser.parse_args()` (currently around line 2912):

```python
    parser.add_argument(
        "--no_peak_chart",
        dest="peak_chart",
        help="Disable peak 60-minute charts.",
        action="store_false",
    )

    args = parser.parse_args()
```

Insert the new argument between `--no_peak_chart` and `args = parser.parse_args()`:

```python
    parser.add_argument(
        "-C",
        "--compare-dir",
        dest="compare_dir",
        help="Compare all HTML files in a directory: produce vmstat and mgstat overlay charts.",
        action="store",
        metavar='"/path/to/directory"',
    )

    args = parser.parse_args()
```

- [ ] **Step 3: Add the early-exit compare path**

Find the block just after `args = parser.parse_args()` (around line 2920):

```python
    args = parser.parse_args()

    # Validate input file
    if args.input_file is not None:
```

Insert between them:

```python
    args = parser.parse_args()

    if args.compare_dir is not None:
        yaspe_compare_overlay.run(args.compare_dir)
        sys.exit(0)

    # Validate input file
    if args.input_file is not None:
```

- [ ] **Step 4: Verify `--help` shows the new flag**

```bash
python yaspe.py --help | grep compare
```

Expected output contains: `-C "/path/to/directory", --compare-dir "/path/to/directory"`

- [ ] **Step 5: Run existing tests to confirm no regression**

```bash
python -m pytest tests/test_compare_overlay.py -v
```

Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add yaspe.py
git commit -m "feat: add -C/--compare-dir flag to yaspe.py"
```

---

## Task 9: Smoke test against real sample data

**Files:** none modified — this is a manual verification step.

- [ ] **Step 1: Run against the sample directory**

```bash
python yaspe.py -C "test_samples/differnet_servers"
```

Expected output (approximate):
```
Found 3 HTML file(s) in .../test_samples/differnet_servers
Processing: aemedcprehrdb03_MCMELIVETCC_20260212_000005_24hours_5.html
Processing: svnh-trak-livetc01_THSVLIVETC01_20260331_000130_24hours_2sec.html
Processing: trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html

Building mgstat overlay charts (3 traces)...
  Written: .../compare_overlay/mgstat/gloref_s_overlay.html
  ...

Building vmstat overlay charts (3 traces)...
  Written: .../compare_overlay/vmstat/us_overlay.html
  ...

Done. Charts written to: .../compare_overlay
```

- [ ] **Step 2: Check output directory was created**

```bash
ls test_samples/differnet_servers/compare_overlay/mgstat/ | head -10
ls test_samples/differnet_servers/compare_overlay/vmstat/ | head -10
```

Expected: multiple `*_overlay.html` files in each.

- [ ] **Step 3: Open a chart and visually verify**

Open one of the HTML files in a browser. Confirm:
- Three traces visible (MCMELIVETCC, THSVLIVETC01, MEKKESHLIVETCA + dates)
- X-axis shows HH:MM (00:00–24:00 range)
- Hover shows actual date + time + value
- Overview/zoom panel visible at bottom
- Legend entries show instance name + date

- [ ] **Step 4: Commit the smoke test SQLite files if desired (optional — they are derived)**

If you want to keep the generated SQLites out of git, add to `.gitignore`:

```
test_samples/differnet_servers/*_SystemPerformance.sqlite
test_samples/differnet_servers/compare_overlay/
```

```bash
git add .gitignore
git commit -m "chore: ignore generated SQLite and compare_overlay output in test_samples"
```

---

## Task 10: Version bump and push

- [ ] **Step 1: Bump patch version**

```bash
bump2version patch
```

Expected: creates a commit like `Bump version: 0.5.1 → 0.5.2`

- [ ] **Step 2: Push the feature branch**

```bash
git push origin feature/compare-dir-overlay
```

- [ ] **Step 3: Open PR or merge to main per team workflow**
