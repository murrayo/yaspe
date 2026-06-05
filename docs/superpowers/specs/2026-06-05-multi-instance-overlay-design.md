# Multi-Instance Overlay Charts — Design Spec

**Date:** 2026-06-05
**Status:** Approved

## Overview

Add a `--compare-dir` flag to `yaspe.py` that produces interactive HTML overlay charts from all SystemPerformance HTML files in a directory. Each file becomes one trace. X-axis is time of day (HH:MM). The legend shows `"{instance_name} {date}"` per trace. Only vmstat and mgstat metrics are charted. Only HTML output is produced.

## CLI

```bash
yaspe.py --compare-dir "/path/to/directory"
```

- Short flag: `-C`
- When `-C` is given, all other flags are ignored. The compare path is the only required input.
- Added to the existing argparse block in `yaspe.py`. After parsing, `yaspe.py` calls `yaspe_compare_overlay.run(directory)` and exits. No other existing code is touched.

## New Module: `yaspe_compare_overlay.py`

All compare logic lives here. `yaspe.py` only adds the flag and calls `run()`.

### `run(directory: str) -> None`

1. Glob `*.html` in `directory` (non-recursive).
2. For each HTML file, call existing `extract_sections()` to extract vmstat and mgstat data, writing a per-file SQLite named `{html_basename}_SystemPerformance.sqlite` in the same directory. If the SQLite already exists, append (same as `-a` flag).
3. For each SQLite, read vmstat and mgstat tables into pandas DataFrames.
4. Extract the instance name (see below).
5. Build a trace label: `"{instance_name} {date}"` where date is formatted as `DD-Mon-YYYY` from the first timestamp in the data.
6. Call `_build_overlay_charts()` to produce charts.

### Instance name extraction

```python
import re

def _extract_instance_name(html_path: str) -> str:
    with open(html_path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    m = re.search(r'up\s*>\s*(\S+)', text)
    if m:
        return m.group(1)
    return Path(html_path).stem   # fallback: filename without extension
```

### `_build_overlay_charts(datasets, metric_type, output_dir)`

- `datasets`: list of `{"label": str, "df": DataFrame, "datetime_col": str}`
- `metric_type`: `"mgstat"` or `"vmstat"`
- `output_dir`: `{input_dir}/compare_overlay/{metric_type}/`
- For each numeric column present in all DataFrames, produce one Plotly HTML file named `{column_name}_overlay.html`.

### Chart design

- One trace per file/dataset.
- X-axis: **normalised to a shared reference date** (`2000-01-01`) so all traces overlap on the same `HH:MM` axis regardless of their actual calendar date. Each timestamp `ts` is mapped via `pd.Timestamp("2000-01-01") + (ts - ts.normalize())` (same technique as `_create_day_overlay_html()`). Hover shows the actual date + time + value via `customdata`.
- Y-axis: starts at 0, auto-scales to data.
- Overview/zoom panel (same 75%/25% two-row subplot as `_create_day_overlay_html()`).
- Legend: `"{instance_name} {date}"`, positioned outside the chart area, click-to-hide per trace.
- Hover: actual datetime + value.
- Template: `plotly_white`.
- `include_plotlyjs="cdn"` — no bundled JS.

### Output structure

```
{input_dir}/
  compare_overlay/
    mgstat/
      gloref_s_overlay.html
      PhyRds_s_overlay.html
      ...
    vmstat/
      us_overlay.html
      wa_overlay.html
      ...
```

`/` characters in column names are replaced with `_` in filenames (same as existing code).

## What is NOT in scope

- PNG output.
- iostat, nfsiostat, AIX sar, perfmon — only vmstat and mgstat.
- Interactivity beyond what Plotly provides by default (zoom, hover, click-to-hide).
- Modifying any existing chart functions or the mainline path.

## Files changed

| File | Change |
|------|--------|
| `yaspe.py` | Add `-C / --compare-dir` arg; call `yaspe_compare_overlay.run()` when set |
| `yaspe_compare_overlay.py` | New module — all compare logic |

## Sample data

`test_samples/differnet_servers/` contains three HTML files:

| File | Instance (parsed) |
|------|------------------|
| `aemedcprehrdb03_MCMELIVETCC_20260212_000005_24hours_5.html` | `MCMELIVETCC` |
| `svnh-trak-livetc01_THSVLIVETC01_20260331_000130_24hours_2sec.html` | `THSVLIVETC01` |
| `trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html` | `MEKKESHLIVETCA` |

Instance name is parsed from the line matching `up >\s*(\S+)` in the Configuration section.
