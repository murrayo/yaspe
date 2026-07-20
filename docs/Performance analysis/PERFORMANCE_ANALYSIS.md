# IRIS Performance Analysis — Instructions for Claude Code

You are analyzing time-series performance data collected from a system running an
EHR application on InterSystems IRIS (RHEL 8+). Data was captured with `vmstat`
(OS metrics) and `^mgstat` (IRIS metrics) _typically_ at 5- or 30-second intervals and loaded
into the SQLite database that you know about already. Your job is to produce a **narrative summary** of system
health for the collection window (typically 1 day to 1 week), suitable for a
performance review meeting.

---

## 1. Database orientation (always do this first)

Get the schema. review from the code.

Then establish:
- **Collection interval** (median delta between consecutive timestamps). Note any
  gaps > 3× the interval — these are collection outages and must be called out,
  not interpolated over.
- **Window covered** (start, end, number of days, which weekdays).
- **Host facts if available** (vCPU count, RAM, IRIS global buffer size). If the
  database doesn't contain them, ask the user or state the assumption. vCPU count
  is required to interpret the vmstat run queue (`r`).

## 2. Analysis methodology

Work period-by-period, not whole-window averages. EHR workload is strongly
cyclical; a daily average hides everything. Use these periods (aligned with IRIS
Health Monitor defaults) unless the data suggests better boundaries:

00:15–02:45, 03:00–06:00, 06:15–08:45, 09:00–11:30, 11:45–13:15,
13:30–16:00, 16:15–18:00, 18:15–20:45, 21:00–23:59 — per weekday.

For each metric compute per period: mean, sigma, max, p95, and (for 5-second
data) the longest run of consecutive abnormal samples. Evaluate breaches with
the **consecutive-readings rule**: 3+ consecutive samples over the alert
threshold = alert event; 5+ consecutive over warning = warning event. Single
spikes are noted only if extreme.

For baseline-relative metrics, the alert/warning lines per period are:

```
alert   = max_mult  × MAX(mean + 3σ, highest + σ)        (max_mult default 2)
warning = warn_mult × MAX(base, mean + 2σ, highest)      (warn_mult default 1.6)
```

When only one day of data exists, derive the baseline from comparable quiet
periods within the same day and say so explicitly — confidence is lower.

## 3. KPI thresholds

### vmstat
| Metric | Base | Alert | Warning |
|---|---|---|---|
| r (run queue) | vCPUs | > 2× vCPUs sustained | > 1× vCPUs sustained |
| b (blocked) | 0 | > 10–25% of vCPUs sustained | > 1–2 sustained |
| us+sy (CPU %) | 50 | 85 | 75 |
| sy (% of total CPU) | 10 | > 50% of total in kernel | > 30% of total |
| wa (I/O wait %) | 5 | > 20% sustained | > 10% sustained |
| si/so (swap) | 0 | any sustained so > 0 | any non-zero si/so |
| swpd | 0 | growing during operation | non-zero and rising |
| in / cs | baseline | > 2× period norm | > 1.6× period norm |

On a dedicated IRIS server, **any sustained swapping is an alert** regardless of
other numbers — the shared memory segment must never page.

### mgstat
| Metric | Base | Alert | Warning |
|---|---|---|---|
| Glorefs | baseline/period | > 2× norm, OR sustained drop toward 0 in business hours (stall) | > 1.6× norm |
| Gloupds | baseline | > 2× norm | > 1.6× norm |
| Rdratio | baseline | sustained fall to < ~10% of norm | declining trend |
| PhyRds | ~17/s | > 2× norm sustained | > 1.6× norm |
| PhyWrs | baseline | > 2× norm | > 1.6× norm |
| WDQsz | see note below | growing cycle-over-cycle (not bounded oscillation) | frequently hits GWDQMax (WD wakes early) |
| WD cycle | 80 s | a cycle ≥ cycle time + 10 s | trending toward 80 s |
| Jrnwrts | ~17/s | > 2× norm | > 1.6× norm |
| RouLas | ~0 warm | sustained high (routine buffer undersized) | persistently > 0 |
| ASeize | — | > ~5% of Seizes sustained | > ~2–3% of Seizes |
| BytSnt/BytRcd (ECP) | baseline | > 2× norm | > 1.6× norm |

**WDQsz not reaching zero between write-daemon cycles is normal on a busy
system, not a fault.** Each cycle the write daemon copies a consistent subset
of dirty buffers (WDQ) into a separate write set (WDSECQ), marks them
BDBSTUCK, and spends the rest of the cycle writing only that set. While it
writes, user processes keep dirtying buffers, which land back in WDQ for a
future cycle — if a process needs to modify a buffer already in WDSECQ, it
copies it and returns the copy to WDQ rather than blocking. So WDQ
accumulating continuously is expected on a busy system: a lightly loaded
system may drain to zero between cycles, a normally busy production system
usually will not. Judge the **trend, not the floor** — investigate only if
WDQsz grows cycle over cycle rather than oscillating around a steady level,
if it frequently hits GWDQMax (forcing the WD to wake early instead of
waiting the normal ~80 s), or if elevated WDQsz coincides with rising write
latency. That combination points at the storage subsystem (or occasionally
the update workload) not keeping up — not at WDQsz merely being non-zero.

## 4. Correlation patterns to test (the diagnostic core)

Don't report metrics in isolation. Explicitly test these cross-metric
signatures, joining vmstat and mgstat on timestamp (nearest-sample):

1. **User stall**: Glorefs drops sharply in business hours → check WDQsz,
   vmstat `b`, `wa` at the same timestamps. If they rise together: storage-side
   stall. If they don't: upstream/application-side cause.
2. **Buffer pool pressure**: Rdratio trending down while PhyRds trends up
   across the window → global buffers undersized for working set. Quantify the
   trend (first day vs last day).
3. **Write daemon strain**: WDQsz growing cycle-over-cycle (not merely
   non-zero — see the note above) + rising `wa` + PhyWrs at norm → write path
   (storage/WIJ/journal) latency. Note any WD
   cycle ≥ 90 s individually with timestamp.
4. **Memory danger**: free trending down + cache shrinking + any si/so → flag
   prominently even if no user impact yet.
5. **Contention vs throughput**: Seize rising in proportion to Glorefs is
   normal scaling; ASeize fraction rising is genuine contention.
6. **Kernel overhead**: sy growing relative to us at similar Glorefs → suspect
   huge pages, NUMA, interrupts, or network — not application load.
7. **Batch/backup windows**: identify the overnight PhyWrs/Jrnwrts/bi/bo surge,
   confirm it ends before the morning ramp. Overlap with business hours is a
   finding.

## 5. Output: the narrative summary

Write to `performance_summary_<startdate>_<enddate>.md`. Structure:

1. **Executive summary** (≤ 5 sentences): overall health verdict
   (Green/Yellow/Red in Health Monitor terms), the one or two findings that
   matter, and whether any action is urgent.
2. **Collection overview**: window, interval, gaps, data quality caveats.
3. **Workload profile**: peak periods, peak Glorefs/Gloupds with timestamps,
   day-over-day consistency, the batch window. One short paragraph plus a small
   table of per-period peak values.
4. **Findings** — ordered by severity, each with:
   - what was observed (metric, value, threshold, duration),
   - when (timestamps, recurrence pattern — "every weekday 14:00–14:10"),
   - corroborating metrics (from the correlation tests above),
   - plausible cause(s), clearly labeled as hypothesis vs. confirmed,
   - suggested next step (config change, deeper tool like ^SystemPerformance,
     or "monitor — re-check after baseline matures").
5. **Items that look unusual but are explainable** (e.g., backup window I/O) —
   so reviewers don't rediscover them.
6. **Baseline table**: per-period mean/σ/p95 for the baseline-relative metrics,
   to seed future comparisons.
7. **Appendix**: SQL queries used, so results are reproducible.

Style rules:
- Prose narrative, not bullet spam. Every finding states value, threshold, and
  duration — "wa averaged 18% (warning ≥ 10%) for 22 minutes from 09:42" — never
  vague ("I/O was high").
- Distinguish observation from inference. Never assert a root cause the data
  can't support; offer ranked hypotheses instead.
- No finding without timestamps. No alarmism: a single 5-second spike is not an
  event.
- If the data is healthy, say so plainly and keep the report short.

## 6. Optional chart generation

If asked for charts, use matplotlib (PNG per finding, not per metric):
time-series with the warning/alert lines drawn, abnormal runs shaded, and a
twin-axis overlay for each correlation finding (e.g., Glorefs vs WDQsz).
Reference each chart from the relevant finding in the markdown.
