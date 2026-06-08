# Combined vmstat+mgstat Overlay Chart — Design Spec

**Date:** 2026-06-07
**Status:** Approved

---

## Summary

Add a new HTML overlay chart that plots vmstat CPU breakdown and mgstat IO/routing metrics on a single interactive Plotly chart, readable from an existing SQLite database via a new `--combined` CLI flag.

---

## Architecture

New module: `yaspe_combined_overlay.py`
Public entry point: `run(sql_path: str, output_dir: str) -> None`

```
yaspe.py  -B --combined  -e /path/to.sqlite  [-o output_prefix]
    └── yaspe_combined_overlay.run(sql_path, output_dir)
            ├── load mgstat + vmstat from SQLite
            └── write combined_overlay.html
```

`yaspe.py` changes are minimal: one new `add_argument` call and one `if args.combined` branch that validates `-e` is also present, then calls `yaspe_combined_overlay.run(...)`.

---

## Chart Structure

Single Plotly HTML file: `combined_overlay.html`

Two subplot rows:
- **Row 1 (75%)** — main multi-axis chart
- **Row 2 (25%)** — overview/zoom panel (mirrors CPU stack from row 1)

### Seven y-axes in Row 1

| Axis | Side | Series | Style |
|---|---|---|---|
| yaxis (left) | left | `wa`, `us`, `sy` | stacked filled areas (`stackgroup="cpu"`), semi-transparent |
| yaxis2 (right, anchored) | right | `WIJwri`, `PhyRds`, `PhyWrs`, `Jrnwrts` | solid lines (shared IO axis) |
| yaxis3 (right, free, shift 0px) | right | `Rourefs` | dashed line |
| yaxis4 (right, free, shift +80px) | right | `RouLaS` | dashed line |
| yaxis5 (right, free, shift +160px) | right | `RouCMs` | dashed line |
| yaxis6 (right, free, shift +240px) | right | `Gloupds` | dashed line |
| yaxis7 (right, free, shift +320px) | right | `Glorefs` | dashed line |

All 15 traces individually toggleable via legend click (Plotly default behaviour).
Each routing metric has its own independent scale — necessary because `Glorefs` can be orders of magnitude larger than `RouCMs`.

The overview panel (row 2) mirrors the CPU stacked area only — keeps the zoom panel readable.

X-axis: actual datetime values from the SQLite (no time-of-day normalisation — single dataset).

Zoom JS: reuse the `_OVERVIEW_ZOOM_JS` pattern from `yaspe_compare_overlay.py` to sync zoom between main and overview panels.

---

## Module: `yaspe_combined_overlay.py`

### Functions

| Function | Purpose |
|---|---|
| `run(sql_path, output_dir)` | Public entry point. Loads data, calls chart builder, writes HTML. |
| `_load_dataframes(sql_path)` | Returns `(mgstat_df, vmstat_df)`. Same pattern as compare overlay. |
| `_detect_datetime_column(df)` | Checks `datetime`, `DateTime`, `Date/Time`, `RunDate`. Same as compare overlay. |
| `_build_combined_chart(mgstat_df, vmstat_df, mg_dt_col, vm_dt_col, output_path)` | Builds and writes the Plotly figure. |

### Missing column handling

If any expected column is absent from the loaded DataFrame, that trace is silently skipped and a one-line console notice is printed:
```
  Skipping missing column: PhyWrs
```

---

## CLI Integration

New argument in `yaspe.py`:

```python
parser.add_argument(
    "-B",
    "--combined",
    dest="combined_overlay",
    help="Create a combined vmstat+mgstat overlay HTML chart from an existing database (requires -e).",
    action="store_true",
)
```

Behaviour:
- Requires `-e` to be present. If missing: print error, exit 1.
- Output file is written to the same directory as the SQLite file (i.e. `os.path.dirname(sql_path)`).
- `-o` (output prefix) is not used for this flag — output path is always derived from the SQLite location.
- Exits after writing the chart (does not continue into normal chart generation).

Example usage:
```bash
./yaspe.py -e /path/to/yaspe_SystemPerformance.sqlite -B
```

Output file: `{sqlite_directory}/combined_overlay.html`

---

## Out of Scope

- PNG output for the combined chart (HTML only)
- Multi-instance overlays (that's the `-C` compare-dir workflow)
- Smoothing (single dataset; raw values shown)
- Windows Perfmon or AIX sar columns (Linux vmstat + mgstat only)
