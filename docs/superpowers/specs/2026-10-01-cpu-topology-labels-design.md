# Design: Accurate CPU Topology Labels and Chart Footnotes

**Date:** 2026-10-01

## Problem

CPU charts label the logical CPU count as `cores` (e.g. "256 cores" on a bare metal host that has 128 physical cores with Hyper-Threading). A user read thread counts as CPU counts and drew the wrong capacity conclusion. Labels are also wrong the other way: `vCPU` is used for bare metal hosts.

## Goal

1. Parse the real CPU topology from the Linux `cpu` section (`lscpu`, falling back to `/proc/cpuinfo`).
2. Distinguish bare metal from virtual machines.
3. Label every CPU chart with an accurate count, and add a footnote under the x axis that states what the file proves and tells the reader to review the true processor architecture before making capacity assumptions.

## Scope

- In: `sp_check.py` parsing and overview/yaml output; `yaspe_utilities.py` label helper; `yaspe.py` chart titles and footnotes; `chart_output.py` run queue reference label; `system_review.py` vmstat title.
- Out: `llm_context.py` / `performance_analysis.py` vCPU wording; `pretty_performance.py`; cross-checking mgstat `numberofcpus` against lscpu; new warnings/recommendations; inferring host physical cores for VMs (not possible from inside a guest).
- No new module, so `yaspe_flask_v1/sync_engine.sh` is unchanged.

## Detection

Observed in sample files:

| Host | `Hypervisor vendor:` | `hypervisor` flag | lscpu topology |
|---|---|---|---|
| Bare metal | absent | absent | 4 sockets × 32 cores × 2 threads = 256 |
| VMware | `VMware` | present | 2 × 19 × 1 = 38 |
| AWS | `KVM` | present | 1 × 8 × 2 = 16 |

- Virtual if `Hypervisor vendor:` is present or the `hypervisor` flag appears in the lscpu `Flags:` line or a `/proc/cpuinfo` `flags` line.
- Bare metal if topology was parsed and neither signal is present.
- Unknown if no topology was found.

The VMware sample shows 19 cores/socket on a Xeon Silver 4216, which has 16 physical cores per socket — confirming guest topology is VM configuration, not host hardware.

## Parsing (`sp_check.py`)

In the existing line loop, alongside the `model name` check, match lines by prefix (tolerant of tabs/spaces before `:`):

| lscpu line | `sp_dict` key |
|---|---|
| `CPU(s):` (exact, not `On-line CPU(s) list` / `NUMA nodeN CPU(s)`) | `lscpu cpus` |
| `Thread(s) per core:` | `lscpu threads per core` |
| `Core(s) per socket:` | `lscpu cores per socket` |
| `Socket(s):` | `lscpu sockets` |
| `NUMA node(s):` | `lscpu numa nodes` |
| `Hypervisor vendor:` | `hypervisor vendor` |
| `hypervisor` token in a flags line | `hypervisor flag` = `True` |

Fallback when no lscpu `Socket(s):` line was found: from `/proc/cpuinfo` blocks, count processors, unique `physical id` values (sockets) and unique (`physical id`, `core id`) pairs (physical cores); derive threads per core = processors / cores and cores per socket = cores / sockets. Store under the same keys.

Only the first occurrence of each lscpu key is kept.

### Platform

The existing `VMware` substring detection is kept. After the loop, if `platform` is not set: use `hypervisor vendor` if present; otherwise `Bare metal` if topology was found and no hypervisor flag; otherwise `N/A` (unchanged).

### Overview text and yaml

`CPUs` line is unchanged. When topology is known, add:

```
CPU topology     : 4 sockets x 32 cores x 2 threads per core
Physical cores   : 128                      (bare metal only)
Threads          : 256 (Hyper-Threading enabled)   (bare metal only)
NUMA nodes       : 4
```

For VMs the topology line ends with `(as presented by <vendor>, not host physical cores)`.

yaml gains `Sockets`, `Cores per socket`, `Threads per core`, `NUMA nodes`, and `Physical cores` (bare metal only). `CPUs` stays numeric — `system_review.py` reads it as a count.

## Label helper (`yaspe_utilities.py`)

`cpu_topology_text(overview: dict) -> tuple[str, str]` — pure function, input is overview field/value pairs (string values from SQLite), returns `(title_label, footnote)`.

Logical CPU count = `lscpu cpus` if present, else `number cpus`.

| Case | Title label | Footnote |
|---|---|---|
| Bare metal, HT on | `256 threads (4 sockets x 32 cores x 2 HT)` | see below |
| Bare metal, HT off | `64 physical cores (2 sockets x 32 cores, no HT)` | see below |
| VM | `38 vCPUs (VMware)` | see below |
| Unknown | `256 logical CPUs` | see below |

AIX keeps its existing ` SMT n` suffix on the processor string. Missing keys (older SQLite, `.mgst`-only, Windows) fall into the Unknown case. If no count is known at all, the label is empty and the footnote is the Unknown text without a number.

Footnotes:

- **Bare metal:** "CPU topology (lscpu): bare metal, no hypervisor detected. 4 sockets × 32 physical cores × 2 threads = 256 logical CPUs (Intel(R) Xeon(R) Gold 6448H). 100% = all 256 threads busy. A Hyper-Threading thread shares a physical core and is not equivalent to a full core. Review the processor architecture before making capacity assumptions." (HT off: omit the Hyper-Threading sentence; "100% = all 64 cores busy".)
- **VMware (and other non-KVM hypervisors):** "CPU topology (lscpu): VMware VM. 38 vCPUs presented as 2 sockets × 19 cores × 1 thread — this is VM configuration, not host hardware. Host CPU model: Intel(R) Xeon(R) Silver 4216 CPU @ 2.10GHz. Host physical cores, Hyper-Threading and overcommit are not visible from inside the guest. Review the host architecture and vCenter CPU Ready (%RDY) before making capacity assumptions." (Non-VMware vendors: drop the vCenter clause.)
- **KVM:** "CPU topology (lscpu): KVM VM. 16 vCPUs presented as 8 cores × 2 threads. On cloud instances each vCPU is typically one hyperthread, not a full core. Host contention appears as vmstat st (steal). Review the instance type and host architecture before making capacity assumptions."
- **Unknown:** "CPU topology not available in this file. 256 is the logical CPU count reported by IRIS, which may be threads or vCPUs. Review the true processor architecture before making capacity assumptions."

`(source)` reads `(/proc/cpuinfo)` when the fallback was used.

## Chart changes (`yaspe.py`)

A small reader loads the overview table into a dict once per chart function and calls `cpu_topology_text`.

Titles: replace `{n} cores` with the title label in the vmstat stacked CPU chart (`yaspe.py:2691`), Total CPU and `r` (`yaspe.py:2713`), and perfmon processor charts (`yaspe.py:2967`). Extend to `us` and `sy`.

Footnote: new `footnote` kwarg (default `""`, separate from the user-supplied `subtitle`) on `simple_chart`, `simple_chart_stacked`, `linked_chart`, the derived Total CPU charts called from `simple_chart` (peak60, business hours peak, 5-min avg, daily summary, heatmap, day overlay — `simple_chart` forwards it), `simple_chart_dual_axis_glorefs_cpu`, `linked_chart_dual_axis_glorefs_cpu`. Passed only for the charts listed above plus Glorefs+CPU.

Rendering:
- Matplotlib: `fig.text` below the axes, small grey font, wrapped to figure width; increase bottom margin for charts saved without `bbox_inches="tight"` so the text is not clipped.
- Plotly: paper-anchored annotation below the bottom axis (under the zoom overview on two-panel HTML), with an increased bottom margin; same for PNG-via-plotly paths.

`chart_output.py:137`: run queue line becomes `Optimal run queue < {title_label}` — `number_cpus` stays numeric for the line value; the label is passed separately.

`system_review.py:103`: replace `{n} vCPU` with the title label, using the topology fields from the yaml.

## Testing

- `tests/test_cpu_topology.py`: parse the three sample CPU sections (bare metal, VMware, AWS) and a cpuinfo-only case via `sp_check`; assert `sp_dict` keys and platform.
- `cpu_topology_text`: every row of the label table, HT off, non-KVM non-VMware vendor, empty overview, and string-typed values as stored in SQLite.
- Footnote render smoke test: a chart call with a footnote writes a PNG without error.
- Manual: regenerate charts from a `test_samples/RHEL` file and check titles and footnotes in PNG and HTML; confirm the rest of the overview text is unchanged.
