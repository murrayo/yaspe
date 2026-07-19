# LLM-Context-First: drop `--analysis`, anonymize, scorecard — Design

**Date:** 2026-07-20
**Branch:** `feature/llm-context-anonymize`
**Status:** Approved design, pending implementation plan

## Goal

Make `--llm-context` the single analysis-oriented output of yaspe. Remove the
`--analysis` markdown report (never advertised, no users). The exported context
must be safe to paste into a public LLM: no customer-identifying information.
Ship a companion prompt file that teaches the LLM the analysis methodology, and
add the analyst-approved key-metrics scorecard so the LLM's output is
review-meeting-ready.

The data file is a **markdown bundle**, not JSON: JSON repeats every key on
every timeseries row (~150 tokens/record vs ~50 for CSV), and a week of 5-min
records as JSON (~320k tokens) would not fit typical chat context windows.
Markdown with fenced CSV blocks is ~3× leaner, reads better for LLMs, and is
human-eyeballable before sharing — which directly serves the anonymization
goal.

Division of labour: **yaspe does the deterministic work** (parse, resample,
percentiles, ratios, breach detection); **the LLM does the judgment work**
(correlate, narrate, hypothesize, recommend).

## CLI changes

- **Remove `--analysis`.** Anyone passing it gets a normal argparse error.
- **Keep `--llm-context`** (unchanged trigger conditions: any mode with a
  SQLite DB, not `.mgst` input).
- **Keep `--context "free text"`** — help text reworded to reference the LLM
  context file. The note is included in the bundle and passes through the scrub.
- **`--resample` default becomes adaptive.** With no explicit value, the
  interval scales with the collection window so multi-day bundles stay inside
  chat context windows: ≤2 days → `5min`, 3–4 days → `15min`, ≥5 days →
  `30min` (argparse default `None` = auto). An explicit `--resample` always
  wins. Multi-day databases are fully supported — `period_stats`, baselines,
  and peak-period selection are already weekday-aware and do not grow with
  window length; only the timeseries CSV does, which this addresses. The
  bundle's timeseries caption states the chosen interval, and precise
  statistics come from full-resolution `period_stats`, so a coarser timeseries
  on long windows loses shape fidelity only.

`--llm-context` now writes **two files** to the output directory:

| File | Content |
|---|---|
| `{prefix}performance_context_{start}_{end}.md` | Anonymized markdown data bundle, `schema_version: 2.0` in its YAML header |
| `{prefix}llm_analysis_prompt.md` | Companion prompt, identical every run |

Console output prints both paths.

## `performance_analysis.py` → analysis library

Delete (report-only machinery):

- `run_analysis()`
- `_write_report()`
- `_attach_chart_requests()` and the `chart_request` field on `Finding`
- any helper used only by the above (e.g. `_fmt_n` if unreferenced after)

Keep (the engine, consumed by `llm_context.py`):

- `_get_collection_meta`, `_get_system_facts`, `_label_period`
- `_compute_baselines`, `_find_breaches`
- `_analyse_vmstat`, `_analyse_mgstat`, `_nearest_join`
- all 7 correlation tests (`_test_user_stall` … `_test_batch_window`)

`sync_engine.sh` is unchanged — the module keeps its name and stays in
`ENGINE_FILES`. `_serialise_finding` in `llm_context.py` no longer needs to
drop `chart_request` (field removed at source).

In `yaspe.py`: remove the `--analysis` call block; the `--llm-context` block
stays (it opens its own connection and rebuilds `sp_dict` from the overview
table when needed).

## Context bundle format (schema 2.0)

Internally `build_llm_context()` still assembles a plain dict (testable,
scrubbable); a new `_render_markdown(ctx) -> str` renders it to the bundle.
Document structure:

```
---  (YAML header)
schema_version: "2.0"
generated_by: yaspe --llm-context
context: <user note or omitted>          (scrubbed)
system:  vcpus, ram_gb, iris_buffers_gb, version, os   ← customer REMOVED
collection: start, end, n_days, weekdays, interval_seconds, gaps
---
## Baselines            per-period mgstat baselines, markdown table
## Findings             pre-computed hints, one bullet group per finding
## Key metrics          analyst scorecard, markdown table (NEW)
## Not available        metrics this dataset cannot provide, table (NEW)
## Period statistics    fenced CSV block (NEW)
## Timeseries           fenced CSV blocks: one merged mgstat+vmstat block,
                        one per iostat IRIS-role device
```

Rendering rules:

- **Floats rounded**: percentages/response-times to 1 decimal, ratios to 2,
  large rates to integers. Never emit full float repr.
- CSV blocks: header row once; missing values are empty cells (no `null`).
- Each CSV block is preceded by a one-line caption stating units and
  aggregation (mean vs `_max`, resample interval).

### `period_stats` (new)

For each weekday × Health-Monitor period (00:15–02:45, 03:00–06:00,
06:15–08:45, 09:00–11:30, 11:45–13:15, 13:30–16:00, 16:15–18:00, 18:15–20:45,
21:00–23:59 — reuse `_label_period`), per metric:
`{mean, sigma, p90, p95, max, n_samples}`.

Metrics covered:

- mgstat: `Glorefs`, `Gloupds`, `PhyRds`, `PhyWrs`, `Jrnwrts`, `Rdratio`,
  `WDQsz`, plus `PPGupds` when present
- vmstat: `r`, `b`, `us_sy` (derived us+sy), `sy`, `wa`, `si`, `so`

Computed from **full-resolution** data (not the resampled series). Structure:

```
"period_stats": [
  {"weekday": "Tuesday", "period": "09:00-11:30",
   "metrics": {"Glorefs": {"mean":…, "sigma":…, "p90":…, "p95":…, "max":…, "n_samples":…}, …}},
  …
]
```

Periods with no samples are omitted.

### `key_metrics` (new)

The analyst's headline scorecard. Each entry:
`{"metric": …, "value": … | {"mean":…, "p90":…, "p95":…, "max":…}, "basis": "how it was computed", "caveat": optional}`.

Two views: `"overall"` (whole window) and `"peak_period"` (the weekday×period
with the highest mean Glorefs, identified in the output).

Rules:

- **Ratios are computed from sums**, never mean-of-ratios
  (e.g. physical R/W ratio = Σ PhyRds ÷ Σ PhyWrs).
- **Rates get a distribution** (`mean`, `p90`, `p95`, `max`).
- Conditional entries appear only when their source columns/devices exist;
  otherwise they move to `not_available`.

| Key metric | Formula / source |
|---|---|
| `max_memory_utilization_pct` | max over samples of `(ram_kb − (free+buff+cache)) / ram_kb × 100`; needs `ram_gb`; caveat: includes page cache as reclaimable |
| `cpu_utilization` | distribution of vmstat `us+sy` (the p95 is the analyst's headline number) |
| `db_disk_reads_per_sec` | iostat `r/s`, Database-role device, distribution |
| `db_disk_read_response_ms` | iostat `r_await`, Database-role device, distribution |
| `db_disk_writes_per_sec` | iostat `w/s`, Database-role device, distribution |
| `db_disk_write_response_ms` | iostat `w_await`, Database-role device, distribution |
| `db_disk_read_write_ratio` | Σ `r/s` ÷ Σ `w/s` on Database-role device |
| `physical_read_write_ratio` | Σ `PhyRds` ÷ Σ `PhyWrs` |
| `glorefs_distribution` | distribution of `Glorefs` (p90 is the analyst's number) |
| `global_update_rate` | distribution of `Gloupds` |
| `ppg_update_rate` | distribution of `PPGupds` — conditional on column |
| `ppg_to_global_update_ratio` | Σ `PPGupds` ÷ Σ `Gloupds` — conditional |
| `global_cache_hit_ratio_pct` | ≈ `(1 − 1/Rdratio) × 100` from Σ-based Rdratio; caveat: block-level approximation |
| `glorefs_per_core` | `Glorefs` distribution ÷ `vcpus` — capacity benchmark |
| `ppg_to_iristemp_writes_ratio` | Σ `PPGupds` ÷ Σ iostat `w/s` on IRIS-role device — conditional on both; caveat: IRIS-role device carries more than IRISTEMP |

Multi-device roles (e.g. several Database disks): sum rates across the role's
devices; response times take the worst (max) device distribution, with the
basis string saying so.

### `not_available` (new)

A list of `{"metric": …, "reason": …, "how_to_collect": …}` naming what the
dataset cannot provide. Static candidates, filtered by what the data actually
contains (e.g. PPG entries appear here only when `PPGupds` is absent):

- transaction rate, global updates/transaction, ECP synch rate → journal file
  analysis (not in SystemPerformance)
- global kill rate, bitsets rate, bitsets/update ratio → `^GLOSTAT` collection
  (mgstat `Gloupds` merges sets and kills)
- max IRIS/user processes, average memory per IRIS process → not captured as
  timeseries
- routine buffer statistics → `irisstat -R` (not in standard profiles)
- PPG metrics → mgstat from this IRIS version lacks `PPGupds` (conditional)

## Anonymization

`_scrub(obj, secrets)` — final pass over the fully-built context dict, before
markdown rendering:

- **Secrets** gathered from `sp_dict`: `customer`, `linux hostname`,
  `instance`, all `up instance N` values. Each secret also contributes its
  short hostname (portion before the first `.`) when it is an FQDN.
- Recursively walks dicts/lists/strings; replaces case-insensitive,
  word-boundary matches of each secret with `[redacted]`.
- **Guard rails**: secrets shorter than 4 characters or whose upper-case form
  is in an allowlist (`{"IRIS", "LINUX", "TEST", "PROD", "DEV", "LIVE"}`) are
  skipped — an instance literally named "IRIS" must not shred the output.
- Best-effort: any exception inside scrub is swallowed and the unscrubbed value
  passes through for that node — the export never fails because of scrubbing.
- `system.customer` is removed at the source (`llm_context` builds `system`
  without it) — scrub is belt-and-braces, not the primary mechanism.

Known limitation (documented in the prompt file): the scrub only knows
identifiers captured in `sp_dict`. A customer name embedded in, say, a device
label would survive. The prompt carries a one-line reminder to eyeball the bundle
before sharing externally.

## Companion prompt (`{prefix}llm_analysis_prompt.md`)

Lives as a module-level string constant `PROMPT_TEMPLATE` in `llm_context.py`
(so the Flask `sync_engine.sh`, which copies `.py` files only, ships it for
free). Written once per export, identical content every run. Derived from
`docs/Performance analysis/PERFORMANCE_ANALYSIS.md` and
`IRIS_EHR_KPI_Reference.md`, rewritten for the bundle-attachment workflow. Content outline:

1. **What you are looking at** — anonymized performance capture from an
   IRIS/EHR system; the reviewer holds the identity; document walk-through
   (YAML header, every section, aggregation caveats: mean vs `_max` columns, resample
   interval, ratios-from-sums).
2. **Method** — period-by-period, never whole-window averages;
   consecutive-readings rule (3+ over alert = event, 5+ over warning);
   baseline formulas (`alert = 2 × MAX(mean+3σ, highest+σ)`,
   `warning = 1.6 × MAX(base, mean+2σ, highest)`); single-day-baseline caveat;
   collection gaps are outages, never interpolate.
3. **KPI threshold tables** — vmstat, mgstat, iostat (from the KPI reference).
4. **Key metrics scorecard** — what each `key_metrics` entry means, healthy
   ranges where they exist, and that these are the headline numbers an
   experienced IRIS analyst leads with.
5. **Findings** — the `findings` array is deterministic pre-computation:
   verify each against the data, extend, correlate across findings; do not
   parrot.
6. **Required output shape** — narrative system-health summary suitable for a
   performance review meeting: executive summary, per-period narrative,
   scorecard commentary, explicit **data limitations** section, and a
   **data to request** list seeded from `not_available`.
7. **Sharing reminder** — data is anonymized by yaspe but eyeball before
   sharing; ask the user for context (`context` field may already carry it).

## Testing

- `tests/test_llm_context.py`:
  - `period_stats`: correct period bucketing via `_label_period`, p90/p95
    present, empty periods omitted
  - `key_metrics`: ratio-from-sums correctness, conditional entries
    (present/absent `PPGupds`), peak-period selection
  - `not_available`: PPG listed when column missing, absent when present
  - `_scrub`: redacts hostname/customer in nested structures, case-insensitive,
    word-boundary (no partial-word mangling), skips short and allowlisted
    secrets, never raises
  - `system` has no `customer` key; schema_version is `"2.0"`
  - prompt file written alongside the bundle; contains schema and thresholds markers
  - renderer: CSV blocks round-trip through pandas.read_csv; floats rounded per
    rule; YAML header parses and carries schema_version 2.0
- `tests/test_performance_analysis.py`: remove report-writer /
  chart-request tests; engine tests unchanged and green.
- Full suite passes; smoke test against a real SQLite.

## Docs

- README: remove `--analysis` documentation; add the LLM workflow section
  (run `--llm-context`, attach both files to a chat LLM).
- `docs/Performance analysis/` stays as the human-readable methodology source;
  `PROMPT_TEMPLATE` notes it derives from there.

## Out of scope (future work)

- Parsing `^GLOSTAT`, `irisstat` snapshots, or journal profiles to close the
  `not_available` gaps.
- Windows/AIX support for llm-context (stays Linux-scoped like Part A).
- Any change to `sync_engine.sh` (not needed).

## Version

Breaking CLI change (flag removal) but the flag was never advertised:
`bump2version minor` at release time.
