# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

`yaspe` (Yet Another System Performance Extractor) parses InterSystems IRIS/Caché **pButtons** and **SystemPerformance** HTML files, extracts metrics (mgstat, vmstat, iostat, Windows Perfmon, AIX sar), stores them in SQLite, and generates charts. It supports Linux, Windows, and AIX data sources.

## Running locally (no Docker)

```bash
pip3 install -r requirements.txt
```

```bash
# Process a SystemPerformance HTML file
./yaspe.py -i /path/to/file.html

# Create SQLite DB + system check + iostat charts
./yaspe.py -i /path/to/file.html -a -s -x -o yaspe

# Chart from existing SQLite (PNG output)
./yaspe.py -e /path/to/yaspe_SystemPerformance.sqlite -p

# Chart from existing SQLite (HTML output)
./yaspe.py -e /path/to/yaspe_SystemPerformance.sqlite

# Process an .mgst mgstat log file directly
./yaspe.py -i /path/to/file.mgst -m

# Pretty Performance charts (combined metrics)
./pretty_performance.py -f yaspe_SystemPerformance.sqlite -s 10:00 -e 11:00 -p input.yml -i -m -c charts.yml -o ./pretty_yaspe
```

## Architecture

### Core pipeline (`yaspe.py`)

1. **Parse HTML** → `split_large_file.py` splits large files, `extract_sections.py` reads vmstat/iostat/mgstat sections, `extract_mgstat.py` handles standalone `.mgst` files
2. **Store in SQLite** → each metric type goes into its own table; connections use WAL mode for performance
3. **Chart** → reads back from SQLite via pandas DataFrames, renders with matplotlib/seaborn (default: line chart) or altair (HTML interactive charts)

### Module responsibilities

| File | Role |
|------|------|
| `yaspe.py` | Main entry point: CLI args, orchestration, SQLite creation, chart dispatch |
| `extract_sections.py` | Parses vmstat, iostat, mgstat, nfsiostat from HTML; handles Linux/AIX/Windows differences |
| `extract_mgstat.py` | Parses standalone `.mgst` mgstat log files |
| `chart_templates.py` | Low-level matplotlib chart rendering (`chart_multi_line`, etc.) |
| `chart_output.py` | Higher-level chart dispatch for iostat, vmstat, mgstat |
| `yaspe_utilities.py` | Shared helpers: number parsing, date formatting, locale handling |
| `system_review.py` | Extracts system overview info and generates `_overview.txt` / `_overview_all.csv` |
| `sp_check.py` | System performance config checks (HugePages, kernel params, etc.) |
| `split_large_file.py` | Splits large HTML files before parsing |
| `pretty_performance.py` | Standalone tool: reads SQLite from yaspe, produces combined metric charts using `input.yml` + `charts.yml` |

### Configuration files for `pretty_performance.py`

- **`input.yml`** — Site-specific: site name, disk device names (Database, Primary Journal, Alternate Journal, WIJ, IRIS), chart DPI/dimensions. See `examples/input.yml`.
- **`charts.yml`** — Chart definitions: which columns to plot, axis assignments, zoom ranges. Column names use suffixes: `_mg` (mgstat), `_vm` (vmstat), `_db/_pri/_wij/_iris` (iostat by disk type). See `examples/charts.yml`.

### Chart output

- Default: interactive HTML charts (altair)
- `-p`: static PNG charts (matplotlib)
- `-P`: both PNG and HTML
- Charts are written to `{prefix}_metrics/` subdirectories
- `line_chart` is the default chart type; `--dots` selects dot/scatter style

### Multi-day workflow

```bash
# Step 1: append each day's HTML into one SQLite
for i in *.html; do ./yaspe.py -i "$i" -a -s -x -o yaspe; done

# Step 2: chart the combined DB
./yaspe.py -e yaspe_SystemPerformance.sqlite -p
```

The resulting SQLite file is named `{prefix}_SystemPerformance.sqlite`.

## Flask web app sync

This CLI repo is the **source of truth** for all engine files. A companion Flask repo at `/Users/moldfiel/projects/all_live_projects/yaspe_flask_v1` copies these files via `sync_engine.sh`.

**When you add, rename, or remove a `.py` module in this repo, update `ENGINE_FILES` in `yaspe_flask_v1/sync_engine.sh`.**

Rules:
- Add any new `.py` file that is imported (directly or transitively) by `yaspe.py`.
- Remove entries for files that have been deleted or renamed.
- Do not add standalone tools not imported by `yaspe.py` (e.g. `yaspe_runner.py`, `vmstat_example.py`).
- Note the sync script change in your commit message.

To verify nothing is missing: check the local imports at the top of `yaspe.py` and confirm every one appears in `ENGINE_FILES`.

Current engine files tracked:
`yaspe.py`, `extract_sections.py`, `extract_mgstat.py`, `sp_check.py`, `split_large_file.py`, `system_review.py`, `chart_output.py`, `chart_templates.py`, `yaspe_utilities.py`, `pretty_performance.py`, `yaspe_compare_overlay.py`, `yaspe_combined_overlay.py`

## Version numbering

This project uses `bump2version` (`.bumpversion.cfg`). After committing and merging to `main`, always bump the version before pushing:

```bash
bump2version patch   # bug fixes
bump2version minor   # new features
bump2version major   # breaking changes
```

`bump2version` updates `current_version` in `.bumpversion.cfg` and `yaspe.py`, then creates its own commit automatically. Push that commit along with the rest:

```bash
git push origin main
```

Do not amend or squash the bump2version commit.
