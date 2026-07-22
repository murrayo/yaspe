# Performance Analysis Engine — Reference for System Architects

This document explains the decisions, methodology, thresholds, and known gaps in
`performance_analysis.py` — the deterministic analysis engine that produces the
`findings`, `baselines`, and `key_metrics` sections of the yaspe LLM context bundle.

Audience: an experienced system architect who wants to understand *why* the engine
makes the judgements it does, not just *what* it outputs.

---

## 1. What the engine produces

`performance_analysis.py` is a library, not a standalone tool. It is called by
`llm_context.py` when `--llm-context` is invoked. It returns structured findings
that are embedded in the bundle for the LLM to reason over.

Three outputs:

- **Baselines** — per-(weekday × IRIS Health Monitor period) statistics for each
  mgstat metric: mean, σ, p95, max. These are the reference values all
  baseline-relative breach detection is anchored to.
- **Findings** — a list of `Finding` objects, each with severity (Red/Yellow/Green),
  a prose observation, timestamps, corroborating evidence, ranked hypotheses, and a
  next step.
- **Key metrics scorecard** — computed separately in `llm_context.py`; the engine
  provides the raw per-period statistics that feed it.

The engine is **Linux-only**. Windows (Perfmon) and AIX (sar) captures do not
go through this code path; the LLM bundle notes this in the "Not available" section.

---

## 2. Period structure

The engine uses the 9 IRIS Health Monitor periods:

| Period name    | Window        |
|----------------|---------------|
| 00:15–02:45    | Overnight quiet |
| 03:00–06:00    | Batch/backup  |
| 06:15–08:45    | Pre-business  |
| 09:00–11:30    | Morning peak  |
| 11:45–13:15    | Midday        |
| 13:30–16:00    | Afternoon peak|
| 16:15–18:00    | Late afternoon|
| 18:15–20:45    | Evening ramp-down |
| 21:00–23:59    | Overnight     |

The 00:00–00:14 gap is intentional — it falls outside all periods and samples in
that window are excluded from baseline computation and breach evaluation. This
mirrors the IRIS Health Monitor's own period definitions.

**Rationale:** EHR workload is strongly cyclical. A whole-window average conceals
the difference between a quiet overnight batch run and a peak clinical period.
Per-period baselines give the LLM a reference that is meaningful for each workload
phase.

---

## 3. Baseline computation

Function: `_compute_baselines(df, metrics)`

For each (weekday, period) combination with ≥ 3 samples, compute:
- `mean` — arithmetic mean of all samples in that cell
- `sigma` — sample standard deviation (ddof=1)
- `p95` — 95th percentile
- `max` — maximum observed value

**Minimum sample threshold:** cells with fewer than 3 samples are skipped and
produce no baseline. This prevents a single-sample baseline from generating
spurious findings on multi-day captures.

**Single-day captures:** when only one day of data exists, the "quiet periods"
(overnight, early morning) serve as the baseline for the same weekday. The engine
does not automatically lower thresholds for this case — the LLM prompt instructs
the LLM to lower its confidence explicitly.

**Weekday fallback:** `_dynamic_thresholds()` first looks up the exact
(weekday, period) key. If no baseline exists for that weekday (e.g. a Monday metric
evaluated against a Sunday baseline), it falls back to any period match regardless
of weekday. This is a pragmatic choice for short captures; it can produce
slightly looser thresholds on weekdays with atypical workload patterns.

---

## 4. Breach detection

### 4.1 Consecutive-readings rule

The engine does **not** fire on a single sample over a threshold. To trigger a finding:

- **Alert (Red):** 3 or more consecutive samples above the alert threshold
- **Warning (Yellow):** 5 or more consecutive samples above the warning threshold

Constants: `ALERT_CONSECUTIVE = 3`, `WARN_CONSECUTIVE = 5`

**Rationale:** at a 5-second collection interval, a single spike lasting one
sample (5 seconds) is noise. Three consecutive alert samples = at least 15 seconds
of sustained pressure. Five consecutive warning samples = 25 seconds. These
numbers were chosen empirically for EHR workloads sampled at 5–30 seconds; they
are not adjustable at runtime (a gap in the design — see §8).

### 4.2 Threshold formula for baseline-relative metrics

```
alert   = max_mult  × MAX(mean + 3σ,   highest + σ)
warning = warn_mult × MAX(base,         mean + 2σ, highest)
```

Defaults: `max_mult = 2.0`, `warn_mult = 1.6`

The `MAX(...)` construct takes the most conservative of three estimates:
- `mean + 3σ` / `mean + 2σ` — statistical upper bound
- `highest + σ` / `highest` — observed peak with some headroom
- `base` (= mean) — floor guard against very low-variance periods producing
  zero-width bands

This prevents a period where the metric is near-zero from generating a threshold
of "alert if > 0.001" while also handling high-variance periods reasonably.

### 4.3 Fixed thresholds (vmstat)

vmstat metrics use fixed thresholds from PERFORMANCE_ANALYSIS.md §3, not
baseline-relative computation. The rationale is that OS-level metrics (CPU %,
I/O wait, swap) have industry-standard reference values that are meaningful
independent of site history.

| Metric | Warning | Alert |
|--------|---------|-------|
| us+sy  | 75%     | 85%   |
| wa     | 10%     | 20%   |
| sy (% of total) | 30% | 50% |
| r (run queue) | 1× vCPUs | 2× vCPUs |
| b (blocked) | max(2, 10% of vCPUs) | max(10, 25% of vCPUs) |
| si / so | any non-zero | any sustained > 0 |
| st (steal) | 5% | 15% |

Run queue and blocked processes are vCPU-relative. If vCPU count is not available
in `sp_dict`, those two checks are skipped entirely and the missing-data note is
propagated to the LLM bundle.

---

## 5. Per-metric decisions

### 5.1 wa (I/O wait)

wa is a necessary but not sufficient signal for storage latency. The engine always
adds a caveat: *"iostat device latency is required to confirm storage-side cause."*

**Why:** wa measures the fraction of time the CPU was idle waiting for I/O. It is
elevated by storage latency but also by high I/O volume on fast storage. It does
not tell you which device, which direction (read vs write), or what the actual
latency was. The engine treats wa as a trigger for further investigation, not a
confirmed finding.

### 5.2 WDQsz

WDQsz has **no fixed threshold** in `METRIC_THRESHOLDS`. The entry exists only so
callers can test membership. All WDQsz logic is in `_analyse_mgstat` and
`_test_write_daemon_strain`.

The engine fires on WDQsz only when one of two conditions holds:
1. **Growing trend:** mean of last-third of non-zero samples > 1.5× mean of
   first-third, and the absolute difference > 100 (to avoid firing on tiny queues)
2. **Persistently elevated:** mean > 3× p25 of non-zero samples (skewed
   distribution indicates a heavy tail, not a steady oscillation)

**Why not "non-zero = alert":** WDQ accumulates continuously while the write daemon
is writing its current set (WDSECQ). On a busy system it is never zero between
cycles. A finding requires evidence that the queue is growing or not draining, not
merely that it exists.

The correlation test `_test_write_daemon_strain` additionally requires concurrent
`wa ≥ 10%`. Without the wa corroboration, a growing WDQsz alone is reported only
as a standalone finding from `_analyse_mgstat`.

### 5.3 Rdratio

Rdratio is marked `"invert": True` in `METRIC_THRESHOLDS`. For most metrics a
breach is a high value; for Rdratio (cache hit ratio) a breach is a declining
value. The baseline-relative formula still applies, but the alert fires when the
value falls **below** the lower bound rather than above the upper bound.

The engine does not currently implement invert logic in `_analyse_mgstat` —
Rdratio breach detection is handled only through the correlation test
`_test_buffer_pressure` (Rdratio down + PhyRds up). This is a known gap (see §8).

### 5.4 RouLaS

The engine only evaluates RouLaS during business hours (08:00–18:00). Overnight
non-zero values are expected during startup, batch, or backup activity and are not
a sizing signal. The business-hours filter is hard-coded.

### 5.5 ASeize / Seize (lock contention)

Two separate checks:

1. **In `_analyse_mgstat`:** rolling 10-sample p95 of ASeize/Glorefs > 1%.
   This catches short bursts of lock pressure.
2. **In `_test_contention_vs_throughput`:** ASeize fraction (ASeize/Seize)
   trending upward across the window. This catches a gradual deterioration.

The threshold of 1% of Glorefs (check 1) and 5% of Seizes (check 2) are empirical.
Seize and ASeize are not present in all pButtons captures; both checks skip silently
if the columns are absent.

### 5.6 st (CPU steal time)

Steal time is evaluated only when the `st` column is present in the vmstat data.
Warning at 5%, alert at 15%. These are thresholds from VMware and AWS operational
guidance for latency-sensitive workloads.

The engine explicitly notes in the finding text that steal-induced latency is
unrelated to IRIS workload — this is important context for the LLM when it
correlates with wa or r findings.

### 5.7 b (blocked processes)

Alert threshold is `max(10, 25% of vCPUs)`. This floor of 10 prevents the alert
from firing on a 2-vCPU system every time a single process blocks. The floor is
arbitrary and may be too high for small VMs (see §8).

---

## 6. Correlation tests

The seven cross-signal tests are the diagnostic core of the engine. Each test joins
mgstat and vmstat on nearest timestamp (within 1.5× the median collection interval)
before evaluating.

| Test | Signal | Corroborating signal | Finding |
|------|--------|----------------------|---------|
| User stall | Glorefs < 5% of mean in business hours | wa > 10%, WDQsz > 0 | Red — storage-side or application stall |
| Buffer pressure | Rdratio −15% trend | PhyRds +20% trend | Yellow — buffers undersized |
| Write daemon strain | WDQsz growing (last > 1.5× first) | wa ≥ warn threshold | Yellow — write path latency |
| Memory danger | free −20% trend | any si or so > 0 | Red if swap active, else Yellow |
| Contention vs throughput | ASeize/Seize fraction +50% trend | ASeize fraction > 5% | Yellow — genuine contention |
| Kernel overhead | sy/us fraction +50% trend | Glorefs stable (< 20% change) | Yellow — HugePages/NUMA/IRQ |
| Batch window | overnight PhyWrs > 2× overall mean | morning overlap | Green (normal) or Yellow (overlap) |

**Test 1 (user stall):** fires only in business hours (08:00–18:00). The stall
threshold is 5% of the business-hours mean Glorefs. This is a very conservative
threshold — a drop to 5% is unmistakable. A 20% dip (which could still be
significant) is not caught by this test.

**Test 7 (batch window):** uniquely can produce a Green finding. This is intentional —
it is useful for the LLM to know the batch window was identified and is *not* a
concern, rather than leaving the overnight write surge unexplained.

---

## 7. Finding structure

Each `Finding` dataclass contains:

| Field | Content |
|-------|---------|
| `metric` | Human-readable metric name |
| `severity` | "Red", "Yellow", or "Green" |
| `observation` | Prose: value, threshold, duration, sample count |
| `when` | Timestamps or recurrence pattern |
| `corroborating` | List of supporting evidence strings |
| `hypotheses` | Ranked, labelled "hypothesis:" or "confirmed:" |
| `next_step` | One concrete action |

The `hypotheses` field uses an explicit prefix convention: findings where the
evidence is conclusive say `"confirmed: ..."`, uncertain ones say
`"hypothesis: ..."`. This is consumed as-is by the LLM prompt, which instructs
the LLM to keep observation and inference separated in the narrative.

---

## 8. Known gaps and future work

### Not yet implemented

| Gap | Impact | Notes |
|-----|--------|-------|
| **Rdratio direct breach detection** | Declining Rdratio is only caught by the buffer-pressure correlation test. A monotonic decline with no PhyRds change (e.g. working set growing slowly) will be missed. | Add invert logic to `_analyse_mgstat` for `invert=True` metrics. |
| **WD cycle time** | `WDcycle` (time between write daemon wakes) is in the PERFORMANCE_ANALYSIS.md spec but not in the engine. A WD cycle ≥ 90 s is a critical signal. | Column not always present; add when available and document absence. |
| **Interrupt / context-switch baseline** (vmstat `in` / `cs`) | Spec includes these as baseline-relative metrics; engine ignores them. High cs can indicate lock contention before ASeize is visible. | Add to `METRIC_THRESHOLDS` and `_analyse_vmstat`. |
| **swpd (total swap used)** | Engine checks si/so rates but not swpd level. A system that swapped overnight and never recovered is missed. | Add a growing-swpd check to `_analyse_vmstat`. |
| **ECP metrics** (BytSnt/BytRcd) | Spec lists ECP as baseline-relative; engine ignores them. Relevant for multi-server configurations. | Low priority unless ECP use is confirmed in the capture. |
| **Configurable thresholds** | All consecutive-readings constants and multipliers are hard-coded. A 30-second interval capture should use different consecutive counts (3× 30s = 90s is a long event) than a 5-second capture. | Make `ALERT_CONSECUTIVE` and `WARN_CONSECUTIVE` interval-aware. |
| **Windows / AIX paths** | Engine is Linux-only. Perfmon and sar data goes through `llm_context.py` without deterministic breach detection. | Requires separate metric maps; medium effort. |
| **Glorefs stall sensitivity** | Stall threshold is 5% of business-hours mean. A 20–30% drop (significant but not catastrophic) is not caught. | Consider adding a Yellow-severity partial-stall check. |
| **b (blocked) floor** | `max(10, 25% of vCPUs)` is too high for small VMs (2–4 vCPU). A 2-vCPU VM would need 10 blocked processes before alerting, which is extreme. | Make the floor a function of vCPU count with a lower bound of 1–2. |
| **Iostat breach detection** | iostat data (r_await, w_await, aqu-sz, %util) is included in the LLM bundle as timeseries but has no deterministic breach detection in the engine. The LLM is expected to reason over it raw. | Add `_analyse_iostat()` with per-device await thresholds. |
| **Period statistics export** | The engine computes baselines internally but the full per-period statistics table (mean/σ/p90/p95/max/n_samples for every metric) is computed separately in `llm_context.py`. These two paths are not unified. | Refactor to use a single computation. |
| **Multi-instance captures** | Engine assumes a single IRIS instance. Multi-instance pButtons captures are not distinguished. | Out of scope until the compare-overlay work is complete. |

### Design constraints to preserve

- **No thresholds in the output text.** The engine embeds thresholds in finding
  prose. Do not move them to the LLM prompt only — they need to be in the finding
  text for the LLM to cite them accurately.
- **Findings are hints, not conclusions.** The LLM prompt explicitly instructs the
  LLM not to restate findings verbatim. The engine's job is to reduce search space,
  not replace analysis.
- **Green findings are intentional.** "All vmstat metrics within normal thresholds"
  is a valid output. It tells the LLM the engine ran cleanly and found nothing —
  absence of evidence is information.
