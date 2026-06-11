# Performance Analysis Module — Design Spec

**Date:** 2026-06-11
**Branch:** feature/performance-analysis
**Status:** Approved

---

## 1. Summary

Add `--analysis` flag to `yaspe.py` that produces a narrative performance summary markdown file from an existing SQLite database. The analysis follows the methodology in `docs/Performance analysis/PERFORMANCE_ANALYSIS.md`. It is Linux-only. Charts are generated only for Yellow/Red findings.

---

## 2. New file: `performance_analysis.py`

Single public entry point:

```python
def run_analysis(connection, sp_dict, output_prefix, filepath, context=None, png_out=False) -> str:
    """
    Run full performance analysis against the SQLite database.
    Returns path to the written markdown file.
    """
```

Internal structure:

```
performance_analysis.py
├── Constants
│   ├── IRIS_PERIODS          # 9 time periods per PERFORMANCE_ANALYSIS.md §2
│   └── METRIC_THRESHOLDS     # KPI thresholds per §3 (vmstat + mgstat tables)
├── Data classes
│   ├── Finding               # metric, severity, observation, when, corroborating,
│   │                         # hypotheses, next_step, chart_request
│   └── ChartRequest          # metric, df, threshold lines, shading spans, twin_axis
├── Database orientation
│   ├── _get_collection_meta()   # interval, gaps, window start/end, weekdays
│   └── _get_system_facts()      # resolve vCPUs, RAM, buffers from sp_dict
├── Per-metric analysis
│   ├── _analyse_vmstat()        # evaluate all vmstat KPIs, return list[Finding]
│   └── _analyse_mgstat()        # evaluate all mgstat KPIs, return list[Finding]
├── Correlation tests (§4)
│   ├── _test_user_stall()
│   ├── _test_buffer_pressure()
│   ├── _test_write_daemon_strain()
│   ├── _test_memory_danger()
│   ├── _test_contention_vs_throughput()
│   ├── _test_kernel_overhead()
│   └── _test_batch_window()
├── Baseline computation
│   └── _compute_baselines()     # per-period mean/σ/p95 for baseline-relative metrics
└── Report writer
    └── _write_report()          # assembles 7-section markdown
```

No circular imports: `performance_analysis.py` does not import from `yaspe.py`. Chart rendering is handled by `yaspe.py` after `run_analysis()` returns.

---

## 3. Changes to `yaspe.py`

### CLI

```
--analysis      Run performance analysis (implies -s). Optional --context string.
--context STR   Free-text context note appended to report header
                (default: "Routine health check — no specific context provided.")
```

### Logic

```python
if args.analysis:
    args.system_out = True   # force -s

# After system_check() returns sp_dict:
if args.analysis:
    import performance_analysis
    chart_requests = performance_analysis.run_analysis(
        connection, sp_dict, output_filepath_prefix, filepath,
        context=args.context, png_out=args.png_out
    )
    # Render charts for Yellow/Red findings
    for cr in chart_requests:
        _render_analysis_chart(cr, ...)
```

`_render_analysis_chart()` is a small private function in `yaspe.py` that calls existing `simple_chart()` helpers with threshold overlays.

---

## 4. System facts from `sp_dict`

| Fact | `sp_dict` key(s) to try | Fallback |
|---|---|---|
| vCPU count | `"logical processors"`, `"cpu count"` | Note assumption in report |
| RAM (GB) | `"total memory"` | Note assumption |
| IRIS global buffers (GB) | `"globals"` (CPF value) | Note assumption |
| Customer / hostname | `"customer"` | "Unknown" |
| IRIS version | `"version string"` | Omitted |
| OS | `"operating system"` | Linux assumed |

Scope is Linux only. Windows/AIX paths in `sp_check.py` are not used by this module.

---

## 5. Threshold evaluation

### Consecutive-readings rule

- **Red (Alert):** 3+ consecutive samples above the alert threshold
- **Yellow (Warning):** 5+ consecutive samples above the warning threshold
- Single extreme spikes noted in prose only — no severity escalation

### Alert / warning formulas for baseline-relative metrics

```
alert   = max_mult  × MAX(mean + 3σ, highest + σ)   # max_mult  default 2.0
warning = warn_mult × MAX(base, mean + 2σ, highest)  # warn_mult default 1.6
```

When only one day of data exists, baselines are derived from comparable quiet periods within the same day. Confidence is noted as lower in the report.

### Fixed thresholds (vmstat)

| Metric | Warning | Alert |
|---|---|---|
| us+sy | ≥ 75% | ≥ 85% |
| wa | ≥ 10% sustained | ≥ 20% sustained |
| r (run queue) | > 1× vCPUs sustained | > 2× vCPUs sustained |
| b (blocked) | > 1–2 sustained | > 10–25% of vCPUs sustained |
| sy (% of total CPU) | > 30% | > 50% |
| si/so (swap) | any non-zero | any sustained so > 0 |

Any sustained swapping = Red regardless of other numbers.

---

## 6. Correlation tests

Seven cross-metric tests, each returning `Finding | None`:

1. **User stall** — Glorefs drops in business hours → check WDQsz, vmstat `b`, `wa`
2. **Buffer pool pressure** — Rdratio trending down + PhyRds trending up across window
3. **Write daemon strain** — WDQsz non-zero between cycles + rising `wa` + PhyWrs at norm
4. **Memory danger** — free trending down + cache shrinking + any si/so
5. **Contention vs throughput** — ASeize fraction rising relative to Seizes
6. **Kernel overhead** — sy growing relative to us at similar Glorefs
7. **Batch/backup window** — overnight PhyWrs/Jrnwrts surge; confirm ends before morning ramp

vmstat and mgstat are joined on nearest-sample timestamp with tolerance = 1.5× collection interval.

---

## 7. Output

### Markdown file

**Path:** `{filepath}/performance_summary_{startdate}_{enddate}.md`

**Sections:**
1. Executive summary (≤ 5 sentences): overall verdict (Green/Yellow/Red), top 1-2 findings, urgency
2. Collection overview: window, interval, gaps, data quality caveats
3. Workload profile: peak periods table (per-period peak Glorefs/Gloupds), day-over-day consistency, batch window
4. Findings: one subsection per finding, Red → Yellow order, prose narrative (value + threshold + duration + timestamps), corroborating metrics, ranked hypotheses, next step
5. Explainable anomalies: backup window I/O and other expected patterns
6. Baseline table: per-period mean/σ/p95 for baseline-relative metrics
7. Appendix: SQL queries used

Style: prose narrative, not bullet spam. Every finding states value + threshold + duration. No finding without timestamps.

### Charts

- **Only for Yellow/Red findings**, PNG only (matplotlib), written to `{output_prefix}analysis_metrics/`
- Each chart: time-series with warning/alert threshold lines, abnormal run shading
- Correlation findings: twin-axis overlay (e.g. Glorefs vs WDQsz on right axis)
- Charts referenced inline in their finding section
- If all Green: no charts generated, report is short

### Interaction with existing `-p` / `-P` flags

Analysis charts always use matplotlib regardless of the PNG/HTML flag on the main pipeline.

---

## 8. `sync_engine.sh` update

Add `performance_analysis.py` to `ENGINE_FILES` in `yaspe_flask_v1/sync_engine.sh`.

---

## 9. Dependencies

No new packages. All imports (`sqlite3`, `pandas`, `numpy`, `datetime`, `pathlib`, `dataclasses`) are already present in `requirements.txt` or the Python standard library.

---

## 10. Out of scope

- Windows and AIX analysis
- Interactive HTML report output
- YAML config file for system facts (facts come from SQLite / sp_dict)
- Modifying `-s` flag behaviour
