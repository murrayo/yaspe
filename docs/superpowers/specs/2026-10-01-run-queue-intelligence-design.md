# Design: Run Queue Intelligence from CPU Topology

**Date:** 2026-10-01

## Problem

The vmstat `r` (run queue) chart has no reference line in `yaspe.py`, and `chart_output.py` draws one line at the logical CPU count. `performance_analysis.py` flags `r` against 1× / 2× `number cpus`. None of these use the CPU topology now parsed by `sp_check.py` (sockets, cores, threads, bare metal vs VM), so a reader cannot tell whether a high run queue means CPU shortage, Hyper-Threading doubling-up, host contention, or something else.

## Goal

Using the topology already in the overview, show on the `r` chart:

1. Reference lines at the real capacity levels (physical cores, threads, vCPUs).
2. How often and how far `r` went above each line.
3. A data-driven verdict that cross-checks CPU % and, on VMs, steal.
4. A normalised "r per core" chart.
5. Topology-aware run queue findings in `performance_analysis.py`.

Success: a reader of the `r` chart can tell, without arithmetic, whether the run queue indicates CPU shortage, HT doubling-up, host contention or something else.

## Scope

- In: `yaspe_utilities.py` (new pure helpers), `yaspe.py` (`r` chart, new "r per core" chart, multi-line reference support), `chart_templates.py` / `chart_output.py` (system review `r` chart lines), `performance_analysis.py` (`r` thresholds and wording), `llm_context.py` (pass topology; `r` row of the prompt table only).
- Out: new text output files or `overview.txt` changes; AIX / Windows specific run queue logic (they get the Unknown treatment; Windows perfmon Processor Queue Length is not touched); per-NUMA analysis; verdict on system review charts (they have no footnote).
- No new module, so `yaspe_flask_v1/sync_engine.sh` is unchanged.

## Inputs

Overview-style dict (SQLite `overview` field/value pairs, string values, or `sp_dict` from `sp_check`, same keys): `cpu host type`, `hypervisor vendor`, `lscpu sockets`, `lscpu cores per socket`, `lscpu threads per core`, `lscpu cpus`, `number cpus`.

vmstat DataFrame: `datetime`, `r`; optional `Total CPU`, `us`, `sy`, `st`. Values may be strings; coerce to numeric.

## Reference lines

`r` counts tasks running plus runnable, so each line is a capacity level.

| Host | Line 1 | Line 2 |
|---|---|---|
| Bare metal, threads per core > 1 | physical cores (sockets × cores per socket), label "Physical cores 128 — above = HT doubling-up" | threads (logical CPUs), "Threads 256 — above = tasks waiting for any CPU" |
| Bare metal, threads per core = 1 | physical cores | — |
| KVM, threads per core > 1 | presented cores (sockets × cores per socket), "Presented cores 8 — above = sharing hyperthread pairs" | vCPUs |
| VMware, other hypervisor, or KVM with 1 thread per core | vCPUs | — |
| Unknown (no topology; AIX, Windows, older DBs) | logical CPUs (`lscpu cpus` else `number cpus`) | — |
| No CPU count | no lines | — |

### Y axis and off-scale lines

- Line 1 is drawn, and the y axis extended to include it (max = max(peak, line 1) × 1.05), only if the `r` peak ≥ 50% of line 1.
- Otherwise line 1 is not drawn and the y axis stays on the data; its legend entry still appears (as an invisible-line legend item / annotation) reading e.g. `Physical cores 128 (off scale, peak 20 = 16%)`.
- Line 2 is drawn only if it fits within the y axis already chosen; otherwise it is listed off scale the same way.

## Statistics (legend)

Computed over the data passed to that chart. For each line the legend label carries:

- `% of samples above` (one decimal; `<0.1%` when non-zero but rounds to 0).
- For the highest line with any samples above: peak value and its time, e.g. `Threads 256: above in 0.4%, peak 310 at 29-Aug 11:04`.

## Verdict (footnote)

One extra line appended to the existing topology footnote of the `r` chart (and its derived charts). "Queued samples" = samples with `r` > line 1. CPU % = `Total CPU`, else `us + sy`.

1. Fewer than 1% of samples queued: `Run queue stayed at or below 128 physical cores in 99%+ of samples — no sustained CPU queuing.` Stop.
2. Otherwise, CPU clause (omitted if no CPU % column):
   - median CPU % over queued samples ≥ 80: `CPU-bound: while r > 128, median CPU was 94%.`
   - < 80: `r exceeded 128 while CPU was only 45% busy — suggests bursty work within the sample interval or lock/spin contention rather than CPU shortage.`
3. Bare metal HT: `r was between cores and threads in 5.8% of samples — tasks sharing physical cores via HT get less throughput than full cores.`
4. KVM (omitted if no `st` column): median `st` over queued samples ≥ 5: `Steal 12% while queued — host is short of CPU; adding vCPUs alone won't help.` < 5 and CPU-bound: `Steal low — the guest itself needs more vCPUs.`
5. VMware: `Steal is not visible inside VMware guests; check vCenter CPU Ready (%RDY) for these times.`
6. Unknown topology: steps 1–2 only, against logical CPUs.

No `r` data (missing or no numeric values): no statistics, no verdict.

## r per core chart

New vmstat chart "r per core" (PNG and HTML) = `r` ÷ line 1's count. Y label names the divisor (`r ÷ 128 physical cores`, `r ÷ 38 vCPUs`, `r ÷ 8 presented cores`, `r ÷ 32 logical CPUs`). Reference line at 1.0 ("saturated"); bare metal HT and KVM with threads per core > 1 also get a line at line 2 ÷ line 1 (e.g. 2.0, "all threads busy"). Same topology title and footnote (with verdict) as `r`. Skipped when there are no lines.

## Code structure

### `yaspe_utilities.py`

```python
@dataclass
class RefLine:
    value: float
    label: str        # short base label, e.g. "Physical cores 128"
    kind: str         # "cores" | "threads" | "presented_cores" | "vcpus" | "logical"

def run_queue_lines(overview: dict) -> list[RefLine]

@dataclass
class RunQueueInsight:
    lines: list[RefLine]
    pct_above: list[float]          # parallel to lines
    legend_labels: list[str]        # parallel to lines, with stats / off-scale text
    drawn: list[bool]               # parallel to lines
    y_max: float | None
    peak: float | None
    peak_time: str | None
    verdict: str                    # "" when not applicable
    per_core_divisor: int | None
    per_core_label: str             # e.g. "r ÷ 128 physical cores"

def run_queue_insight(df, overview: dict) -> RunQueueInsight
```

### `yaspe.py`

- `simple_chart` and `_apply_ref_lines` accept `threshold` as either a `(value, label)` tuple (unchanged) or a list of tuples. Off-scale entries are passed as legend-only items.
- `chart_vmstat`: for `r`, compute the insight once; pass the drawn lines, legend labels and `y_max`; footnote = topology footnote + verdict. Add the "r per core" column to the chart loop.

### `chart_templates.py` / `chart_output.py`

`extra_horizontal` accepts a list of `(value, label)` tuples. `chart_output.py`'s `r` branch uses `run_queue_lines` (needs the topology fields; `system_review.py` maps the yaspe yaml keys — `CPU host type`, `Hypervisor vendor`, `Sockets`, `Cores per socket`, `Threads per core`, `CPUs` — to the overview-style keys and passes the dict as a new `topology` kwarg).

### `performance_analysis.py`

`_analyse_vmstat(df, vcpus, topology=None)`. With topology: warn = above line 1, alert = above the highest line (2× line 1 when only one line), same consecutive-sample rules. Observations name the line (`exceeded 128 physical cores`); hypotheses use the verdict reasoning. Without topology: behaviour unchanged.

### `llm_context.py`

Pass `sp_dict` as `topology` to `_analyse_vmstat`; update the `r` row of the threshold table to describe line 1 / highest line. No other changes.

## Testing

- `tests/test_run_queue.py`: `run_queue_lines` for every row of the table; % above and peak time; off-scale at, just above and just below 50%; each verdict branch (no queuing, CPU-bound, high `r` low CPU, HT band, KVM steal high/low, VMware %RDY, Unknown); missing `st`; missing CPU %; non-numeric `r`; string-typed overview values.
- Rendering: `r` and "r per core" PNG with multiple lines; Plotly HTML contains both horizontal lines; `extra_horizontal` list in `chart_templates`.
- `performance_analysis`: topology thresholds and wording; unchanged result without topology.
- Manual: rerun the `test_samples` folders (Manipal, EKA, IDEM, AIX) and inspect `r` and "r per core" charts.
