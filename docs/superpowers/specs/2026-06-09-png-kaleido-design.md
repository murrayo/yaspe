# Design: Replace matplotlib PNG export with kaleido

**Date:** 2026-06-09
**Status:** Draft — for review

## Problem

PNG chart generation is significantly slower than HTML because each metric builds two completely independent figures: one in matplotlib (for PNG) and one in Plotly (for HTML). This doubles rendering work per chart and means `plt.style.use()`, `plt.subplots()`, and `plt.close()` are called for every single chart in a run.

## Approach: Single Plotly figure, two outputs

Use **kaleido** (`pip install kaleido`) to export the Plotly figure that is already built for HTML directly to PNG via `fig.write_image()`. One figure, two file formats. The `simple_chart()` matplotlib functions become redundant.

Kaleido starts a single headless Chromium instance the first time `write_image()` is called in a process, then reuses it for all subsequent exports. The per-chart overhead drops from "build new matplotlib figure + render + close" to "write_image() on existing Plotly fig".

## What changes

### `requirements.txt`
Add `kaleido`. Remove `matplotlib`, `seaborn` — subject to confirming nothing else in the codebase imports them outside of chart generation.

### `yaspe.py`

**Remove:** `simple_chart()`, `simple_chart_no_time()`, `simple_chart_stacked()`, `simple_chart_stacked_iostat()`, `simple_chart_histogram_iostat()` — all the matplotlib chart functions.

**Keep:** `linked_chart()`, `linked_chart_no_time()` and all other Plotly chart functions — unchanged.

**Modify:** All call sites that currently call both `simple_chart(...)` and `linked_chart(...)` for the same column. Replace the pair with a single call to a modified `linked_chart()` that also writes PNG when `-p` is requested:

```python
# Before (two separate calls):
simple_chart(data, column_name, title, max_y, png_filepath, output_prefix)
linked_chart(data, column_name, title, max_y, html_filepath, output_prefix)

# After (one call, two outputs):
linked_chart(data, column_name, title, max_y, filepath, output_prefix,
             write_png=include_png, png_path=png_filepath)
```

Inside `linked_chart()`, after `fig.write_html(...)`:

```python
if write_png:
    fig.write_image(png_path, scale=2, width=1400, height=650)
```

`scale=2` gives equivalent pixel density to the current `dpi=150` matplotlib output.

### `chart_templates.py`

This file contains the low-level matplotlib helpers used by `chart_output.py` (for the `pretty_performance` flow, which is being dropped). Once `pretty_performance.py` is removed, `chart_templates.py` can be deleted entirely. Until then, leave it in place.

### `chart_output.py`

Uses `chart_templates.py` for `pretty_performance`. Leave unchanged until `pretty_performance` is dropped.

## Dependency impact

| Library | Before | After |
|---|---|---|
| `matplotlib` | Required | Removable once pretty_performance dropped |
| `seaborn` | Required | Removable once pretty_performance dropped |
| `kaleido` | Not present | New dependency |
| `plotly` | Required | Required (unchanged) |

Note: `matplotlib` and `seaborn` should not be removed until `pretty_performance.py` is dropped, since `chart_output.py` still imports them. They can be removed in the same commit that drops `pretty_performance`.

## Expected output differences

- PNG files will use the Plotly white template rather than seaborn styling — cleaner, consistent with the HTML output
- File size will be comparable (PNG compression is handled by kaleido/Chromium)
- The overview/minimap panel present in HTML will also appear in the exported PNG (single figure)
- First PNG export in a run has ~0.5–1s kaleido startup cost; subsequent exports are fast

## Fallback

If kaleido is not installed, `fig.write_image()` raises `ValueError: No renderer found`. A try/except at startup can detect this and fall back to skipping PNG with a clear error message, rather than crashing mid-run.

## Files changed

- `requirements.txt` — add kaleido
- `yaspe.py` — remove matplotlib chart functions, modify `linked_chart` / `linked_chart_no_time` to accept `write_png` kwarg
- `chart_templates.py` — no change now; delete when pretty_performance dropped
- `chart_output.py` — no change now; delete when pretty_performance dropped

## Out of scope

- `pretty_performance.py` — uses matplotlib via `chart_output.py`; leave unchanged until dropped
- `yaspe_compare_overlay.py`, `yaspe_combined_overlay.py` — HTML only, no PNG output, no change needed
