# Key Performance Indicators — EHR Applications on InterSystems IRIS (RHEL 8+)

**Collection tools:** `vmstat` (OS) and InterSystems IRIS `^mgstat`
**Collection cadence:** 5 or 30 second intervals over 24 hours; extended runs (e.g., one week) to capture a full business cycle.

**Threshold philosophy** (mirrors IRIS Health Monitor): use **absolute thresholds** where a hard limit makes sense, and **baseline multipliers** (warning ≈ 1.6× period norm, alert/max ≈ 2× period norm) where the "right" value is workload-dependent (e.g., Glorefs). **Base** is the minimum value worth evaluating — samples below it are treated as noise, consistent with Health Monitor sensor objects.

---

## vmstat — OS-level KPIs (RHEL 8+)

| Metric | Description | Base | Max (Alert) | Warning |
|---|---|---|---|---|
| `r` | Run queue — processes waiting for CPU | # of vCPUs | > 2× vCPUs sustained (3+ consecutive readings) | > 1× vCPUs sustained |
| `b` | Processes in uninterruptible sleep (blocked on I/O) | 0 | > 10–25% of vCPUs sustained | > 1–2 sustained |
| `us + sy` | Total CPU utilization % | 50% | 85% | 75% |
| `sy` | System (kernel) CPU % | 10% | > 50% of total CPU consumed in system mode | > 30% of total |
| `wa` | I/O wait % | 5% | > 20% sustained | > 10% sustained |
| `si` / `so` | Swap-in / swap-out (KB/s) | 0 | Any sustained `so` > 0 | Any non-zero `si`/`so` |
| `swpd` | Swap space in use | 0 | Growing during operation | Non-zero and rising |
| `free` + `cache` | Available memory headroom | Site baseline | Physical memory > 96% used *and* paging active | Approaching commit of huge pages + buffers |
| `in` / `cs` | Interrupts / context switches per sec | Site baseline | > 2× period norm | > 1.6× period norm |

**Notes:**
- The 50/75/85 CPU thresholds mirror Health Monitor's `CPUUsage` sensor.
- On a dedicated IRIS database server, **any sustained swapping is effectively an alert condition** regardless of other numbers — the shared memory segment (global buffers) must never page.
- High `sy` relative to `us` usually points at I/O, networking, or huge-page misconfiguration rather than application load.

---

## mgstat — IRIS-level KPIs

| Metric | Description | Base | Max (Alert) | Warning |
|---|---|---|---|---|
| `Glorefs` | Global references/sec — primary workload/throughput indicator | Site baseline per period | No absolute max — > 2× period norm (or sustained drop to ~0 during business hours, which signals a stall) | > 1.6× period norm |
| `Gloupds` | Global updates (sets/kills)/sec | Site baseline | > 2× period norm | > 1.6× period norm |
| `Rdratio` | Ratio of logical block reads to physical reads — cache effectiveness | Site baseline (higher is better) | Sustained fall to < ~10% of normal ratio | Declining trend vs. baseline period |
| `PhyRds` | Physical (disk) block reads/sec | 1024/min ≈ ~17/s | > 2× period norm sustained | > 1.6× period norm |
| `PhyWrs` | Physical block writes/sec | Site baseline | > 2× period norm | > 1.6× period norm |
| `WDQsz` | Write daemon queue size | See note below | Queue growing across multiple consecutive WD cycles | Frequently hits GWDQMax (WD wakes early instead of the normal ~80 s) |
| `WDphase` / WD cycle | Write daemon cycle behavior | 80 s cycle | Single cycle ≥ ~90 s (cycle time + 10 s, per System Monitor rule) | Cycle time trending toward 80 s |
| `Jrnwrts` | Journal writes/sec | 1024/min ≈ ~17/s | > 2× period norm | > 1.6× period norm |
| `RouLas` | Routine loads/saves per sec | ~0 after warm-up | Sustained high values (routine buffer undersized) | Persistently > 0 in steady state |
| `Seize` / `ASeize` | Global seizes and async seizes/sec — resource contention | Site baseline | ASeize > ~5% of Seizes sustained | ASeize > ~2–3% of Seizes, or Seizes > 1.6× norm |
| `BytSnt` / `BytRcd` | ECP bytes sent/received per sec (if ECP in use) | Site baseline | > 2× period norm | > 1.6× period norm |

**Notes:**
- **WDQsz not reaching zero between write-daemon cycles is normal on a busy
  system, not a fault.** Each cycle the write daemon copies a consistent
  subset of dirty buffers (WDQ) into a separate write set (WDSECQ) and spends
  the cycle writing only that set; buffers modified while the WD is writing
  return to WDQ for a future cycle. New dirty buffers therefore accumulate in
  WDQ continuously while the system is busy — a lightly loaded system may
  drain to zero between cycles, a normally busy production system usually
  will not. Judge the trend, not the floor: investigate only if WDQsz grows
  cycle over cycle rather than oscillating around a steady level, if it
  frequently hits GWDQMax (forcing the WD to wake early), or if elevated
  WDQsz coincides with rising write latency.

---

## Establishing "norm" for baseline-relative metrics

This is where the 5-second and longer collections work together, mirroring the Health Monitor chart approach:

1. **Segment by period.** EHR workloads are strongly cyclical — morning clinic ramp-up, mid-morning peak, batch/backup overnight, end-of-month billing. Use week-long runs to define periods (Health Monitor's default is nine periods per day, per weekday), then compute statistics per period rather than one global average.
2. **Compute mean + sigma per period.** A practical alert line for a multiplier-based metric is:

   `alert = multiplier × max( mean + 3σ , highest_observed + 1σ )`
   `warning = multiplier × max( base , mean + 2σ , highest_observed )`

   — the same formulas Health Monitor uses to build its charts. Use 30-second data for baseline statistics and 5-second data to characterize true peaks and short stalls (a 5-second Glorefs flatline is invisible at 30-second resolution).
3. **Require consecutive breaches.** Don't alert on single samples. Health Monitor's rule of 3 consecutive readings over the alert threshold / 5 consecutive over the warning threshold translates well to mgstat data and suppresses transient spikes.
4. **Recalibrate deliberately.** As user counts grow, Glorefs/Gloupds norms rise legitimately. Re-baseline on a schedule (or after go-lives/upgrades), and never baseline during a holiday, incident, or atypical week.

## EHR-specific diagnostic signatures

- A **drop** in Glorefs during business hours is often more diagnostic than a rise — it usually means users are blocked. Check `WDQsz`, vmstat `b`, and `wa` at the same timestamps.
- **Rdratio falling while PhyRds rises** is the canonical signature of an undersized global buffer pool relative to the working set.
