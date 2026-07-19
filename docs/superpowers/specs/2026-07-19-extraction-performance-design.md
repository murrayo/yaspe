# Extraction performance: fast number conversion, section seeking, extraction-time disk filtering

**Date:** 2026-07-19
**Status:** Approved

## Problem

Processing a single 24-hour RHEL SystemPerformance HTML file (~365 MB) takes ~55 s,
almost entirely CPU. A one-week customer data set takes ~6.5 minutes. Profiling a real
file (`test_samples/RHEL 1 week`, 385 MB, 72 iostat devices, 5-second samples) shows:

| Cost centre | Share of runtime |
|---|---|
| `get_number_type()` — 23.6 M calls | ~76% |
| of which Python `locale` machinery (`setlocale`, `atof`, `localeconv`) | ~60% |
| line-scanning loop in `extract_sections()` | ~11% |
| pandas DataFrame construction | ~2% |
| SQLite insert (`to_sql`) | ~2% |

Key facts discovered:

- `locale.setlocale()` is called on **every** value conversion; `locale.atof()` is used
  for every non-integer value and each call runs `localeconv()` (26 s of the 84 s
  profiled run).
- The iostat section is 175 MB of the 385 MB file: 17,280 timestamp blocks × ~72
  devices = **1,244,160 rows per day**, all parsed and written to SQLite (154 MB DB per
  day) even though charting only uses the ~4 CPF-resolved IRIS devices (databases,
  journals, WIJ).
- ~68 MB of irisstat/EnsQCount sections sit between mgstat and vmstat and are scanned
  line-by-line (~15 substring tests per line) purely to get past them.
- SQLite loading is **not** a bottleneck (2 s with WAL mode).

## Goals

- Reduce per-file extraction time from ~55 s to roughly 5 s on the reference file.
- Reduce SQLite size for typical IRIS analysis runs (~150 MB/day → ~10 MB/day).
- No regression in robustness: malformed or unusual files must parse at least as well
  as today. Missing columns between days must not abort multi-day appends.
- No change to chart output for the normal workflow.

## Non-goals

- Full vectorised rewrite of section parsing with `pandas.read_csv` (deferred; only if
  the changes below prove insufficient).
- Any change to chart rendering, `pretty_performance.py`, or the Flask app beyond the
  normal engine-file sync.

## Design

### 1. Number conversion rewrite (`yaspe_utilities.py`)

- Move `locale.setlocale(locale.LC_ALL, "en_US.UTF-8")` to module import time. It is
  currently executed inside `get_number_type()` on every call.
- Reorder `get_number_type(s)`:
  1. `int(s)` — unchanged fast path for integers
  2. `float(s)` — new fast path; plain decimals (the overwhelming majority of iostat
     values) convert at C speed
  3. `locale.atof(s)` — retained fallback for locale-grouped strings such as
     `"1,035.70"` (which `float()` rejects), preserving European-number handling
  4. return `s` unchanged if all conversions fail
- Apply the same `float`-before-`atof` ordering to the fallback path of
  `get_aix_wacky_numbers()`.
- Semantics are identical: every string that converts today converts to the same value;
  strings that fail today still pass through unchanged.

**Verification gate:** run the current code and the new code over the same reference
day file into fresh databases; `sqlite3 <db> .dump` output must be byte-identical.

### 2. Section seeking with full-scan fallback (`extract_sections.py`)

- New pre-pass over the file reading ~4 MB chunks (`ISO-8859-1`), recording byte
  offsets of:
  - `Profile run` (header region — run start date)
  - `<!-- beg_mgstat -->` / `<!-- end_mgstat -->`
  - `<!-- beg_vmstat -->` / `<!-- end_vmstat -->`
  - `div id=free` and its terminator
  - `div id=iostat` / `id="iostat"` and the next `<div` (iostat has no end marker)
  - `id=nfsiostat` and its terminator, when nfsiostat is requested
  - Windows (`id=perfmon` / `<!-- end_win_perfmon -->`) and AIX (`<div id=sar-d>`)
    markers, per operating system
- Chunk boundaries: retain a tail overlap (length of the longest marker) between
  consecutive chunks so a marker straddling two chunks is still found.
- Main parse then feeds **only the byte ranges of needed sections** (plus the header
  region) to the existing line-parsing logic, which is unchanged. The ~68 MB of
  irisstat/EnsQCount content and everything after the last needed section is never
  line-scanned.
- **Fallback rule (advisory pre-pass, never authoritative):**
  - If a needed section's start marker is not found, or its end cannot be located
    before the next section start (malformed boundaries), or offsets are inconsistent
    (out of order, overlapping), fall back to today's whole-file line-by-line scan for
    the entire file.
  - The existing early-stop (`_needed`/`_completed`) logic is retained in the fallback
    path.
  - A one-line message states which mode was used, so fallbacks are visible in logs.

### 3. Extraction-time disk filtering (`yaspe.py`)

- Extract the CPF disk-role resolution currently embedded in the charting path
  (`mainline`, ~line 3172) into a helper that reads the `overview` table fields
  (`iris disk role Database N`, `Primary Journal`, `Alternate Journal`, `WIJ`). These
  fields are already populated before `create_sections` runs.
- `create_sections` receives the effective disk list chosen as follows:
  1. `--all-disks` flag set → empty list (keep every device; escape hatch for
     investigating non-IRIS disks)
  2. explicit user-supplied disk list → use it (current behaviour)
  3. CPF roles resolve to devices → auto-filter to those, printing
     `Auto disk list from CPF (extraction): [...]`
  4. otherwise (no CPF info) → keep all devices
- The existing charting-time auto-detect remains: it supplies device labels and works
  identically against filtered or unfiltered databases.
- New CLI flag `--all-disks`, documented in `--help` and the README.
- **Behaviour change note:** by default, non-IRIS devices are no longer stored in
  SQLite for Linux files with a parseable CPF. Re-run with `--all-disks` to capture
  everything. This default also flows to the Flask app via the normal engine sync.

### 4. Multi-day column-alignment hardening (`yaspe.py` `create_sections`)

Appending a day whose section gained or lost columns currently raises
`table <t> has no column named <c>` and aborts. Before each `to_sql(if_exists="append")`:

- Read the existing table's columns (`PRAGMA table_info`).
- DataFrame columns absent from the table → `ALTER TABLE ... ADD COLUMN` (type mapped
  from the DataFrame dtype).
- Table columns absent from the DataFrame → left NULL by constructing the insert from
  the DataFrame's own columns (no action needed beyond not failing).
- Table absent entirely → current behaviour (pandas creates it).

## Expected results (reference file)

- ~55 s → roughly 5 s per day file (conversion fix ×~3, disk filter removes ~85% of
  remaining conversions, seeking removes dead scanning).
- SQLite per day ~154 MB → ~10 MB for the default IRIS-focused run.
- Peak memory well under the current 2.7 GB (iostat row dicts drop 18×).

## Testing

- **Golden diff (change 1):** byte-identical `sqlite3 .dump` before/after on the
  reference RHEL day file, run with `--all-disks` once change 3 lands so the
  comparison stays apples-to-apples.
- **Seeking equivalence (change 2):** dump-diff seeking mode vs forced-fallback mode on
  RHEL, RHEL-1-week, and available AIX/Windows samples in `test_samples/`. Truncate a
  copy of a sample mid-iostat and corrupt an end-marker to prove fallback engages and
  matches current-code output.
- **Filtering (change 3):** default run contains only CPF devices; `--all-disks` run
  matches today's device set; explicit `-d` list still wins; file with no CPF info
  keeps all devices.
- **Column alignment (change 4):** append two synthetic days where day 2 adds and
  drops a vmstat column; both appends succeed and NULLs appear where expected.
- **Timing:** record before/after wall time on the reference file in the PR
  description.

## Impact

- No new `.py` modules → `ENGINE_FILES` in `yaspe_flask_v1/sync_engine.sh` unchanged.
- Version bump: minor (new flag, new default behaviour).
