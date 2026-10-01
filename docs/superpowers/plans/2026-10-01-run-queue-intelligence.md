# Run Queue Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the vmstat `r` (run queue) chart topology-aware: capacity reference lines, % of samples above each line, a data-driven verdict in the footnote, an "r per core" chart, and topology-aware run queue findings.

**Architecture:** Pure helpers `run_queue_lines` / `run_queue_insight` in `yaspe_utilities.py` take the overview-style topology dict plus the vmstat DataFrame and return everything the charts and analysis need. `yaspe.py` chart functions learn to draw a list of reference lines (with legend-only entries for off-scale lines) and a custom y label; `chart_vmstat` wires the insight into the `r` chart and a new "r per core" chart. `chart_output.py` / `system_review.py` and `performance_analysis.py` / `llm_context.py` consume `run_queue_lines` so thresholds never drift.

**Tech Stack:** Python 3.11, pandas, matplotlib, plotly, pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-run-queue-intelligence-design.md`

## Global Constraints

- Topology input is an overview-style dict with keys `cpu host type`, `hypervisor vendor`, `lscpu sockets`, `lscpu cores per socket`, `lscpu threads per core`, `lscpu cpus`, `number cpus`; values may be strings (SQLite) or ints (`sp_dict`).
- vmstat values may be strings; coerce with `pd.to_numeric(..., errors="coerce")`.
- Off-scale rule: line 1 drawn (y max = max(peak, line 1) × 1.05) only if peak ≥ 50% of line 1; otherwise y max = peak and line 1 is legend-only. Line 2 drawn only if ≤ chosen y max.
- Verdict "queued" = `r` > line 1; fewer than 1% queued → no-queuing sentence; CPU-bound threshold median CPU ≥ 80; KVM steal threshold median `st` ≥ 5.
- Existing single-tuple `threshold=(value, label)` callers and `extra_horizontal=(value, label)` callers must behave exactly as before.
- `_analyse_vmstat` without `topology` must behave exactly as before.
- No new module → `yaspe_flask_v1/sync_engine.sh` unchanged.
- Baseline: 4 tests already fail on `main` (`tests/test_llm_context.py::test_build_llm_context_json_serialisable`, `::test_export_llm_context_writes_bundle_and_prompt`, `tests/test_performance_analysis.py::test_compute_baselines_returns_expected_keys`, `::test_compute_baselines_values`). They must not change; no new failures.
- Test command: `pytest -q` from the repo root (pyenv `pytest`; the `yaspe311` conda env has no pytest).

## Review Focus

1. Duplicate or non-RangeIndex DataFrame index in `run_queue_insight` — peak time must come from the peak row (positional), not a label lookup that returns a Series. Test: `test_insight_peak_time_with_duplicate_index` (Task 2).
2. `r` present but CPU % columns absent (older AIX-like captures) — verdict must still say how often `r` exceeded line 1, never crash. Test: `test_verdict_without_cpu_columns` (Task 3).
3. VM with vendor but no lscpu topology (lines fall back to logical CPUs) — must get the Unknown treatment, no %RDY/steal clause. Test: `test_verdict_vendor_without_topology_is_unknown` (Task 3).
4. `r` peak of 0 (idle host) — y max 0 must not break the chart; line legend-only. Test: `test_insight_zero_peak` (Task 2).
5. `r per core` column must not appear when there is no CPU count, and `r` chart must keep its old behaviour then. Test: `test_chart_vmstat_no_cpu_count_no_per_core` (Task 5).

---

### Task 1: `RefLine` and `run_queue_lines`

**Files:**
- Modify: `yaspe_utilities.py` (imports at top; new code after `cpu_topology_text`)
- Test: `tests/test_run_queue.py` (create)

**Interfaces:**
- Consumes: `_overview_int(overview, key)` already in `yaspe_utilities.py`.
- Produces: `RefLine(value: int, kind: str, noun: str, label: str, meaning: str)` dataclass; `run_queue_lines(overview: dict) -> list[RefLine]` (lowest line first, `[]` when no CPU count).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_queue.py`:

```python
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe_utilities import run_queue_lines

BARE_HT = {"cpu host type": "bare metal", "lscpu sockets": "4", "lscpu cores per socket": "32",
           "lscpu threads per core": "2", "lscpu cpus": "256"}
BARE_NOHT = {"cpu host type": "bare metal", "lscpu sockets": "2", "lscpu cores per socket": "32",
             "lscpu threads per core": "1", "lscpu cpus": "64"}
KVM = {"cpu host type": "virtual", "hypervisor vendor": "KVM", "lscpu sockets": "1",
       "lscpu cores per socket": "8", "lscpu threads per core": "2", "lscpu cpus": "16"}
KVM1 = {"cpu host type": "virtual", "hypervisor vendor": "KVM", "lscpu sockets": "1",
        "lscpu cores per socket": "4", "lscpu threads per core": "1", "lscpu cpus": "4"}
VMW = {"cpu host type": "virtual", "hypervisor vendor": "VMware", "lscpu sockets": "2",
       "lscpu cores per socket": "19", "lscpu threads per core": "1", "lscpu cpus": "38"}
UNKNOWN = {"number cpus": "32"}


def _summary(lines):
    return [(ln.value, ln.kind, ln.label) for ln in lines]


def test_lines_bare_metal_ht():
    lines = run_queue_lines(BARE_HT)
    assert _summary(lines) == [(128, "cores", "Physical cores 128"), (256, "threads", "Threads 256")]
    assert lines[0].meaning == "HT doubling-up"
    assert lines[0].noun == "physical cores"
    assert lines[1].meaning == "tasks waiting for any CPU"


def test_lines_bare_metal_no_ht():
    lines = run_queue_lines(BARE_NOHT)
    assert _summary(lines) == [(64, "cores", "Physical cores 64")]
    assert lines[0].meaning == "tasks waiting for a core"


def test_lines_kvm_with_threads():
    lines = run_queue_lines(KVM)
    assert _summary(lines) == [(8, "presented_cores", "Presented cores 8"), (16, "vcpus", "vCPUs 16")]
    assert lines[0].meaning == "sharing hyperthread pairs"


def test_lines_kvm_one_thread_per_core():
    assert _summary(run_queue_lines(KVM1)) == [(4, "vcpus", "vCPUs 4")]


def test_lines_vmware():
    lines = run_queue_lines(VMW)
    assert _summary(lines) == [(38, "vcpus", "vCPUs 38")]
    assert lines[0].noun == "vCPUs"


def test_lines_unknown_uses_logical_count():
    lines = run_queue_lines(UNKNOWN)
    assert _summary(lines) == [(32, "logical", "Logical CPUs 32")]
    assert lines[0].noun == "logical CPUs"


def test_lines_no_cpu_count():
    assert run_queue_lines({}) == []
    assert run_queue_lines(None) == []
    assert run_queue_lines({"number cpus": "0"}) == []


def test_lines_int_values_from_sp_dict():
    sp = {"cpu host type": "bare metal", "lscpu sockets": 4, "lscpu cores per socket": 32,
          "lscpu threads per core": 2, "lscpu cpus": 256}
    assert [ln.value for ln in run_queue_lines(sp)] == [128, 256]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_queue.py -q`
Expected: collection ERROR — `ImportError: cannot import name 'run_queue_lines'`.

- [ ] **Step 3: Implement**

At the top of `yaspe_utilities.py`, after `import dateutil.parser`, add:

```python
from dataclasses import dataclass, field

import pandas as pd
```

After the end of `cpu_topology_text` add:

```python
@dataclass
class RefLine:
    value: int
    kind: str      # "cores" | "threads" | "presented_cores" | "vcpus" | "logical"
    noun: str      # used in sentences: "128 physical cores"
    label: str     # legend base: "Physical cores 128"
    meaning: str   # what r above this line means


_WAITING = "tasks waiting for any CPU"


def run_queue_lines(overview):
    """Return run queue reference lines (lowest first) for the CPU topology in overview."""
    overview = overview or {}
    sockets = _overview_int(overview, "lscpu sockets")
    cores_per_socket = _overview_int(overview, "lscpu cores per socket")
    threads_per_core = _overview_int(overview, "lscpu threads per core")
    logical = _overview_int(overview, "lscpu cpus") or _overview_int(overview, "number cpus")
    if logical is not None and logical <= 0:
        logical = None
    host_type = overview.get("cpu host type")

    if None in (sockets, cores_per_socket, threads_per_core) or host_type not in ("bare metal", "virtual"):
        if logical is None:
            return []
        return [RefLine(logical, "logical", "logical CPUs", f"Logical CPUs {logical}", _WAITING)]

    cores = sockets * cores_per_socket
    if logical is None:
        logical = cores * threads_per_core

    if host_type == "bare metal":
        if threads_per_core > 1:
            return [
                RefLine(cores, "cores", "physical cores", f"Physical cores {cores}", "HT doubling-up"),
                RefLine(logical, "threads", "threads", f"Threads {logical}", _WAITING),
            ]
        return [RefLine(cores, "cores", "physical cores", f"Physical cores {cores}", "tasks waiting for a core")]

    if overview.get("hypervisor vendor") == "KVM" and threads_per_core > 1:
        return [
            RefLine(cores, "presented_cores", "presented cores", f"Presented cores {cores}", "sharing hyperthread pairs"),
            RefLine(logical, "vcpus", "vCPUs", f"vCPUs {logical}", _WAITING),
        ]
    return [RefLine(logical, "vcpus", "vCPUs", f"vCPUs {logical}", _WAITING)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_queue.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add yaspe_utilities.py tests/test_run_queue.py
git commit -m "feat: add run_queue_lines for topology-aware run queue reference lines"
```

---

### Task 2: `run_queue_insight` — statistics, off-scale rule, per-core scaling

**Files:**
- Modify: `yaspe_utilities.py` (after `run_queue_lines`)
- Test: `tests/test_run_queue.py` (append)

**Interfaces:**
- Consumes: `RefLine`, `run_queue_lines` (Task 1).
- Produces:
  - `RunQueueInsight` dataclass with fields `lines`, `pct_above`, `legend_labels`, `drawn`, `thresholds` (list of `(value | None, legend_label)` — `None` = legend-only), `y_max`, `peak`, `peak_time` (`"%d-%b %H:%M"`), `verdict` (`""` until Task 3), `per_core_divisor`, `per_core_label`, `per_core_thresholds` (same shape as `thresholds`), `per_core_y_max`.
  - `run_queue_insight(df, overview, time_col="datetime_parsed") -> RunQueueInsight`. Empty `RunQueueInsight()` (all lists empty, numbers `None`, strings `""`) when no `r` column, no numeric `r`, or no lines.
  - `_fmt_pct(pct: float) -> str` (`"<0.1%"` for 0 < pct < 0.05, else one decimal + `%`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_queue.py` (and change the import line to `from yaspe_utilities import run_queue_lines, run_queue_insight, _fmt_pct`):

```python
def _rq_df(r, **cols):
    times = pd.date_range("2025-08-29 11:00", periods=len(r), freq="1min")
    data = {"datetime_parsed": times, "r": r}
    data.update(cols)
    return pd.DataFrame(data)


def test_insight_pct_above_and_peak():
    df = _rq_df([10.0] * 90 + [200.0] * 8 + [300.0] * 2)
    rq = run_queue_insight(df, BARE_HT)
    assert rq.pct_above == [10.0, 2.0]
    assert rq.peak == 300.0
    assert rq.peak_time == "29-Aug 12:38"
    assert rq.legend_labels[0] == "Physical cores 128 (above = HT doubling-up): 10.0% of samples above"
    assert rq.legend_labels[1] == ("Threads 256 (above = tasks waiting for any CPU): 2.0% of samples above, "
                                   "peak 300 at 29-Aug 12:38")
    assert rq.drawn == [True, True]
    assert rq.thresholds == [(128, rq.legend_labels[0]), (256, rq.legend_labels[1])]


def test_insight_peak_time_with_duplicate_index():
    df = _rq_df([1.0, 5.0, 2.0])
    df.index = [0, 0, 1]
    rq = run_queue_insight(df, UNKNOWN)
    assert rq.peak_time == "29-Aug 11:01"


def test_insight_off_scale_at_exactly_half():
    rq = run_queue_insight(_rq_df([64.0] * 10), BARE_HT)
    assert rq.drawn == [True, False]
    assert rq.y_max == 128 * 1.05


def test_insight_off_scale_just_below_half():
    rq = run_queue_insight(_rq_df([63.0] * 10), BARE_HT)
    assert rq.drawn == [False, False]
    assert rq.y_max == 63.0
    assert rq.legend_labels[0] == "Physical cores 128 (off scale, peak 63 = 49%)"
    assert rq.thresholds[0] == (None, "Physical cores 128 (off scale, peak 63 = 49%)")


def test_insight_off_scale_just_above_half():
    rq = run_queue_insight(_rq_df([65.0] * 10), BARE_HT)
    assert rq.drawn[0] is True


def test_insight_line_two_drawn_when_it_fits():
    rq = run_queue_insight(_rq_df([250.0] * 10), BARE_HT)
    assert rq.drawn == [True, True]
    assert rq.y_max == 250 * 1.05


def test_insight_line_two_off_scale():
    rq = run_queue_insight(_rq_df([130.0] * 10), BARE_HT)
    assert rq.drawn == [True, False]
    assert rq.thresholds[1] == (None, "Threads 256 (off scale, peak 130 = 51%)")


def test_insight_zero_peak():
    rq = run_queue_insight(_rq_df([0.0] * 10), BARE_HT)
    assert rq.y_max == 0.0
    assert rq.drawn == [False, False]
    assert rq.legend_labels[0] == "Physical cores 128 (off scale, peak 0 = 0%)"


def test_fmt_pct():
    assert _fmt_pct(0.0) == "0.0%"
    assert _fmt_pct(0.025) == "<0.1%"
    assert _fmt_pct(6.25) == "6.2%"


def test_insight_tiny_percentage():
    df = _rq_df([100.0] * 3999 + [300.0])
    rq = run_queue_insight(df, BARE_HT)
    assert "<0.1% of samples above" in rq.legend_labels[1]


def test_insight_string_r_values():
    rq = run_queue_insight(_rq_df(["10", "200", "x"]), BARE_HT)
    assert rq.peak == 200.0
    assert rq.pct_above == [50.0, 0.0]


def test_insight_non_numeric_r_is_empty():
    rq = run_queue_insight(_rq_df(["x"] * 5), BARE_HT)
    assert rq.lines == [] and rq.thresholds == [] and rq.verdict == ""
    assert rq.y_max is None and rq.per_core_divisor is None


def test_insight_missing_r_column_is_empty():
    df = pd.DataFrame({"datetime_parsed": pd.date_range("2025-08-29", periods=3, freq="1min"), "us": [1, 2, 3]})
    assert run_queue_insight(df, BARE_HT).thresholds == []


def test_insight_no_cpu_count_is_empty():
    rq = run_queue_insight(_rq_df([10.0] * 5), {})
    assert rq.lines == [] and rq.per_core_divisor is None


def test_insight_per_core_bare_metal_ht():
    rq = run_queue_insight(_rq_df([64.0] * 9 + [384.0]), BARE_HT)
    assert rq.per_core_divisor == 128
    assert rq.per_core_label == "r ÷ 128 physical cores"
    assert rq.per_core_y_max == 3.0 * 1.05
    assert rq.per_core_thresholds == [(1.0, "1.0 = r equals 128 physical cores (saturated)"),
                                      (2.0, "2 = all 256 threads busy")]


def test_insight_per_core_line_two_off_scale():
    rq = run_queue_insight(_rq_df([64.0] * 10), BARE_HT)
    assert rq.per_core_y_max == 1.05
    assert rq.per_core_thresholds[1] == (None, "2 = all 256 threads busy (off scale)")


def test_insight_per_core_vmware():
    rq = run_queue_insight(_rq_df([10.0] * 10), VMW)
    assert rq.per_core_label == "r ÷ 38 vCPUs"
    assert rq.per_core_thresholds == [(1.0, "1.0 = r equals 38 vCPUs (saturated)")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_queue.py -q`
Expected: collection ERROR — `ImportError: cannot import name 'run_queue_insight'`.

- [ ] **Step 3: Implement**

Append after `run_queue_lines` in `yaspe_utilities.py`:

```python
@dataclass
class RunQueueInsight:
    lines: list = field(default_factory=list)
    pct_above: list = field(default_factory=list)
    legend_labels: list = field(default_factory=list)
    drawn: list = field(default_factory=list)
    thresholds: list = field(default_factory=list)  # (value or None when off scale, legend label)
    y_max: float = None
    peak: float = None
    peak_time: str = None
    verdict: str = ""
    per_core_divisor: int = None
    per_core_label: str = ""
    per_core_thresholds: list = field(default_factory=list)
    per_core_y_max: float = None


def _fmt_pct(pct):
    if 0 < pct < 0.05:
        return "<0.1%"
    return f"{pct:.1f}%"


def _run_queue_verdict(data, r, lines, pct_above, overview):
    return ""


def run_queue_insight(df, overview, time_col="datetime_parsed"):
    """Reference lines, time above each line, verdict and per-core scaling for the vmstat r chart."""
    lines = run_queue_lines(overview)
    if df is None or "r" not in df.columns or not lines:
        return RunQueueInsight()
    r = pd.to_numeric(df["r"], errors="coerce")
    keep = r.notna()
    if not keep.any():
        return RunQueueInsight()
    data = df.loc[keep.to_numpy()]
    r = r[keep.to_numpy()]
    n = len(r)

    peak = float(r.max())
    peak_time = None
    if time_col in data.columns:
        peak_pos = int(r.to_numpy().argmax())
        peak_time = pd.Timestamp(data[time_col].iloc[peak_pos]).strftime("%d-%b %H:%M")

    pct_above = [100.0 * float((r > line.value).sum()) / n for line in lines]
    first = lines[0]
    y_max = max(peak, first.value) * 1.05 if peak >= 0.5 * first.value else peak
    drawn = [line.value <= y_max for line in lines]

    highest = max((i for i, pct in enumerate(pct_above) if pct > 0), default=None)
    legend_labels = []
    for i, line in enumerate(lines):
        if not drawn[i]:
            legend_labels.append(f"{line.label} (off scale, peak {peak:,.0f} = {100 * peak / line.value:.0f}%)")
            continue
        text = f"{line.label} (above = {line.meaning}): {_fmt_pct(pct_above[i])} of samples above"
        if i == highest and peak_time:
            text += f", peak {peak:,.0f} at {peak_time}"
        legend_labels.append(text)
    thresholds = [(line.value if drawn[i] else None, legend_labels[i]) for i, line in enumerate(lines)]

    per_core_y_max = max(peak / first.value, 1.0) * 1.05
    per_core_thresholds = [(1.0, f"1.0 = r equals {first.value} {first.noun} (saturated)")]
    if len(lines) > 1:
        ratio = lines[-1].value / first.value
        label = f"{ratio:g} = all {lines[-1].value} {lines[-1].noun} busy"
        if ratio <= per_core_y_max:
            per_core_thresholds.append((ratio, label))
        else:
            per_core_thresholds.append((None, f"{label} (off scale)"))

    return RunQueueInsight(
        lines=lines,
        pct_above=pct_above,
        legend_labels=legend_labels,
        drawn=drawn,
        thresholds=thresholds,
        y_max=y_max,
        peak=peak,
        peak_time=peak_time,
        verdict=_run_queue_verdict(data, r, lines, pct_above, overview or {}),
        per_core_divisor=first.value,
        per_core_label=f"r ÷ {first.value} {first.noun}",
        per_core_thresholds=per_core_thresholds,
        per_core_y_max=per_core_y_max,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_queue.py -q`
Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add yaspe_utilities.py tests/test_run_queue.py
git commit -m "feat: add run_queue_insight with time-above stats, off-scale rule and per-core scaling"
```

---

### Task 3: Run queue verdict

**Files:**
- Modify: `yaspe_utilities.py` (replace the `_run_queue_verdict` stub)
- Test: `tests/test_run_queue.py` (append)

**Interfaces:**
- Consumes: `_fmt_pct`, `RefLine`, `run_queue_insight` (Task 2) — `_run_queue_verdict(data, r, lines, pct_above, overview)` where `data` is the numeric-`r` subset of the DataFrame and `r` is the numeric series sharing `data`'s index.
- Produces: `RunQueueInsight.verdict` strings exactly as in the tests below.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_queue.py`:

```python
def _queued(n_queued, r_queued, n_total=100, r_idle=10.0, **cols_queued_idle):
    """r_idle for the first n_total - n_queued samples, r_queued for the rest; extra cols given as (queued, idle)."""
    n_idle = n_total - n_queued
    cols = {k: [v[1]] * n_idle + [v[0]] * n_queued for k, v in cols_queued_idle.items()}
    return _rq_df([r_idle] * n_idle + [r_queued] * n_queued, **cols)


def test_verdict_no_queuing():
    rq = run_queue_insight(_rq_df([10.0] * 100, **{"Total CPU": [50.0] * 100}), BARE_HT)
    assert rq.verdict == ("Run queue stayed at or below 128 physical cores in 99%+ of samples — "
                          "no sustained CPU queuing.")


def test_verdict_cpu_bound():
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (95.0, 20.0)}), BARE_HT)
    assert rq.verdict.startswith("Run queue: CPU-bound: while r > 128, median CPU was 95%.")


def test_verdict_high_r_low_cpu():
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (45.0, 20.0)}), BARE_HT)
    assert ("r exceeded 128 while CPU was only 45% busy — suggests bursty work within the sample "
            "interval or lock/spin contention rather than CPU shortage.") in rq.verdict


def test_verdict_us_sy_fallback():
    rq = run_queue_insight(_queued(10, 200.0, us=(80.0, 10.0), sy=(15.0, 5.0)), BARE_HT)
    assert "CPU-bound: while r > 128, median CPU was 95%." in rq.verdict


def test_verdict_without_cpu_columns():
    rq = run_queue_insight(_queued(10, 200.0), BARE_HT)
    assert rq.verdict.startswith("Run queue: r exceeded 128 physical cores in 10.0% of samples.")
    assert "CPU-bound" not in rq.verdict and "suggests bursty" not in rq.verdict


def test_verdict_ht_band():
    df = _rq_df([10.0] * 90 + [200.0] * 8 + [300.0] * 2, **{"Total CPU": [20.0] * 90 + [95.0] * 10})
    rq = run_queue_insight(df, BARE_HT)
    assert ("r was between cores and threads in 8.0% of samples — tasks sharing physical cores via HT "
            "get less throughput than full cores.") in rq.verdict


def test_verdict_no_ht_band_without_ht():
    rq = run_queue_insight(_queued(10, 100.0, **{"Total CPU": (95.0, 20.0)}), BARE_NOHT)
    assert "between cores and threads" not in rq.verdict


def test_verdict_kvm_steal_high():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0), "st": (12.0, 0.0)}), KVM)
    assert "Steal 12% while queued — host is short of CPU; adding vCPUs alone won't help." in rq.verdict


def test_verdict_kvm_steal_low_cpu_bound():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0), "st": (1.0, 0.0)}), KVM)
    assert rq.verdict.endswith("Steal low — the guest itself needs more vCPUs.")


def test_verdict_kvm_steal_low_not_cpu_bound():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (40.0, 20.0), "st": (1.0, 0.0)}), KVM)
    assert "Steal" not in rq.verdict


def test_verdict_kvm_without_st_column():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), KVM)
    assert "Steal" not in rq.verdict


def test_verdict_vmware_rdy():
    rq = run_queue_insight(_queued(10, 50.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), VMW)
    assert rq.verdict.endswith("Steal is not visible inside VMware guests; check vCenter CPU Ready (%RDY) for these times.")


def test_verdict_unknown_topology():
    rq = run_queue_insight(_queued(10, 50.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), UNKNOWN)
    assert rq.verdict == "Run queue: CPU-bound: while r > 32, median CPU was 95%."


def test_verdict_vendor_without_topology_is_unknown():
    overview = {"number cpus": "32", "cpu host type": "virtual", "hypervisor vendor": "VMware"}
    rq = run_queue_insight(_queued(10, 50.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), overview)
    assert "%RDY" not in rq.verdict
```

Note on `test_verdict_unknown_topology`: `UNKNOWN` has no `cpu host type`, so `run_queue_lines` returns the `logical` line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_queue.py -q`
Expected: the 14 new verdict tests FAIL (verdict is `""`); earlier 25 pass.

- [ ] **Step 3: Implement**

Replace the `_run_queue_verdict` stub in `yaspe_utilities.py`:

```python
def _run_queue_verdict(data, r, lines, pct_above, overview):
    first = lines[0]
    first_text = f"{first.value} {first.noun}"
    if pct_above[0] < 1.0:
        return f"Run queue stayed at or below {first_text} in 99%+ of samples — no sustained CPU queuing."

    queued = (r > first.value).to_numpy()
    if "Total CPU" in data.columns:
        cpu = pd.to_numeric(data["Total CPU"], errors="coerce")
    elif "us" in data.columns and "sy" in data.columns:
        cpu = pd.to_numeric(data["us"], errors="coerce") + pd.to_numeric(data["sy"], errors="coerce")
    else:
        cpu = None
    cpu_median = cpu[queued].median() if cpu is not None else None

    parts = []
    cpu_bound = False
    if cpu_median is None or pd.isna(cpu_median):
        parts.append(f"r exceeded {first_text} in {_fmt_pct(pct_above[0])} of samples.")
    elif cpu_median >= 80:
        cpu_bound = True
        parts.append(f"CPU-bound: while r > {first.value}, median CPU was {cpu_median:.0f}%.")
    else:
        parts.append(
            f"r exceeded {first.value} while CPU was only {cpu_median:.0f}% busy — suggests bursty work "
            "within the sample interval or lock/spin contention rather than CPU shortage."
        )

    if first.kind == "cores" and len(lines) > 1:
        band = pct_above[0] - pct_above[1]
        if band > 0:
            parts.append(
                f"r was between cores and threads in {_fmt_pct(band)} of samples — tasks sharing physical "
                "cores via HT get less throughput than full cores."
            )

    vendor = overview.get("hypervisor vendor") if first.kind in ("presented_cores", "vcpus") else ""
    if vendor == "KVM" and "st" in data.columns:
        st_median = pd.to_numeric(data["st"], errors="coerce")[queued].median()
        if not pd.isna(st_median):
            if st_median >= 5:
                parts.append(
                    f"Steal {st_median:.0f}% while queued — host is short of CPU; adding vCPUs alone won't help."
                )
            elif cpu_bound:
                parts.append("Steal low — the guest itself needs more vCPUs.")
    elif vendor == "VMware":
        parts.append("Steal is not visible inside VMware guests; check vCenter CPU Ready (%RDY) for these times.")

    return "Run queue: " + " ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_queue.py -q`
Expected: 39 passed.

- [ ] **Step 5: Commit**

```bash
git add yaspe_utilities.py tests/test_run_queue.py
git commit -m "feat: data-driven run queue verdict (CPU%, HT band, KVM steal, VMware %RDY)"
```

---

### Task 4: Multi-line thresholds and custom y label in chart functions

**Files:**
- Modify: `yaspe.py` — new helper above `_apply_ref_lines` (~line 1345); `_apply_ref_lines` threshold block (~1384-1390); `linked_chart` kwargs and the three `yaxis=dict(title=column_name, ...)` lines inside `linked_chart` (~1438, 1499, 1532); `simple_chart` kwargs, `ax.set_ylabel(column_name, fontsize=14)` (~1875) and threshold block (~1895-1899).
- Test: `tests/test_run_queue_charts.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `simple_chart(..., threshold=<tuple | list of (value | None, label)>, y_label=str)`, `linked_chart(..., threshold=<same>, y_label=str)`. A `None` value is a legend-only entry. `_threshold_list(threshold) -> list`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_queue_charts.py`:

```python
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe


def _df(periods=10):
    times = pd.date_range("2024-01-15 09:00", periods=periods, freq="1min")
    return pd.DataFrame({"datetime_parsed": times, "datetime": times, "metric": np.arange(periods, dtype=float)})


def _capture_png(fn, *args, **kwargs):
    captured = {}

    def fake_savefig(*a, **k):
        import matplotlib.pyplot as plt
        ax = plt.gcf().axes[0]
        legend = ax.get_legend()
        captured["legend"] = [t.get_text() for t in legend.get_texts()] if legend else []
        captured["ylabel"] = ax.get_ylabel()
        captured["hlines"] = [ln.get_ydata()[0] for ln in ax.get_lines() if len(ln.get_ydata()) == 2
                              and ln.get_ydata()[0] == ln.get_ydata()[1]]

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), patch("matplotlib.pyplot.close"):
        fn(*args, **kwargs)
    return captured


def test_threshold_list_normalises():
    assert yaspe._threshold_list(None) == []
    assert yaspe._threshold_list((5, "A")) == [(5, "A")]
    assert yaspe._threshold_list([(5, "A"), (None, "B")]) == [(5, "A"), (None, "B")]


def test_simple_chart_single_threshold_unchanged(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r", "T", 10, str(tmp_path) + "/", "", threshold=(5, "Five"))
    assert "Five" in cap["legend"]
    assert 5 in cap["hlines"]


def test_simple_chart_threshold_list_with_legend_only(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r", "T", 10, str(tmp_path) + "/", "",
                       threshold=[(5, "Line one"), (8, "Line two"), (None, "Off scale line")])
    assert {"Line one", "Line two", "Off scale line"} <= set(cap["legend"])
    assert 5 in cap["hlines"] and 8 in cap["hlines"]


def test_simple_chart_y_label(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r per core", "T", 2, str(tmp_path) + "/", "",
                       y_label="r ÷ 128 physical cores")
    assert cap["ylabel"] == "r ÷ 128 physical cores"


def test_simple_chart_default_y_label(tmp_path):
    cap = _capture_png(yaspe.simple_chart, _df(), "r", "T", 10, str(tmp_path) + "/", "")
    assert cap["ylabel"] == "r"


def test_apply_ref_lines_threshold_list():
    fig = go.Figure()
    yaspe._apply_ref_lines(fig, _df(), False, [(5, "A"), (8, "B"), (None, "C off scale")], row=None)
    assert [s.y0 for s in fig.layout.shapes] == [5, 8]
    assert [t.name for t in fig.data] == ["C off scale"]


def test_apply_ref_lines_single_tuple_unchanged():
    fig = go.Figure()
    yaspe._apply_ref_lines(fig, _df(), False, (80, "80% CPU threshold"), row=None)
    assert [s.y0 for s in fig.layout.shapes] == [80]
    assert fig.layout.shapes[0].line.dash == "dashdot"


def test_linked_chart_html_y_label_and_lines(tmp_path):
    captured = {}

    def fake_write_html(self, *a, **k):
        captured["fig"] = self

    with patch("plotly.graph_objects.Figure.write_html", fake_write_html):
        yaspe.linked_chart(_df(), "r per core", "T", 2, str(tmp_path) + "/", "",
                           threshold=[(1.0, "Saturated"), (None, "Threads off scale")],
                           y_label="r ÷ 128 physical cores")
    fig = captured["fig"]
    assert fig.layout.yaxis.title.text == "r ÷ 128 physical cores"
    assert [s.y0 for s in fig.layout.shapes] == [1.0]
    assert "Threads off scale" in [t.name for t in fig.data]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_queue_charts.py -q`
Expected: FAIL — `AttributeError: module 'yaspe' has no attribute '_threshold_list'`, `ValueError: too many values to unpack` on list thresholds, y label mismatch. `test_simple_chart_single_threshold_unchanged`, `test_simple_chart_default_y_label` and `test_apply_ref_lines_single_tuple_unchanged` pass already.

- [ ] **Step 3: Implement**

In `yaspe.py`, directly above `def _apply_ref_lines(`, add:

```python
_PNG_THRESHOLD_STYLES = ["-.", "--", ":"]
_PLOTLY_THRESHOLD_DASHES = ["dashdot", "dash", "dot"]


def _threshold_list(threshold):
    """Normalise a threshold kwarg: None, one (value, label) tuple, or a list of them.
    A value of None is a legend-only entry (reference line off scale)."""
    if threshold is None:
        return []
    if isinstance(threshold, tuple):
        return [threshold]
    return list(threshold)
```

In `_apply_ref_lines`, replace:

```python
    if threshold is not None:
        thresh_val, thresh_label = threshold
        thresh_color = "red" if data["metric"].max() > thresh_val else "orange"
        fig.add_hline(y=thresh_val, line=dict(color=thresh_color, dash="dashdot", width=1.5),
                      annotation_text=thresh_label, annotation_position="top left",
                      annotation=dict(bgcolor="rgba(255,255,255,0.85)", bordercolor="lightgrey", borderwidth=1),
                      **kw)
```

with:

```python
    for i, (thresh_val, thresh_label) in enumerate(_threshold_list(threshold)):
        if thresh_val is None:
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", name=thresh_label,
                                     line=dict(color="grey", dash="dot")), **kw)
            continue
        thresh_color = "red" if data["metric"].max() > thresh_val else "orange"
        fig.add_hline(y=thresh_val,
                      line=dict(color=thresh_color, dash=_PLOTLY_THRESHOLD_DASHES[i % 3], width=1.5),
                      annotation_text=thresh_label,
                      annotation_position="top left" if i % 2 == 0 else "top right",
                      annotation=dict(bgcolor="rgba(255,255,255,0.85)", bordercolor="lightgrey", borderwidth=1),
                      **kw)
```

In `linked_chart`, after `footnote = kwargs.get("footnote", "")` add:

```python
    y_label = kwargs.get("y_label", column_name)
```

and in the three `yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),` lines **inside `linked_chart` only** (two `png_fig.update_layout` calls and the two-panel `fig.update_layout`) replace `title=column_name` with `title=y_label`. Leave the other occurrences in the file (lines ~1063, ~1574, ~1615, ~1644) unchanged.

In `simple_chart`, change the comment on the threshold kwarg line to `# Optional (value, label) tuple or list of them`, and after `footnote = kwargs.get("footnote", "")` add:

```python
    y_label = kwargs.get("y_label", column_name)
```

Replace `ax.set_ylabel(column_name, fontsize=14)` inside `simple_chart` (~line 1875; the one followed by `ax.tick_params(labelsize=14)` and `if is_long_period:`) with `ax.set_ylabel(y_label, fontsize=14)`.

Replace the `simple_chart` threshold block:

```python
    if threshold is not None:
        thresh_val, thresh_label = threshold
        color = "red" if png_data["metric"].max() > thresh_val else "orange"
        ax.axhline(y=thresh_val, color=color, linestyle="-.", linewidth=1.5, alpha=0.8, label=thresh_label)
        ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)
```

with:

```python
    thresholds = _threshold_list(threshold)
    for i, (thresh_val, thresh_label) in enumerate(thresholds):
        if thresh_val is None:
            ax.plot([], [], color="grey", linestyle=":", label=thresh_label)
            continue
        color = "red" if png_data["metric"].max() > thresh_val else "orange"
        ax.axhline(y=thresh_val, color=color, linestyle=_PNG_THRESHOLD_STYLES[i % 3], linewidth=1.5, alpha=0.8,
                   label=thresh_label)
    if thresholds:
        ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_queue_charts.py tests/test_cpu_footnote_charts.py -q`
Expected: all pass (9 new + existing footnote chart tests).

- [ ] **Step 5: Commit**

```bash
git add yaspe.py tests/test_run_queue_charts.py
git commit -m "feat: charts accept a list of reference lines and a custom y label"
```

---

### Task 5: Wire the insight into `chart_vmstat` (`r` chart + "r per core" chart)

**Files:**
- Modify: `yaspe.py` — import line `from yaspe_utilities import cpu_topology_text`; `chart_vmstat` (~2696-2830).
- Test: `tests/test_run_queue_charts.py` (append)

**Interfaces:**
- Consumes: `run_queue_insight(df, overview, time_col="datetime_parsed")` and `RunQueueInsight` fields (Task 2/3); `threshold=` list and `y_label=` kwargs (Task 4); existing `get_overview_dict`, `cpu_topology_text`.
- Produces: `r` chart calls get `threshold=rq.thresholds`, `max_y=rq.y_max`, footnote `f"{cpu_footnote} {rq.verdict}"`; new chart column `"r per core"` with `threshold=rq.per_core_thresholds`, `max_y=rq.per_core_y_max`, `y_label=rq.per_core_label`, `min_max=False`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_queue_charts.py`:

```python
import sqlite3


def _db(overview_rows, r_values):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id INTEGER PRIMARY KEY AUTOINCREMENT, field TEXT NOT NULL, value TEXT)")
    conn.executemany("INSERT INTO overview (field, value) VALUES (?, ?)", overview_rows)
    n = len(r_values)
    times = pd.date_range("2024-01-15 09:00", periods=n, freq="1min")
    pd.DataFrame({
        "RunDate": times.strftime("%m/%d/%Y"), "RunTime": times.strftime("%H:%M:%S"),
        "r": r_values, "us": np.full(n, 80.0), "sy": np.full(n, 15.0),
        "wa": np.ones(n), "id": np.full(n, 5.0),
    }).to_sql("vmstat", conn, index=False)
    conn.commit()
    return conn


BARE_ROWS = [
    ("customer", "Acme"), ("operating system", "Linux"), ("processor model", "Intel(R) Xeon(R) Gold 6448H"),
    ("number cpus", "256"), ("lscpu cpus", "256"), ("lscpu sockets", "4"),
    ("lscpu cores per socket", "32"), ("lscpu threads per core", "2"),
    ("cpu host type", "bare metal"), ("cpu topology source", "lscpu"),
]


def _run_vmstat(conn, tmp_path, png=True):
    with patch.object(yaspe, "simple_chart") as sc, \
         patch.object(yaspe, "simple_chart_stacked"), \
         patch.object(yaspe, "linked_chart") as lc:
        yaspe.chart_vmstat(conn, str(tmp_path) + "/", "", png, False)
    return {c.args[1]: c for c in sc.call_args_list}, {c.args[1]: c for c in lc.call_args_list}


def test_chart_vmstat_r_gets_lines_and_verdict(tmp_path):
    png, _ = _run_vmstat(_db(BARE_ROWS, [10.0] * 90 + [200.0] * 10), tmp_path)
    r_call = png["r"]
    thresholds = r_call.kwargs["threshold"]
    assert [t[0] for t in thresholds] == [128, None]
    assert thresholds[0][1].startswith("Physical cores 128 (above = HT doubling-up): 10.0% of samples above")
    assert r_call.args[3] == 200 * 1.05
    assert "bare metal" in r_call.kwargs["footnote"]
    assert "Run queue: CPU-bound: while r > 128, median CPU was 95%." in r_call.kwargs["footnote"]


def test_chart_vmstat_r_per_core_chart(tmp_path):
    png, _ = _run_vmstat(_db(BARE_ROWS, [10.0] * 90 + [200.0] * 10), tmp_path)
    pc = png["r per core"]
    assert pc.kwargs["y_label"] == "r ÷ 128 physical cores"
    assert pc.kwargs["threshold"][0] == (1.0, "1.0 = r equals 128 physical cores (saturated)")
    assert pc.kwargs["min_max"] is False
    assert "256 threads (4 sockets x 32 cores x 2 HT)" in pc.args[2]
    assert "Run queue:" in pc.kwargs["footnote"]
    assert pc.args[0]["metric"].max() == 200.0 / 128


def test_chart_vmstat_html_r_per_core(tmp_path):
    _, html = _run_vmstat(_db(BARE_ROWS, [10.0] * 100), tmp_path, png=False)
    assert html["r per core"].kwargs["y_label"] == "r ÷ 128 physical cores"
    assert html["r"].kwargs["threshold"][0][0] is None


def test_chart_vmstat_no_cpu_count_no_per_core(tmp_path):
    rows = [("customer", "Acme"), ("operating system", "Linux"), ("processor model", "Some CPU")]
    png, _ = _run_vmstat(_db(rows, [3.0] * 10), tmp_path)
    assert "r per core" not in png
    assert png["r"].kwargs.get("threshold") is None
    assert png["r"].args[3] == 3.0


def test_chart_vmstat_other_columns_untouched(tmp_path):
    png, _ = _run_vmstat(_db(BARE_ROWS, [10.0] * 100), tmp_path)
    assert png["Total CPU"].kwargs["threshold"] == (80, "80% CPU threshold")
    assert "Run queue" not in png["Total CPU"].kwargs["footnote"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_queue_charts.py -q`
Expected: the 5 new tests FAIL (`KeyError: 'r per core'`, `threshold` is `None` for `r`); Task 4 tests pass.

- [ ] **Step 3: Implement**

Change the import in `yaspe.py`:

```python
from yaspe_utilities import cpu_topology_text, run_queue_insight
```

In `chart_vmstat`, after `df.sort_values("datetime_parsed", inplace=True)` add:

```python
    # Run queue reference lines, time-above stats and verdict from the CPU topology
    rq = run_queue_insight(df, overview)
    if rq.per_core_divisor:
        df["r per core"] = pd.to_numeric(df["r"], errors="coerce") / rq.per_core_divisor
```

In the per-column loop, replace:

```python
            if column_name in ("Total CPU", "r", "us", "sy"):
                title = f"{column_name} - {customer}{cpu_title_line}"
                column_footnote = cpu_footnote
            else:
```

with:

```python
            if column_name in ("Total CPU", "r", "us", "sy", "r per core"):
                title = f"{column_name} - {customer}{cpu_title_line}"
                column_footnote = cpu_footnote
                if column_name in ("r", "r per core") and rq.verdict:
                    column_footnote = f"{cpu_footnote} {rq.verdict}"
            else:
```

After the existing threshold block (the `elif column_name == "wa": threshold = (10, "10% iowait threshold")` lines) add:

```python
            y_label = column_name
            if column_name == "r" and rq.thresholds:
                threshold = rq.thresholds
                max_y = rq.y_max
            elif column_name == "r per core":
                threshold = rq.per_core_thresholds
                max_y = rq.per_core_y_max
                y_label = rq.per_core_label
```

Add `y_label=y_label,` to the `simple_chart(...)` call (after `footnote=column_footnote,`) and to both `linked_chart(...)` calls in this loop (after `footnote=column_footnote`).

`min_max` for `"r per core"` stays `False` because it is not in the `("Total CPU", "wa", "sy", "us", "r")` tuple — do not add it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_queue_charts.py tests/test_cpu_footnote_charts.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add yaspe.py tests/test_run_queue_charts.py
git commit -m "feat: topology reference lines, verdict and r per core chart for vmstat run queue"
```

---

### Task 6: System review `r` chart lines

**Files:**
- Modify: `chart_templates.py` (~line 177-182, `extra_horizontal` drawing), `chart_output.py` (`chart_vmstat`, ~line 109-140), `system_review.py` (~line 118-125 and the three `chart_output.chart_vmstat(` calls at ~142, ~175, ~210)
- Test: `tests/test_run_queue_charts.py` (append)

**Interfaces:**
- Consumes: `run_queue_lines(overview) -> list[RefLine]` (Task 1); `system_review.yaml_cpu_overview(yaspe_yaml) -> dict` (existing).
- Produces: `chart_templates._draw_extra_horizontal(ax, extra_horizontal, max_y)`; `chart_output.chart_vmstat(..., topology=dict)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_queue_charts.py`:

```python
import matplotlib.pyplot as plt


def test_draw_extra_horizontal_tuple_and_list():
    import chart_templates
    fig, ax = plt.subplots()
    chart_templates._draw_extra_horizontal(ax, (5, "Five"), 10)
    chart_templates._draw_extra_horizontal(ax, [(128, "Cores"), (256, "Threads")], 10)
    chart_templates._draw_extra_horizontal(ax, (0, ""), 10)
    labels = [ln.get_label() for ln in ax.get_lines()]
    assert labels == ["Five", "Cores", "Threads"]
    plt.close(fig)


def test_chart_output_r_uses_topology_lines():
    import chart_output
    captured = []
    times = pd.date_range("2024-01-15 09:00", periods=5, freq="1min")
    df = pd.DataFrame({"r": [1.0] * 5, "Total CPU": [10.0] * 5}, index=times)
    topology = {"cpu host type": "bare metal", "lscpu sockets": 4, "lscpu cores per socket": 32,
                "lscpu threads per core": 2, "number cpus": 256}
    with patch("chart_templates.chart_multi_line", side_effect=lambda *a, **k: captured.append(k)):
        chart_output.chart_vmstat(df, {"vmstat columns": ["r"]}, number_cpus=256, topology=topology)
    r_call = [k for k in captured if k["left_y_axis_label"] == "r"][0]
    assert r_call["extra_horizontal"] == [(128, "Physical cores 128 (above = HT doubling-up)"),
                                          (256, "Threads 256 (above = tasks waiting for any CPU)")]


def test_system_review_passes_topology():
    import system_review
    overview = system_review.yaml_cpu_overview({"CPUs": 256, "CPU host type": "bare metal", "Sockets": 4,
                                                "Cores per socket": 32, "Threads per core": 2})
    from yaspe_utilities import run_queue_lines
    assert [ln.value for ln in run_queue_lines(overview)] == [128, 256]
```

The existing `tests/test_cpu_topology.py::test_run_queue_label_uses_cpu_label` (no `topology`) must keep passing — it pins the fallback.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_queue_charts.py -q`
Expected: `test_draw_extra_horizontal_tuple_and_list` FAILS (`AttributeError: ... '_draw_extra_horizontal'`), `test_chart_output_r_uses_topology_lines` FAILS (gets `(256, "Optimal run queue < 256 logical CPUs")`). `test_system_review_passes_topology` passes already (it pins the mapping the wiring relies on).

- [ ] **Step 3: Implement**

In `chart_templates.py`, add above `def chart_multi_line(` (module level):

```python
def _draw_extra_horizontal(ax, extra_horizontal, max_y):
    """Draw one (value, label) reference line, or a list of them; values <= 0 are skipped."""
    lines = extra_horizontal if isinstance(extra_horizontal, list) else [extra_horizontal]
    for value, label in lines:
        if value > 0:
            color = "r" if value < max_y else "m"
            ax.axhline(y=value, color=color, linestyle="--", label=f"{label}")
```

Replace in `chart_multi_line`:

```python
    extra_color = "m"
    if extra_horizontal[0] > 0:
        if extra_horizontal[0] < max_y:
            extra_color = "r"

        ax1.axhline(y=extra_horizontal[0], color=extra_color, linestyle="--", label=f"{extra_horizontal[1]}")
```

with:

```python
    _draw_extra_horizontal(ax1, extra_horizontal, max_y)
```

In `chart_output.py` `chart_vmstat`, after `cpu_label = kwargs.get("cpu_label", "")` add:

```python
    topology = kwargs.get("topology") or {}
    run_queue_refs = yaspe_utilities.run_queue_lines(topology) if topology else []
```

and replace:

```python
        if counter == "r" and number_cpus > 0:
            label = cpu_label or f"{number_cpus} logical CPUs"
            extra_horizontal = (number_cpus, f"Optimal run queue < {label}")
```

with:

```python
        if counter == "r" and run_queue_refs:
            extra_horizontal = [(ln.value, f"{ln.label} (above = {ln.meaning})") for ln in run_queue_refs]
        elif counter == "r" and number_cpus > 0:
            label = cpu_label or f"{number_cpus} logical CPUs"
            extra_horizontal = (number_cpus, f"Optimal run queue < {label}")
```

In `system_review.py`, change:

```python
    cpu_label = ""

    if "yaspe" in site_survey_input:
        number_cpus = site_survey_input["yaspe"]["CPUs"]
        cpu_label, _ = yaspe_utilities.cpu_topology_text(yaml_cpu_overview(site_survey_input["yaspe"]))
```

to:

```python
    cpu_label = ""
    cpu_topology = {}

    if "yaspe" in site_survey_input:
        number_cpus = site_survey_input["yaspe"]["CPUs"]
        cpu_topology = yaml_cpu_overview(site_survey_input["yaspe"])
        cpu_label, _ = yaspe_utilities.cpu_topology_text(cpu_topology)
```

and add `topology=cpu_topology,` after `cpu_label=cpu_label,` in each of the three `chart_output.chart_vmstat(` calls.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_queue_charts.py tests/test_cpu_topology.py -q`
Expected: all pass, including `test_run_queue_label_uses_cpu_label`.

- [ ] **Step 5: Commit**

```bash
git add chart_templates.py chart_output.py system_review.py tests/test_run_queue_charts.py
git commit -m "feat: system review r chart draws topology run queue lines"
```

---

### Task 7: Topology-aware run queue findings

**Files:**
- Modify: `performance_analysis.py` (imports ~line 15; `_analyse_vmstat` signature line 279 and the `r` block ~414-447), `llm_context.py` (threshold table row ~line 131; `_analyse_vmstat` call ~line 897)
- Test: `tests/test_performance_analysis.py` (append)

**Interfaces:**
- Consumes: `run_queue_lines`, `run_queue_insight(df, overview, time_col="dt")` (Tasks 1-3).
- Produces: `_analyse_vmstat(df, vcpus, topology=None) -> list[Finding]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_performance_analysis.py`:

```python
BARE_HT_TOPOLOGY = {"cpu host type": "bare metal", "lscpu sockets": 4, "lscpu cores per socket": 32,
                    "lscpu threads per core": 2, "lscpu cpus": 256}


def _r_findings(findings):
    return [f for f in findings if f.metric == "r (run queue)"]


def test_run_queue_topology_warn_above_physical_cores():
    df = _make_vmstat_df(wa_vals=[2.0] * 10, r_vals=[200.0] * 5 + [10.0] * 5)
    findings = _r_findings(_analyse_vmstat(df, vcpus=256, topology=BARE_HT_TOPOLOGY))
    assert [f.severity for f in findings] == ["Yellow"]
    assert "Run queue exceeded 128 physical cores for 5 consecutive samples." in findings[0].observation


def test_run_queue_topology_alert_above_threads():
    df = _make_vmstat_df(wa_vals=[2.0] * 10, r_vals=[300.0] * 3 + [10.0] * 7)
    findings = _r_findings(_analyse_vmstat(df, vcpus=256, topology=BARE_HT_TOPOLOGY))
    assert [f.severity for f in findings] == ["Red"]
    assert "Run queue exceeded 256 threads for 3 consecutive samples. Peak: 300." in findings[0].observation
    assert any(h.startswith("hypothesis: Run queue:") for h in findings[0].hypotheses)


def test_run_queue_topology_single_line_alerts_at_double():
    vmw = {"cpu host type": "virtual", "hypervisor vendor": "VMware", "lscpu sockets": 2,
           "lscpu cores per socket": 19, "lscpu threads per core": 1, "lscpu cpus": 38}
    df = _make_vmstat_df(wa_vals=[2.0] * 10, r_vals=[80.0] * 3 + [10.0] * 7)
    findings = _r_findings(_analyse_vmstat(df, vcpus=38, topology=vmw))
    assert [f.severity for f in findings] == ["Red"]
    assert "Run queue exceeded 2× 38 vCPUs (76)" in findings[0].observation


def test_run_queue_without_topology_unchanged():
    df = _make_vmstat_df(wa_vals=[2.0] * 10, r_vals=[5.0] * 3 + [0.0] * 7)
    findings = _r_findings(_analyse_vmstat(df, vcpus=2))
    assert findings[0].observation.startswith("Run queue exceeded 4 (2× vCPUs=2) for 3 consecutive samples.")
    assert findings[0].hypotheses == ["hypothesis: CPU saturation — more runnable threads than cores"]
```

Before writing these, check `_fmt_n(4.0)` returns `"4"` and `_fmt_n(300.0)` returns `"300"` (`python -c "import performance_analysis as p; print(p._fmt_n(4.0), p._fmt_n(300.0))"`); if it formats differently, adjust only the literal numbers in the expected strings and ledger it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_performance_analysis.py -q -k run_queue`
Expected: the 3 topology tests FAIL with `TypeError: _analyse_vmstat() got an unexpected keyword argument 'topology'`; `test_run_queue_without_topology_unchanged` and the existing `test_analyse_vmstat_run_queue_vcpu_relative` pass.

- [ ] **Step 3: Implement**

In `performance_analysis.py`, after `import pandas as pd` add:

```python
from yaspe_utilities import run_queue_insight, run_queue_lines
```

Change the signature to:

```python
def _analyse_vmstat(df: pd.DataFrame, vcpus: Optional[int], topology: Optional[dict] = None) -> list:
```

Replace the whole `# --- r (run queue) — vCPU-relative ---` block (from that comment through the end of the `elif warn_runs:` `findings.append(...)` for `r`) with:

```python
    # --- r (run queue) — topology lines when known, else vCPU-relative ---
    rq_lines = run_queue_lines(topology) if topology else []
    if "r" in df.columns and (rq_lines or vcpus is not None):
        r_vals = pd.to_numeric(df["r"], errors="coerce").fillna(0)
        red_hypotheses = ["hypothesis: CPU saturation — more runnable threads than cores"]
        warn_hypotheses = ["hypothesis: intermittent CPU pressure"]
        if rq_lines:
            first, last = rq_lines[0], rq_lines[-1]
            warn_thr = first.value
            warn_desc = f"{first.value} {first.noun}"
            if len(rq_lines) > 1:
                alert_thr = last.value
                alert_desc = f"{last.value} {last.noun}"
            else:
                alert_thr = first.value * 2
                alert_desc = f"2× {first.value} {first.noun} ({_fmt_n(alert_thr)})"
            verdict = run_queue_insight(df, topology, time_col="dt").verdict
            if verdict:
                red_hypotheses.append(f"hypothesis: {verdict}")
                warn_hypotheses.append(f"hypothesis: {verdict}")
        else:
            alert_thr = vcpus * 2.0
            warn_thr = vcpus * 1.0
            alert_desc = f"{_fmt_n(alert_thr)} (2× vCPUs={vcpus})"
            warn_desc = f"{_fmt_n(warn_thr)} (1× vCPUs={vcpus})"
        red_runs  = _find_breaches(r_vals, df["dt"], alert_thr, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(r_vals, df["dt"], warn_thr,  WARN_CONSECUTIVE)
        if red_runs:
            when, n_events, primary = _fmt_breach_when(red_runs, _fmt_ts)
            start, end, count = primary
            recurrence = f" Occurred {n_events} time(s) across the collection window." if n_events > 1 else ""
            findings.append(Finding(
                metric="r (run queue)",
                severity="Red",
                observation=f"Run queue exceeded {alert_desc} for "
                            f"{count} consecutive samples. Peak: {_fmt_n(r_vals.max())}.{recurrence}",
                when=when,
                hypotheses=red_hypotheses,
                next_step="Cross-reference with us+sy. If us+sy < 80%, suspect lock contention rather than CPU shortage.",
            ))
        elif warn_runs:
            when, n_events, primary = _fmt_breach_when(warn_runs, _fmt_ts)
            start, end, count = primary
            recurrence = f" Occurred {n_events} time(s) across the collection window." if n_events > 1 else ""
            findings.append(Finding(
                metric="r (run queue)",
                severity="Yellow",
                observation=f"Run queue exceeded {warn_desc} for {count} consecutive samples.{recurrence}",
                when=when,
                hypotheses=warn_hypotheses,
                next_step="Monitor trend.",
            ))
```

Without topology the observation strings are byte-identical to before (`f"{_fmt_n(alert_thr)} (2× vCPUs={vcpus})"`), so existing tests and LLM output are unchanged.

In `llm_context.py`:
- Replace the table row
  `| r (run queue) | vCPUs | > 2x vCPUs sustained | > 1x vCPUs sustained |`
  with
  `| r (run queue) | physical cores / vCPUs | > threads (bare metal HT) or vCPUs (KVM with HT), else 2x vCPUs, sustained | > physical / presented cores, else 1x vCPUs, sustained |`
- Change `all_findings.extend(_pa._analyse_vmstat(vm_df, vcpus=vcpus))` to `all_findings.extend(_pa._analyse_vmstat(vm_df, vcpus=vcpus, topology=sp_dict))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q`
Expected: only the 4 baseline failures (listed in Global Constraints); everything else passes.

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py llm_context.py tests/test_performance_analysis.py
git commit -m "feat: topology-aware run queue findings in performance analysis"
```

---

### Final verification (after Task 7, before the final review)

- [ ] Run the sample folders exactly as the user does, using `/tmp/run_samples.sh` (symlinks each `test_samples/<folder>/*.html` into `/tmp/yaspe_samples/<folder>`, runs `python yaspe.py -i $i -a -s -c -o yaspe` per file, then `python yaspe.py -e yaspe_SystemPerformance.sqlite -P`). Expected: 0 tracebacks in every `run.log`.
- [ ] Inspect PNGs `vmstat/png/*z_r.png` and `*z_r per core.png` for Manipal (two lines, HT band clause), EKA (presented cores/vCPUs, steal clause), IDEM (vCPUs, %RDY clause), AIX (logical CPUs, no HT/VM clause). Footnote not clipped; legend readable.
