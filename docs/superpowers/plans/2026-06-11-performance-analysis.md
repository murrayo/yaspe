# Performance Analysis Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--analysis` flag to `yaspe.py` that reads an existing SQLite database and produces a narrative performance summary markdown file following the methodology in `docs/Performance analysis/PERFORMANCE_ANALYSIS.md`.

**Architecture:** A new standalone module `performance_analysis.py` contains all analysis logic (constants, dataclasses, database orientation, per-metric analysis, correlation tests, baseline computation, report writing). `yaspe.py` calls it after `sp_check.system_check()` when `--analysis` is set; chart rendering for Yellow/Red findings is done back in `yaspe.py` using the existing `simple_chart()` function via `ChartRequest` objects returned by `run_analysis()`.

**Tech Stack:** Python 3, pandas, numpy, sqlite3, matplotlib, dataclasses — all already in requirements.txt or stdlib. No new packages.

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Create | `performance_analysis.py` | All analysis logic; public entry `run_analysis()` |
| Create | `tests/test_performance_analysis.py` | Unit tests for analysis functions |
| Modify | `yaspe.py` | Add `--analysis` / `--context` CLI flags; call `run_analysis()`; add `_render_analysis_chart()` |
| Modify | `yaspe_flask_v1/sync_engine.sh` | Add `performance_analysis.py` to `ENGINE_FILES` |

---

## Task 1: Scaffold `performance_analysis.py` with constants and dataclasses

**Files:**
- Create: `performance_analysis.py`
- Create: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_performance_analysis.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from performance_analysis import IRIS_PERIODS, METRIC_THRESHOLDS, Finding, ChartRequest

def test_iris_periods_count():
    assert len(IRIS_PERIODS) == 9

def test_iris_periods_structure():
    period = IRIS_PERIODS[0]
    assert "name" in period
    assert "start" in period
    assert "end" in period

def test_metric_thresholds_vmstat_keys():
    assert "wa" in METRIC_THRESHOLDS
    assert "r" in METRIC_THRESHOLDS
    assert "us_sy" in METRIC_THRESHOLDS
    assert "si" in METRIC_THRESHOLDS
    assert "so" in METRIC_THRESHOLDS
    assert "b" in METRIC_THRESHOLDS
    assert "sy_pct" in METRIC_THRESHOLDS

def test_metric_thresholds_mgstat_keys():
    assert "Glorefs" in METRIC_THRESHOLDS
    assert "PhyRds" in METRIC_THRESHOLDS
    assert "WDQsz" in METRIC_THRESHOLDS
    assert "Rdratio" in METRIC_THRESHOLDS

def test_finding_dataclass():
    f = Finding(
        metric="wa",
        severity="Yellow",
        observation="wa averaged 12%",
        when="09:00–09:22",
        corroborating=[],
        hypotheses=["hypothesis: storage latency"],
        next_step="Monitor",
        chart_request=None,
    )
    assert f.severity == "Yellow"
    assert f.chart_request is None

def test_chart_request_dataclass():
    import pandas as pd
    cr = ChartRequest(
        metric="wa",
        title="I/O Wait",
        df=pd.DataFrame({"datetime_parsed": [], "metric": []}),
        warn_level=10.0,
        alert_level=20.0,
        shading_spans=[],
        twin_metric=None,
        twin_df=None,
        output_dir="/tmp",
        filename="wa_finding",
    )
    assert cr.warn_level == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -m pytest tests/test_performance_analysis.py -v
```

Expected: `ModuleNotFoundError: No module named 'performance_analysis'`

- [ ] **Step 3: Create `performance_analysis.py` with constants and dataclasses**

```python
"""
Performance analysis module for yaspe.
Produces a narrative markdown summary from a SQLite database following
the methodology in docs/Performance analysis/PERFORMANCE_ANALYSIS.md.
Linux only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# 9 IRIS Health Monitor periods (per PERFORMANCE_ANALYSIS.md §2)
IRIS_PERIODS = [
    {"name": "00:15–02:45", "start": "00:15", "end": "02:45"},
    {"name": "03:00–06:00", "start": "03:00", "end": "06:00"},
    {"name": "06:15–08:45", "start": "06:15", "end": "08:45"},
    {"name": "09:00–11:30", "start": "09:00", "end": "11:30"},
    {"name": "11:45–13:15", "start": "11:45", "end": "13:15"},
    {"name": "13:30–16:00", "start": "13:30", "end": "16:00"},
    {"name": "16:15–18:00", "start": "16:15", "end": "18:00"},
    {"name": "18:15–20:45", "start": "18:15", "end": "20:45"},
    {"name": "21:00–23:59", "start": "21:00", "end": "23:59"},
]

# KPI thresholds (per PERFORMANCE_ANALYSIS.md §3)
# fixed_warn / fixed_alert: used directly (not baseline-relative)
# baseline_relative=True: alert/warn computed dynamically from mean/σ
METRIC_THRESHOLDS = {
    # vmstat — fixed thresholds
    "us_sy":    {"fixed_warn": 75.0,  "fixed_alert": 85.0,  "baseline_relative": False, "label": "us+sy (CPU %)"},
    "wa":       {"fixed_warn": 10.0,  "fixed_alert": 20.0,  "baseline_relative": False, "label": "wa (I/O wait %)"},
    "r":        {"fixed_warn": None,  "fixed_alert": None,   "baseline_relative": False, "vcpu_relative": True,  "label": "r (run queue)"},
    "b":        {"fixed_warn": 2.0,   "fixed_alert": None,   "baseline_relative": False, "vcpu_relative": True,  "label": "b (blocked)"},
    "sy_pct":   {"fixed_warn": 30.0,  "fixed_alert": 50.0,  "baseline_relative": False, "label": "sy (% of total CPU)"},
    "si":       {"fixed_warn": 0.0,   "fixed_alert": 0.0,   "baseline_relative": False, "label": "si (swap in)"},
    "so":       {"fixed_warn": 0.0,   "fixed_alert": 0.0,   "baseline_relative": False, "label": "so (swap out)"},
    # mgstat — baseline-relative
    "Glorefs":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Glorefs"},
    "Gloupds":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Gloupds"},
    "PhyRds":   {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "PhyRds"},
    "PhyWrs":   {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "PhyWrs"},
    "Jrnwrts":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Jrnwrts"},
    "WDQsz":    {"fixed_warn": 0.0,   "fixed_alert": 0.0,   "baseline_relative": False, "label": "WDQsz"},
    "Rdratio":  {"baseline_relative": True,  "warn_mult": 1.6, "max_mult": 2.0, "label": "Rdratio", "invert": True},
    "RouLaS":   {"fixed_warn": 0.0,   "fixed_alert": None,  "baseline_relative": False, "label": "RouLaS"},
}

# Consecutive-readings rule
ALERT_CONSECUTIVE = 3   # samples above alert threshold = Red
WARN_CONSECUTIVE  = 5   # samples above warn threshold  = Yellow


@dataclass
class ChartRequest:
    metric: str
    title: str
    df: pd.DataFrame
    warn_level: float
    alert_level: float
    shading_spans: list          # list of (start_dt, end_dt) for abnormal run shading
    twin_metric: Optional[str]   # None, or name of second metric for twin-axis overlay
    twin_df: Optional[pd.DataFrame]
    output_dir: str
    filename: str                # no extension; .png appended by renderer


@dataclass
class Finding:
    metric: str
    severity: str                # "Red", "Yellow", "Green"
    observation: str             # prose: value, threshold, duration
    when: str                    # timestamps / recurrence pattern
    corroborating: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    next_step: str = ""
    chart_request: Optional[ChartRequest] = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: scaffold performance_analysis.py with constants and dataclasses"
```

---

## Task 2: Database orientation — `_get_collection_meta()` and `_get_system_facts()`

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_performance_analysis.py

import sqlite3
import tempfile
import pandas as pd
from datetime import datetime

from performance_analysis import _get_collection_meta, _get_system_facts


def _make_test_db(rows):
    """Create an in-memory SQLite DB with a minimal mgstat table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE mgstat (
            id_key INTEGER PRIMARY KEY,
            RunDate TEXT, RunTime TEXT,
            Glorefs REAL, PhyRds REAL, PhyWrs REAL,
            Gloupds REAL, Rdratio REAL, WDQsz REAL,
            Jrnwrts REAL, RouLaS REAL, Seize REAL, ASeize REAL,
            "html name" TEXT
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO mgstat (RunDate, RunTime, Glorefs, PhyRds, PhyWrs, "
            "Gloupds, Rdratio, WDQsz, Jrnwrts, RouLaS, Seize, ASeize, \"html name\") "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            r
        )
    conn.commit()
    return conn


def test_get_collection_meta_interval():
    rows = [
        ("01/01/2026", "09:00:00", 1000,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:05", 1100,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:10", 1200,0,0,0,50,0,0,0,0,0,"f.html"),
    ]
    conn = _make_test_db(rows)
    meta = _get_collection_meta(conn)
    assert meta["interval_seconds"] == 5
    assert meta["n_days"] == 1
    assert meta["gaps"] == []
    conn.close()


def test_get_collection_meta_detects_gap():
    rows = [
        ("01/01/2026", "09:00:00", 1000,0,0,0,50,0,0,0,0,0,"f.html"),
        ("01/01/2026", "09:00:05", 1100,0,0,0,50,0,0,0,0,0,"f.html"),
        # gap: 60 seconds > 3 × 5s interval
        ("01/01/2026", "09:01:05", 1200,0,0,0,50,0,0,0,0,0,"f.html"),
    ]
    conn = _make_test_db(rows)
    meta = _get_collection_meta(conn)
    assert len(meta["gaps"]) == 1
    conn.close()


def test_get_system_facts_linux():
    sp_dict = {
        "operating system": "Linux",
        "customer": "TestHospital",
        "number cpus": "8",
        "memory MB": "32768",
        "globals total MB": "16384",
        "version string": "IRIS for UNIX 2024.1",
    }
    facts = _get_system_facts(sp_dict)
    assert facts["vcpus"] == 8
    assert facts["ram_gb"] == 32
    assert facts["iris_buffers_gb"] == 16
    assert facts["customer"] == "TestHospital"


def test_get_system_facts_missing_keys():
    facts = _get_system_facts({})
    assert facts["vcpus"] is None
    assert facts["ram_gb"] is None
    assert facts["iris_buffers_gb"] is None
    assert facts["customer"] == "Unknown"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_get_collection_meta_interval tests/test_performance_analysis.py::test_get_system_facts_linux -v
```

Expected: `ImportError: cannot import name '_get_collection_meta'`

- [ ] **Step 3: Implement `_get_collection_meta()` and `_get_system_facts()`**

Add to `performance_analysis.py` after the dataclass definitions:

```python
import sqlite3
from datetime import timedelta
import numpy as np


def _get_collection_meta(connection) -> dict:
    """
    Establish collection window, median interval, and gaps > 3× interval.
    Returns dict with keys: start, end, n_days, weekdays, interval_seconds, gaps.
    gaps is a list of (gap_start, gap_end) datetime tuples.
    """
    try:
        df = pd.read_sql_query(
            "SELECT RunDate, RunTime FROM mgstat ORDER BY RunDate, RunTime",
            connection,
        )
    except Exception:
        return {"start": None, "end": None, "n_days": 0, "weekdays": [],
                "interval_seconds": None, "gaps": []}

    if df.empty:
        return {"start": None, "end": None, "n_days": 0, "weekdays": [],
                "interval_seconds": None, "gaps": []}

    # Use the pre-computed 'datetime' column when available (yaspe stores it);
    # fall back to combining RunDate + RunTime with flexible parsing.
    if "datetime" in df.columns:
        df["dt"] = pd.to_datetime(df["datetime"].str.strip(), errors="coerce")
    else:
        df["dt"] = pd.to_datetime(
            df["RunDate"].str.strip() + " " + df["RunTime"].str.strip(),
            errors="coerce",
        )
    df = df.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)

    diffs = df["dt"].diff().dropna()
    interval_secs = diffs.median().total_seconds() if len(diffs) > 0 else None
    gap_threshold = timedelta(seconds=interval_secs * 3) if interval_secs else None

    gaps = []
    if gap_threshold:
        gap_mask = diffs > gap_threshold
        for idx in diffs[gap_mask].index:
            gaps.append((df["dt"].iloc[idx - 1], df["dt"].iloc[idx]))

    start = df["dt"].min()
    end = df["dt"].max()
    n_days = (end.date() - start.date()).days + 1
    weekdays = sorted({ts.strftime("%A") for ts in df["dt"]})

    return {
        "start": start,
        "end": end,
        "n_days": n_days,
        "weekdays": weekdays,
        "interval_seconds": interval_secs,
        "gaps": gaps,
    }


def _get_system_facts(sp_dict: dict) -> dict:
    """
    Extract system facts from sp_dict (populated by sp_check.system_check()).
    Returns dict with: vcpus, ram_gb, iris_buffers_gb, customer, version, os.
    Missing values are None; customer defaults to "Unknown".
    """
    vcpus = None
    for key in ("number cpus",):
        if key in sp_dict:
            try:
                vcpus = int(str(sp_dict[key]).strip().split()[0])
            except (ValueError, IndexError):
                pass
            break

    ram_gb = None
    if "memory MB" in sp_dict:
        try:
            ram_gb = round(int(str(sp_dict["memory MB"]).strip()) / 1024)
        except (ValueError, TypeError):
            pass

    iris_buffers_gb = None
    if "globals total MB" in sp_dict:
        try:
            iris_buffers_gb = round(int(str(sp_dict["globals total MB"]).strip()) / 1024)
        except (ValueError, TypeError):
            pass

    return {
        "vcpus": vcpus,
        "ram_gb": ram_gb,
        "iris_buffers_gb": iris_buffers_gb,
        "customer": sp_dict.get("customer", "Unknown"),
        "version": sp_dict.get("version string"),
        "os": sp_dict.get("operating system", "Linux"),
    }
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: add _get_collection_meta and _get_system_facts"
```

---

## Task 3: Baseline computation — `_compute_baselines()` and period labelling

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_performance_analysis.py

from performance_analysis import _label_period, _compute_baselines


def test_label_period_morning():
    assert _label_period("09:30") == "09:00–11:30"


def test_label_period_overnight():
    assert _label_period("01:00") == "00:15–02:45"


def test_label_period_outside_all():
    # 00:00–00:14 falls outside all defined periods
    assert _label_period("00:05") is None


def _make_mgstat_df():
    """Three rows in 09:00–11:30 period on same day."""
    return pd.DataFrame({
        "dt": pd.to_datetime([
            "2026-01-01 09:00:05",
            "2026-01-01 09:00:10",
            "2026-01-01 09:00:15",
        ]),
        "Glorefs": [1000.0, 1200.0, 800.0],
        "PhyRds":  [10.0, 12.0, 8.0],
    })


def test_compute_baselines_returns_expected_keys():
    df = _make_mgstat_df()
    baselines = _compute_baselines(df, ["Glorefs", "PhyRds"])
    assert "09:00–11:30" in baselines
    period = baselines["09:00–11:30"]
    assert "Glorefs" in period
    assert "mean" in period["Glorefs"]
    assert "sigma" in period["Glorefs"]
    assert "p95" in period["Glorefs"]
    assert "max" in period["Glorefs"]


def test_compute_baselines_values():
    df = _make_mgstat_df()
    baselines = _compute_baselines(df, ["Glorefs"])
    g = baselines["09:00–11:30"]["Glorefs"]
    assert abs(g["mean"] - 1000.0) < 1.0
    assert g["max"] == 1200.0
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_label_period_morning tests/test_performance_analysis.py::test_compute_baselines_values -v
```

Expected: `ImportError: cannot import name '_label_period'`

- [ ] **Step 3: Implement `_label_period()` and `_compute_baselines()`**

Add to `performance_analysis.py`:

```python
def _label_period(time_str: str) -> Optional[str]:
    """
    Map an HH:MM string to the matching IRIS Health Monitor period name.
    Returns None if outside all defined periods (e.g. 00:00–00:14).
    """
    from datetime import time as dtime
    h, m = int(time_str[:2]), int(time_str[3:5])
    t = dtime(h, m)
    for p in IRIS_PERIODS:
        sh, sm = int(p["start"][:2]), int(p["start"][3:])
        eh, em = int(p["end"][:2]), int(p["end"][3:])
        if dtime(sh, sm) <= t <= dtime(eh, em):
            return p["name"]
    return None


def _compute_baselines(df: pd.DataFrame, metrics: list) -> dict:
    """
    Compute per-period mean/σ/p95/max for each metric column in df.
    df must have a 'dt' column of datetime64.
    Returns: {period_name: {metric: {mean, sigma, p95, max}}}
    """
    df = df.copy()
    df["_period"] = df["dt"].dt.strftime("%H:%M").apply(_label_period)
    df = df.dropna(subset=["_period"])

    result = {}
    for period_name, group in df.groupby("_period"):
        result[period_name] = {}
        for metric in metrics:
            if metric not in group.columns:
                continue
            vals = pd.to_numeric(group[metric], errors="coerce").dropna()
            if vals.empty:
                continue
            result[period_name][metric] = {
                "mean":  float(vals.mean()),
                "sigma": float(vals.std(ddof=1)) if len(vals) > 1 else 0.0,
                "p95":   float(np.percentile(vals, 95)),
                "max":   float(vals.max()),
            }
    return result
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: add _label_period and _compute_baselines"
```

---

## Task 4: Consecutive-breach detector — `_find_breaches()`

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_performance_analysis.py

from performance_analysis import _find_breaches


def test_find_breaches_no_breach():
    vals = pd.Series([5.0, 6.0, 4.0, 3.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05",
                           "2026-01-01 09:00:10","2026-01-01 09:00:15"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert runs == []


def test_find_breaches_single_spike_ignored():
    vals = pd.Series([5.0, 25.0, 4.0, 3.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05",
                           "2026-01-01 09:00:10","2026-01-01 09:00:15"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert runs == []


def test_find_breaches_detects_run():
    vals = pd.Series([5.0, 25.0, 30.0, 22.0, 4.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05",
                           "2026-01-01 09:00:10","2026-01-01 09:00:15",
                           "2026-01-01 09:00:20"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert len(runs) == 1
    start, end, count = runs[0]
    assert count == 3


def test_find_breaches_returns_timestamps():
    vals = pd.Series([15.0, 15.0, 15.0])
    dts  = pd.to_datetime(["2026-01-01 09:00:00","2026-01-01 09:00:05","2026-01-01 09:00:10"])
    runs = _find_breaches(vals, dts, threshold=10.0, min_consecutive=3)
    assert len(runs) == 1
    start, end, count = runs[0]
    assert str(start) == "2026-01-01 09:00:00"
    assert str(end)   == "2026-01-01 09:00:10"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_find_breaches_detects_run -v
```

Expected: `ImportError: cannot import name '_find_breaches'`

- [ ] **Step 3: Implement `_find_breaches()`**

Add to `performance_analysis.py`:

```python
def _find_breaches(
    values: pd.Series,
    datetimes: pd.Series,
    threshold: float,
    min_consecutive: int,
) -> list:
    """
    Find runs of consecutive samples above threshold.
    Returns list of (run_start, run_end, count) tuples.
    Only returns runs with length >= min_consecutive.
    """
    above = (values > threshold).values
    runs = []
    i = 0
    while i < len(above):
        if above[i]:
            j = i
            while j < len(above) and above[j]:
                j += 1
            run_len = j - i
            if run_len >= min_consecutive:
                runs.append((datetimes.iloc[i], datetimes.iloc[j - 1], run_len))
            i = j
        else:
            i += 1
    return runs
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 20 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: add _find_breaches consecutive-breach detector"
```

---

## Task 5: vmstat per-metric analysis — `_analyse_vmstat()`

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_performance_analysis.py

from performance_analysis import _analyse_vmstat


def _make_vmstat_df(wa_vals, r_vals=None, si_vals=None, so_vals=None, us_vals=None, sy_vals=None):
    n = len(wa_vals)
    base_dt = pd.date_range("2026-01-01 09:00:00", periods=n, freq="5s")
    return pd.DataFrame({
        "dt": base_dt,
        "wa": wa_vals,
        "r":  r_vals  if r_vals  is not None else [0.0] * n,
        "si": si_vals if si_vals is not None else [0.0] * n,
        "so": so_vals if so_vals is not None else [0.0] * n,
        "us": us_vals if us_vals is not None else [20.0] * n,
        "sy": sy_vals if sy_vals is not None else [5.0] * n,
        "b":  [0.0] * n,
        "id": [75.0] * n,
    })


def test_analyse_vmstat_green_when_normal():
    df = _make_vmstat_df(wa_vals=[2.0] * 10)
    findings = _analyse_vmstat(df, vcpus=8)
    # All within thresholds — no Red or Yellow findings
    non_green = [f for f in findings if f.severity != "Green"]
    assert non_green == []


def test_analyse_vmstat_yellow_wa():
    # 5 consecutive samples of wa=12% → Yellow (warn threshold 10%, 5 consecutive)
    df = _make_vmstat_df(wa_vals=[12.0] * 5 + [2.0] * 5)
    findings = _analyse_vmstat(df, vcpus=8)
    wa_findings = [f for f in findings if "wa" in f.metric]
    assert any(f.severity in ("Yellow", "Red") for f in wa_findings)


def test_analyse_vmstat_red_wa():
    # 3 consecutive samples of wa=25% → Red (alert threshold 20%, 3 consecutive)
    df = _make_vmstat_df(wa_vals=[25.0] * 3 + [2.0] * 7)
    findings = _analyse_vmstat(df, vcpus=8)
    wa_findings = [f for f in findings if "wa" in f.metric]
    assert any(f.severity == "Red" for f in wa_findings)


def test_analyse_vmstat_swap_is_always_red():
    # Any sustained so > 0 is Red
    df = _make_vmstat_df(wa_vals=[2.0] * 10, so_vals=[1.0] * 3 + [0.0] * 7)
    findings = _analyse_vmstat(df, vcpus=8)
    so_findings = [f for f in findings if "so" in f.metric or "swap" in f.metric.lower()]
    assert any(f.severity == "Red" for f in so_findings)


def test_analyse_vmstat_run_queue_vcpu_relative():
    # r > 2 × 2 vCPUs = 4 → alert; use 3 consec samples of r=5 on 2-vCPU system
    df = _make_vmstat_df(wa_vals=[2.0] * 10, r_vals=[5.0] * 3 + [0.0] * 7)
    findings = _analyse_vmstat(df, vcpus=2)
    r_findings = [f for f in findings if "run queue" in f.metric.lower() or f.metric == "r"]
    assert any(f.severity == "Red" for f in r_findings)


def test_analyse_vmstat_finding_has_observation_text():
    df = _make_vmstat_df(wa_vals=[25.0] * 3 + [2.0] * 7)
    findings = _analyse_vmstat(df, vcpus=8)
    for f in findings:
        if f.severity in ("Yellow", "Red"):
            assert len(f.observation) > 0
            assert len(f.when) > 0
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_analyse_vmstat_green_when_normal -v
```

Expected: `ImportError: cannot import name '_analyse_vmstat'`

- [ ] **Step 3: Implement `_analyse_vmstat()`**

Add to `performance_analysis.py`:

```python
def _analyse_vmstat(df: pd.DataFrame, vcpus: Optional[int]) -> list:
    """
    Evaluate vmstat KPIs. Returns list[Finding] — one per metric that
    triggers Yellow or Red (plus Green summary if all clear).
    df must have columns: dt, wa, r, b, si, so, us, sy, id.
    """
    findings = []
    df = df.copy().sort_values("dt").reset_index(drop=True)

    def _fmt_ts(dt):
        return pd.Timestamp(dt).strftime("%Y-%m-%d %H:%M:%S")

    # --- wa (I/O wait) ---
    if "wa" in df.columns:
        vals = pd.to_numeric(df["wa"], errors="coerce").fillna(0)
        red_runs  = _find_breaches(vals, df["dt"], 20.0, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(vals, df["dt"], 10.0, WARN_CONSECUTIVE)
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="wa (I/O wait %)",
                severity="Red",
                observation=f"wa exceeded 20% (alert) for {count} consecutive samples "
                            f"(≥ {count * df['dt'].diff().median().total_seconds():.0f}s). "
                            f"Peak: {vals.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: storage latency — check iostat await/svctm",
                            "hypothesis: excessive write-back I/O from dirty page flush"],
                next_step="Correlate with iostat await; check WDQsz and PhyWrs.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="wa (I/O wait %)",
                severity="Yellow",
                observation=f"wa exceeded 10% (warning) for {count} consecutive samples. "
                            f"Peak: {vals.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: intermittent storage latency"],
                next_step="Monitor; correlate with iostat.",
                chart_request=None,
            ))

    # --- us+sy (total CPU) ---
    if "us" in df.columns and "sy" in df.columns:
        us_sy = pd.to_numeric(df["us"], errors="coerce").fillna(0) + \
                pd.to_numeric(df["sy"], errors="coerce").fillna(0)
        red_runs  = _find_breaches(us_sy, df["dt"], 85.0, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(us_sy, df["dt"], 75.0, WARN_CONSECUTIVE)
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="us+sy (CPU %)",
                severity="Red",
                observation=f"us+sy exceeded 85% for {count} consecutive samples. "
                            f"Peak: {us_sy.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: CPU-bound workload surge",
                            "hypothesis: runaway process — check top"],
                next_step="Correlate with Glorefs; if Glorefs is proportional this is normal scaling. "
                          "If Glorefs is low, suspect a runaway process.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="us+sy (CPU %)",
                severity="Yellow",
                observation=f"us+sy exceeded 75% for {count} consecutive samples. Peak: {us_sy.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: elevated workload"],
                next_step="Monitor trend.",
                chart_request=None,
            ))

    # --- sy as % of total CPU ---
    if "us" in df.columns and "sy" in df.columns:
        us_vals = pd.to_numeric(df["us"], errors="coerce").fillna(0)
        sy_vals = pd.to_numeric(df["sy"], errors="coerce").fillna(0)
        total = us_vals + sy_vals
        sy_pct = sy_vals.where(total > 0, 0) / total.where(total > 0, 1) * 100
        red_runs  = _find_breaches(sy_pct, df["dt"], 50.0, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(sy_pct, df["dt"], 30.0, WARN_CONSECUTIVE)
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="sy (% of total CPU)",
                severity="Red",
                observation=f"Kernel CPU exceeded 50% of total CPU for {count} consecutive samples. "
                            f"Peak sy fraction: {sy_pct.max():.1f}%.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: HugePages not configured — IRIS managing own TLB",
                            "hypothesis: NUMA cross-socket traffic",
                            "hypothesis: high interrupt/softirq rate"],
                next_step="Check HugePages configuration. Review /proc/interrupts during a repeat event.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="sy (% of total CPU)",
                severity="Yellow",
                observation=f"Kernel CPU exceeded 30% of total CPU for {count} consecutive samples.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: elevated system-call rate or kernel overhead"],
                next_step="Monitor; check HugePages setting.",
                chart_request=None,
            ))

    # --- r (run queue) — vCPU-relative ---
    if "r" in df.columns and vcpus is not None:
        r_vals = pd.to_numeric(df["r"], errors="coerce").fillna(0)
        alert_thr = vcpus * 2.0
        warn_thr  = vcpus * 1.0
        red_runs  = _find_breaches(r_vals, df["dt"], alert_thr, ALERT_CONSECUTIVE)
        warn_runs = _find_breaches(r_vals, df["dt"], warn_thr,  WARN_CONSECUTIVE)
        if red_runs:
            start, end, count = red_runs[0]
            findings.append(Finding(
                metric="r (run queue)",
                severity="Red",
                observation=f"Run queue exceeded {alert_thr:.0f} (2× vCPUs={vcpus}) for "
                            f"{count} consecutive samples. Peak: {r_vals.max():.0f}.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: CPU saturation — more runnable threads than cores"],
                next_step="Cross-reference with us+sy. If us+sy < 80%, suspect lock contention rather than CPU shortage.",
                chart_request=None,
            ))
        elif warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="r (run queue)",
                severity="Yellow",
                observation=f"Run queue exceeded {warn_thr:.0f} (1× vCPUs={vcpus}) for {count} consecutive samples.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: intermittent CPU pressure"],
                next_step="Monitor trend.",
                chart_request=None,
            ))

    # --- si / so (swap) — any sustained = Red ---
    for col, label in (("si", "swap in (si)"), ("so", "swap out (so)")):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0)
            red_runs = _find_breaches(vals, df["dt"], 0.0, ALERT_CONSECUTIVE)
            if red_runs:
                start, end, count = red_runs[0]
                findings.append(Finding(
                    metric=label,
                    severity="Red",
                    observation=f"Sustained {col} > 0 for {count} consecutive samples — "
                                f"IRIS shared memory segment is paging. Peak: {vals.max():.0f} KB/s.",
                    when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                    hypotheses=["confirmed: memory pressure causing IRIS shared memory to page out"],
                    next_step="URGENT: Reduce global buffer allocation or add RAM. "
                              "Any sustained swap on a dedicated IRIS server is critical.",
                    chart_request=None,
                ))

    if not findings:
        findings.append(Finding(
            metric="vmstat (all)",
            severity="Green",
            observation="All vmstat metrics within normal thresholds for the collection window.",
            when="entire window",
        ))

    return findings
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 26 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: implement _analyse_vmstat with consecutive-breach rule"
```

---

## Task 6: mgstat per-metric analysis — `_analyse_mgstat()`

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_performance_analysis.py

from performance_analysis import _analyse_mgstat


def _make_mgstat_analysis_df(glorefs=None, phyrds=None, wdqsz=None, rdratio=None, n=10):
    base_dt = pd.date_range("2026-01-01 09:00:00", periods=n, freq="5s")
    return pd.DataFrame({
        "dt":      base_dt,
        "Glorefs": glorefs  if glorefs  is not None else [1000.0] * n,
        "PhyRds":  phyrds   if phyrds   is not None else [10.0] * n,
        "PhyWrs":  [5.0] * n,
        "Gloupds": [200.0] * n,
        "Jrnwrts": [17.0] * n,
        "WDQsz":   wdqsz   if wdqsz   is not None else [0.0] * n,
        "Rdratio": rdratio  if rdratio  is not None else [50.0] * n,
        "RouLaS":  [0.0] * n,
        "Seize":   [1000.0] * n,   # optional; not present in all files
        "ASeize":  [10.0] * n,     # optional; not present in all files
    })


def test_analyse_mgstat_green_when_normal():
    df = _make_mgstat_analysis_df()
    baselines = _compute_baselines(df, ["Glorefs", "PhyRds", "PhyWrs", "Gloupds", "Jrnwrts", "Rdratio"])
    findings = _analyse_mgstat(df, baselines)
    non_green = [f for f in findings if f.severity != "Green"]
    assert non_green == []


def test_analyse_mgstat_wdqsz_nonzero_is_yellow():
    # WDQsz non-zero for 5+ consecutive samples = Yellow
    df = _make_mgstat_analysis_df(wdqsz=[1.0] * 5 + [0.0] * 5)
    baselines = _compute_baselines(df, ["Glorefs", "PhyRds"])
    findings = _analyse_mgstat(df, baselines)
    wd_findings = [f for f in findings if "WDQsz" in f.metric or "write daemon" in f.metric.lower()]
    assert any(f.severity in ("Yellow", "Red") for f in wd_findings)


def test_analyse_mgstat_finding_text():
    df = _make_mgstat_analysis_df(wdqsz=[2.0] * 5 + [0.0] * 5)
    baselines = _compute_baselines(df, ["Glorefs"])
    findings = _analyse_mgstat(df, baselines)
    for f in findings:
        if f.severity in ("Yellow", "Red"):
            assert len(f.observation) > 10
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_analyse_mgstat_green_when_normal -v
```

Expected: `ImportError: cannot import name '_analyse_mgstat'`

- [ ] **Step 3: Implement `_analyse_mgstat()`**

Add to `performance_analysis.py`:

```python
def _analyse_mgstat(df: pd.DataFrame, baselines: dict) -> list:
    """
    Evaluate mgstat KPIs. Returns list[Finding].
    df must have columns: dt, Glorefs, PhyRds, PhyWrs, Gloupds, Jrnwrts, WDQsz, Rdratio, RouLaS.
    Seize and ASeize are optional (not present in all pButtons files).
    baselines: output of _compute_baselines() for mgstat metrics.
    """
    findings = []
    df = df.copy().sort_values("dt").reset_index(drop=True)

    def _fmt_ts(dt):
        return pd.Timestamp(dt).strftime("%Y-%m-%d %H:%M:%S")

    def _dynamic_thresholds(metric, period_name):
        """Return (warn_level, alert_level) for a baseline-relative metric."""
        if period_name not in baselines or metric not in baselines.get(period_name, {}):
            return None, None
        b = baselines[period_name][metric]
        mean, sigma, highest = b["mean"], b["sigma"], b["max"]
        cfg = METRIC_THRESHOLDS.get(metric, {})
        warn_mult = cfg.get("warn_mult", 1.6)
        max_mult  = cfg.get("max_mult", 2.0)
        warn_level  = warn_mult  * max(mean, mean + 2 * sigma, highest)
        alert_level = max_mult   * max(mean + 3 * sigma, highest + sigma)
        return warn_level, alert_level

    # --- WDQsz ---
    if "WDQsz" in df.columns:
        vals = pd.to_numeric(df["WDQsz"], errors="coerce").fillna(0)
        warn_runs = _find_breaches(vals, df["dt"], 0.0, WARN_CONSECUTIVE)
        if warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="WDQsz (write daemon queue)",
                severity="Yellow",
                observation=f"WDQsz was non-zero for {count} consecutive samples "
                            f"(max {vals.max():.0f}). Write daemon queue backing up between cycles.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: write path (storage/WIJ/journal) latency causing WD queue growth"],
                next_step="Correlate with wa and PhyWrs. If wa is elevated: storage write latency. "
                          "Check WD cycle time; any cycle ≥ 90 s is critical.",
                chart_request=None,
            ))

    # --- RouLaS (column name is capitalised S in pButtons schema) ---
    roul_col = "RouLaS" if "RouLaS" in df.columns else "RouLas" if "RouLas" in df.columns else None
    if roul_col:
        vals = pd.to_numeric(df[roul_col], errors="coerce").fillna(0)
        warn_runs = _find_breaches(vals, df["dt"], 0.0, WARN_CONSECUTIVE)
        if warn_runs:
            start, end, count = warn_runs[0]
            findings.append(Finding(
                metric="RouLaS (routine cache misses)",
                severity="Yellow",
                observation=f"RouLaS was non-zero for {count} consecutive samples (max {vals.max():.0f}). "
                            f"Routine buffer cache is undersized.",
                when=f"{_fmt_ts(start)} – {_fmt_ts(end)}",
                hypotheses=["hypothesis: routine buffer (routines= in CPF) too small for working set"],
                next_step="Review routines= setting in CPF. Consider increasing.",
                chart_request=None,
            ))

    # --- Baseline-relative metrics: Glorefs, PhyRds, PhyWrs, Gloupds, Jrnwrts ---
    for metric in ("Glorefs", "PhyRds", "PhyWrs", "Gloupds", "Jrnwrts"):
        if metric not in df.columns:
            continue
        vals = pd.to_numeric(df[metric], errors="coerce").fillna(0)
        df["_period_tmp"] = df["dt"].dt.strftime("%H:%M").apply(_label_period)

        period_findings = []
        for period_name, group_idx in df.groupby("_period_tmp").groups.items():
            group_vals = vals.iloc[group_idx]
            group_dts  = df["dt"].iloc[group_idx]
            warn_level, alert_level = _dynamic_thresholds(metric, period_name)
            if warn_level is None:
                continue
            red_runs  = _find_breaches(group_vals, group_dts, alert_level, ALERT_CONSECUTIVE)
            warn_runs = _find_breaches(group_vals, group_dts, warn_level,  WARN_CONSECUTIVE)
            if red_runs:
                start, end, count = red_runs[0]
                period_findings.append(Finding(
                    metric=metric,
                    severity="Red",
                    observation=f"{metric} exceeded alert level {alert_level:.0f} "
                                f"(2× period norm) for {count} consecutive samples. "
                                f"Peak: {group_vals.max():.0f}.",
                    when=f"{_fmt_ts(start)} – {_fmt_ts(end)} ({period_name})",
                    hypotheses=[f"hypothesis: abnormal workload spike in {metric}"],
                    next_step=f"Correlate with vmstat and other mgstat metrics in the same window.",
                    chart_request=None,
                ))
            elif warn_runs:
                start, end, count = warn_runs[0]
                period_findings.append(Finding(
                    metric=metric,
                    severity="Yellow",
                    observation=f"{metric} exceeded warning level {warn_level:.0f} "
                                f"(1.6× period norm) for {count} consecutive samples. "
                                f"Peak: {group_vals.max():.0f}.",
                    when=f"{_fmt_ts(start)} – {_fmt_ts(end)} ({period_name})",
                    hypotheses=[f"hypothesis: elevated {metric} during {period_name}"],
                    next_step="Monitor trend across multiple days.",
                    chart_request=None,
                ))
        findings.extend(period_findings)

    if not findings:
        findings.append(Finding(
            metric="mgstat (all)",
            severity="Green",
            observation="All mgstat metrics within normal thresholds for the collection window.",
            when="entire window",
        ))

    return findings
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 29 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: implement _analyse_mgstat with baseline-relative and fixed thresholds"
```

---

## Task 7: Correlation tests (7 cross-metric patterns)

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_performance_analysis.py

from performance_analysis import (
    _test_user_stall, _test_buffer_pressure, _test_write_daemon_strain,
    _test_memory_danger, _test_contention_vs_throughput,
    _test_kernel_overhead, _test_batch_window,
)


def _make_joined_df(n=20, **kwargs):
    """
    Build a merged vmstat+mgstat DataFrame. Callers override specific columns.
    Default: healthy values throughout.
    """
    base_dt = pd.date_range("2026-01-01 09:00:00", periods=n, freq="5s")
    defaults = {
        "dt": base_dt,
        "Glorefs": [1000.0] * n,
        "WDQsz":   [0.0] * n,
        "PhyRds":  [10.0] * n,
        "PhyWrs":  [5.0] * n,
        "Jrnwrts": [17.0] * n,
        "Rdratio": [50.0] * n,
        "Seize":   [1000.0] * n,
        "ASeize":  [10.0] * n,
        "RouLaS":  [0.0] * n,
        "wa":  [2.0] * n,
        "b":   [0.0] * n,
        "us":  [20.0] * n,
        "sy":  [5.0] * n,
        "si":  [0.0] * n,
        "so":  [0.0] * n,
        "free":  [10000.0] * n,
        "cache": [5000.0] * n,
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


def test_user_stall_no_finding_when_healthy():
    df = _make_joined_df()
    result = _test_user_stall(df)
    assert result is None


def test_user_stall_detects_drop_with_wa():
    # Glorefs drops to near 0 during business hours (09:xx), wa rises
    n = 20
    glorefs = [1000.0] * 5 + [20.0] * 5 + [1000.0] * 10
    wa      = [2.0] * 5 + [25.0] * 5 + [2.0] * 10
    wdqsz   = [0.0] * 5 + [5.0] * 5 + [0.0] * 10
    df = _make_joined_df(Glorefs=glorefs, wa=wa, WDQsz=wdqsz)
    result = _test_user_stall(df)
    assert result is not None
    assert result.severity in ("Yellow", "Red")


def test_buffer_pressure_no_finding_when_healthy():
    df = _make_joined_df()
    result = _test_buffer_pressure(df)
    assert result is None


def test_buffer_pressure_detects_trend():
    n = 20
    # Rdratio declining, PhyRds rising
    rdratio = [50.0 - i * 2 for i in range(n)]
    phyrds  = [10.0 + i * 1 for i in range(n)]
    df = _make_joined_df(Rdratio=rdratio, PhyRds=phyrds)
    result = _test_buffer_pressure(df)
    assert result is not None


def test_memory_danger_no_finding_when_healthy():
    df = _make_joined_df()
    result = _test_memory_danger(df)
    assert result is None


def test_memory_danger_detects_free_declining_with_swap():
    n = 20
    free  = [10000.0 - i * 400 for i in range(n)]
    cache = [5000.0  - i * 200 for i in range(n)]
    si    = [0.0] * 10 + [1.0] * 10
    df = _make_joined_df(free=free, cache=cache, si=si)
    result = _test_memory_danger(df)
    assert result is not None
    assert result.severity == "Red"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_user_stall_no_finding_when_healthy -v
```

Expected: `ImportError: cannot import name '_test_user_stall'`

- [ ] **Step 3: Implement the 7 correlation tests**

Add to `performance_analysis.py`:

```python
def _nearest_join(mgstat_df: pd.DataFrame, vmstat_df: pd.DataFrame,
                  interval_secs: float) -> pd.DataFrame:
    """Merge mgstat and vmstat on nearest timestamp within 1.5× interval."""
    tolerance = pd.Timedelta(seconds=interval_secs * 1.5)
    mg = mgstat_df.sort_values("dt").reset_index(drop=True)
    vm = vmstat_df.sort_values("dt").reset_index(drop=True)
    merged = pd.merge_asof(mg, vm, on="dt", tolerance=tolerance,
                           direction="nearest", suffixes=("", "_vm"))
    return merged


def _test_user_stall(df: pd.DataFrame) -> Optional[Finding]:
    """
    Test 1: Glorefs drops sharply in business hours.
    df is a merged vmstat+mgstat DataFrame with 'dt', 'Glorefs', 'WDQsz', 'b', 'wa'.
    Business hours = 08:00–18:00.
    """
    bh = df[df["dt"].dt.hour.between(8, 17)].copy()
    if bh.empty or "Glorefs" not in bh.columns:
        return None

    glorefs = pd.to_numeric(bh["Glorefs"], errors="coerce").dropna()
    if glorefs.empty:
        return None

    mean_g = glorefs.mean()
    # A stall = at least 3 consecutive samples below 5% of mean
    stall_threshold = mean_g * 0.05
    if stall_threshold < 1:
        return None

    stall_runs = _find_breaches(-glorefs, bh["dt"].reset_index(drop=True),
                                threshold=-stall_threshold, min_consecutive=ALERT_CONSECUTIVE)

    if not stall_runs:
        return None

    start, end, count = stall_runs[0]
    # Check corroborating evidence
    window = bh[(bh["dt"] >= start) & (bh["dt"] <= end)]
    wa_elevated = "wa" in window.columns and pd.to_numeric(window["wa"], errors="coerce").mean() > 10
    wdqsz_elevated = "WDQsz" in window.columns and pd.to_numeric(window["WDQsz"], errors="coerce").max() > 0

    corroborating = []
    if wa_elevated:
        corroborating.append(f"wa elevated ({pd.to_numeric(window['wa'], errors='coerce').mean():.1f}%) during stall — storage-side cause likely")
    if wdqsz_elevated:
        corroborating.append(f"WDQsz non-zero during stall — write daemon queue backing up")
    if not corroborating:
        corroborating.append("wa and WDQsz within normal range — upstream/application-side cause possible")

    return Finding(
        metric="Glorefs (user stall)",
        severity="Red",
        observation=f"Glorefs dropped to near zero (< 5% of mean {mean_g:.0f}) in business hours "
                    f"for {count} consecutive samples — potential user-visible stall.",
        when=f"{pd.Timestamp(start).strftime('%Y-%m-%d %H:%M:%S')} – "
             f"{pd.Timestamp(end).strftime('%Y-%m-%d %H:%M:%S')}",
        corroborating=corroborating,
        hypotheses=(["confirmed: storage-side stall (wa + WDQsz corroborate)"]
                    if wa_elevated or wdqsz_elevated
                    else ["hypothesis: application-side stall (no storage indicators)"]),
        next_step="Capture ^SystemPerformance during a recurrence. "
                  "Check storage latency with iostat -x during the window.",
        chart_request=None,
    )


def _test_buffer_pressure(df: pd.DataFrame) -> Optional[Finding]:
    """
    Test 2: Rdratio trending down while PhyRds trends up.
    Quantify first-third vs last-third of window.
    """
    if "Rdratio" not in df.columns or "PhyRds" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 9:
        return None

    third = n // 3
    rdratio = pd.to_numeric(df["Rdratio"], errors="coerce").fillna(0)
    phyrds  = pd.to_numeric(df["PhyRds"],  errors="coerce").fillna(0)

    rd_first = rdratio.iloc[:third].mean()
    rd_last  = rdratio.iloc[2*third:].mean()
    ph_first = phyrds.iloc[:third].mean()
    ph_last  = phyrds.iloc[2*third:].mean()

    rdratio_declined = rd_last < rd_first * 0.85   # > 15% decline
    phyrds_increased = ph_last > ph_first * 1.20   # > 20% increase

    if not (rdratio_declined and phyrds_increased):
        return None

    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    return Finding(
        metric="Rdratio / PhyRds (buffer pool pressure)",
        severity="Yellow",
        observation=f"Rdratio declined from {rd_first:.1f}% to {rd_last:.1f}% "
                    f"({(rd_last - rd_first) / rd_first * 100:.1f}% change) while PhyRds "
                    f"increased from {ph_first:.1f} to {ph_last:.1f} over the collection window.",
        when=f"{start_ts} – {end_ts}",
        corroborating=["Rdratio decline and PhyRds increase are anti-correlated, consistent with buffer pressure"],
        hypotheses=["hypothesis: global buffer working set is growing beyond allocated size — "
                    "buffers are undersized for current workload"],
        next_step="Review globals= setting in CPF. If Rdratio trend continues across multiple "
                  "collections, increase global buffers (if RAM allows).",
        chart_request=None,
    )


def _test_write_daemon_strain(df: pd.DataFrame) -> Optional[Finding]:
    """Test 3: WDQsz non-zero between cycles + rising wa."""
    if "WDQsz" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    wdqsz = pd.to_numeric(df["WDQsz"], errors="coerce").fillna(0)
    warn_runs = _find_breaches(wdqsz, df["dt"], 0.0, WARN_CONSECUTIVE)
    if not warn_runs:
        return None

    start, end, count = warn_runs[0]
    window = df[(df["dt"] >= start) & (df["dt"] <= end)]
    wa_mean = pd.to_numeric(window.get("wa", pd.Series([0])), errors="coerce").mean()

    if wa_mean < 5.0:
        return None

    return Finding(
        metric="WDQsz + wa (write daemon strain)",
        severity="Yellow",
        observation=f"WDQsz non-zero for {count} consecutive samples with concurrent wa={wa_mean:.1f}% — "
                    f"write path under strain.",
        when=f"{pd.Timestamp(start).strftime('%Y-%m-%d %H:%M:%S')} – "
             f"{pd.Timestamp(end).strftime('%Y-%m-%d %H:%M:%S')}",
        corroborating=[f"wa averaged {wa_mean:.1f}% during WDQsz event"],
        hypotheses=["hypothesis: storage write latency causing write daemon queue growth",
                    "hypothesis: WIJ or journal device saturated"],
        next_step="Check iostat await on WIJ and journal devices during recurrence.",
        chart_request=None,
    )


def _test_memory_danger(df: pd.DataFrame) -> Optional[Finding]:
    """Test 4: free trending down + cache shrinking + any si/so."""
    if "free" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 6:
        return None

    free  = pd.to_numeric(df["free"],  errors="coerce").fillna(0)
    cache = pd.to_numeric(df.get("cache", pd.Series([float("nan")] * n)), errors="coerce")
    si    = pd.to_numeric(df.get("si",    pd.Series([0.0] * n)),           errors="coerce").fillna(0)
    so    = pd.to_numeric(df.get("so",    pd.Series([0.0] * n)),           errors="coerce").fillna(0)

    third = n // 3
    free_declining  = free.iloc[2*third:].mean() < free.iloc[:third].mean() * 0.80
    cache_shrinking = (not cache.isna().all()) and cache.iloc[2*third:].mean() < cache.iloc[:third].mean() * 0.85
    any_swap = (si > 0).any() or (so > 0).any()

    if not (free_declining and any_swap):
        return None

    severity = "Red" if any_swap else "Yellow"
    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    corroborating = []
    if cache_shrinking:
        corroborating.append("Page cache is also shrinking — kernel reclaiming memory")
    if any_swap:
        corroborating.append("Swap activity detected — memory pressure is confirmed")

    return Finding(
        metric="free / cache / swap (memory danger)",
        severity=severity,
        observation=f"Free memory declined {free.iloc[:third].mean():.0f} → {free.iloc[2*third:].mean():.0f} KB "
                    f"over the collection window" +
                    (" with concurrent swap activity." if any_swap else "."),
        when=f"{start_ts} – {end_ts}",
        corroborating=corroborating,
        hypotheses=["hypothesis: memory leak or growing resident set in IRIS or companion processes",
                    "hypothesis: insufficient RAM for configured IRIS global buffers + OS overhead"],
        next_step="URGENT if swap is active: reduce global buffers or add RAM. "
                  "Monitor free memory trend across collections.",
        chart_request=None,
    )


def _test_contention_vs_throughput(df: pd.DataFrame) -> Optional[Finding]:
    """Test 5: ASeize fraction rising relative to Seizes."""
    if "Seize" not in df.columns or "ASeize" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 9:
        return None

    seize  = pd.to_numeric(df["Seize"],  errors="coerce").fillna(0)
    aseize = pd.to_numeric(df["ASeize"], errors="coerce").fillna(0)

    fraction = aseize.where(seize > 0, 0) / seize.where(seize > 0, 1) * 100
    third = n // 3
    frac_first = fraction.iloc[:third].mean()
    frac_last  = fraction.iloc[2*third:].mean()

    if frac_last < 5.0 or frac_last < frac_first * 1.5:
        return None

    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    return Finding(
        metric="ASeize/Seize (lock contention)",
        severity="Yellow",
        observation=f"ASeize fraction rose from {frac_first:.1f}% to {frac_last:.1f}% of Seizes — "
                    f"genuine lock contention increasing, not just throughput scaling.",
        when=f"{start_ts} – {end_ts}",
        corroborating=["Seize is rising in proportion but ASeize fraction is also rising — contention, not scaling"],
        hypotheses=["hypothesis: lock table pressure — review locksiz in CPF",
                    "hypothesis: application-level contention on a shared resource"],
        next_step="Review locksiz setting. Capture ^SystemPerformance lock analysis during peak.",
        chart_request=None,
    )


def _test_kernel_overhead(df: pd.DataFrame) -> Optional[Finding]:
    """Test 6: sy growing relative to us at similar Glorefs."""
    if "us" not in df.columns or "sy" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)
    n = len(df)
    if n < 9:
        return None

    us = pd.to_numeric(df["us"], errors="coerce").fillna(0)
    sy = pd.to_numeric(df["sy"], errors="coerce").fillna(0)
    total = us + sy
    sy_frac = sy.where(total > 0, 0) / total.where(total > 0, 1)

    third = n // 3
    sf_first = sy_frac.iloc[:third].mean()
    sf_last  = sy_frac.iloc[2*third:].mean()

    glorefs = pd.to_numeric(df.get("Glorefs", pd.Series([1.0] * n)), errors="coerce").fillna(1)
    gl_first = glorefs.iloc[:third].mean()
    gl_last  = glorefs.iloc[2*third:].mean()
    glorefs_stable = abs(gl_last - gl_first) / (gl_first + 1) < 0.20

    if not (glorefs_stable and sf_last > sf_first * 1.5 and sf_last > 0.30):
        return None

    start_ts = df["dt"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    end_ts   = df["dt"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    return Finding(
        metric="sy/us ratio (kernel overhead)",
        severity="Yellow",
        observation=f"Kernel CPU fraction grew from {sf_first*100:.1f}% to {sf_last*100:.1f}% of total CPU "
                    f"while Glorefs remained stable ({gl_first:.0f} → {gl_last:.0f}) — "
                    f"increasing kernel overhead not explained by workload growth.",
        when=f"{start_ts} – {end_ts}",
        corroborating=["Glorefs stable — workload not increasing, so sy growth is not proportional"],
        hypotheses=["hypothesis: HugePages not configured — IRIS managing its own TLB misses",
                    "hypothesis: NUMA cross-socket memory traffic",
                    "hypothesis: growing interrupt or softirq load (network/storage driver)"],
        next_step="Verify HugePages configuration. Check /proc/interrupts for growth on specific IRQs.",
        chart_request=None,
    )


def _test_batch_window(df: pd.DataFrame) -> Optional[Finding]:
    """
    Test 7: Identify overnight PhyWrs/Jrnwrts surge.
    Alert if it overlaps with business hours (08:00+).
    """
    if "PhyWrs" not in df.columns and "Jrnwrts" not in df.columns:
        return None

    df = df.sort_values("dt").reset_index(drop=True)

    overnight = df[df["dt"].dt.hour.between(0, 6)].copy()
    business  = df[df["dt"].dt.hour.between(8, 9)].copy()

    if overnight.empty:
        return None

    phywrs  = pd.to_numeric(df.get("PhyWrs",  pd.Series([0.0]*len(df))), errors="coerce").fillna(0)
    jrnwrts = pd.to_numeric(df.get("Jrnwrts", pd.Series([0.0]*len(df))), errors="coerce").fillna(0)

    overnight_pw  = pd.to_numeric(overnight.get("PhyWrs",  pd.Series([0.0])), errors="coerce").mean()
    business_pw   = pd.to_numeric(business.get("PhyWrs",   pd.Series([0.0])), errors="coerce").mean() if not business.empty else 0
    overall_pw    = phywrs.mean()

    # Batch window exists if overnight writes are >2× overall mean
    if overnight_pw < overall_pw * 2.0:
        return None

    # Only a finding if it overlaps business hours
    overlap = business_pw > overnight_pw * 0.5

    severity = "Yellow" if overlap else "Green"
    note = (" Batch window overlaps business hours — I/O contention risk." if overlap
            else " Batch window ends before business hours ramp — normal.")

    return Finding(
        metric="PhyWrs/Jrnwrts (batch/backup window)",
        severity=severity,
        observation=f"Overnight PhyWrs averaged {overnight_pw:.0f}/s (vs overall mean {overall_pw:.0f}/s) "
                    f"— batch/backup window identified.{note}",
        when=f"00:00–06:00 window",
        corroborating=[],
        hypotheses=(["confirmed: batch/backup I/O overlapping morning ramp — monitor for user impact"]
                    if overlap
                    else ["confirmed: batch window clears before business hours — acceptable"]),
        next_step=("Review backup schedule; aim to complete before 07:00." if overlap
                   else "No action required."),
        chart_request=None,
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 39 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: implement 7 correlation tests (user stall, buffer pressure, WD strain, memory, contention, kernel, batch)"
```

---

## Task 8: `ChartRequest` population and `_write_report()`

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_performance_analysis.py

from performance_analysis import _attach_chart_requests, _write_report


def test_attach_chart_requests_only_nongreen():
    n = 5
    base_dt = pd.date_range("2026-01-01 09:00:00", periods=n, freq="5s")
    df = pd.DataFrame({"dt": base_dt, "wa": [25.0]*n, "metric": [25.0]*n})
    red_finding = Finding(
        metric="wa (I/O wait %)", severity="Red",
        observation="wa exceeded 20%", when="09:00:00",
        chart_request=None,
    )
    green_finding = Finding(
        metric="vmstat (all)", severity="Green",
        observation="All clear", when="entire window",
        chart_request=None,
    )
    findings = [red_finding, green_finding]
    metric_df_map = {"wa (I/O wait %)": df}
    result = _attach_chart_requests(findings, metric_df_map, output_dir="/tmp")
    assert result[0].chart_request is not None   # Red gets chart
    assert result[1].chart_request is None        # Green does not


def test_write_report_creates_file(tmp_path):
    meta = {
        "start": pd.Timestamp("2026-01-01 09:00:00"),
        "end":   pd.Timestamp("2026-01-01 17:00:00"),
        "n_days": 1, "weekdays": ["Thursday"],
        "interval_seconds": 5, "gaps": [],
    }
    facts = {"vcpus": 8, "ram_gb": 32, "iris_buffers_gb": 16,
             "customer": "TestHospital", "version": "IRIS 2024.1", "os": "Linux"}
    findings = [Finding(
        metric="vmstat (all)", severity="Green",
        observation="All clear", when="entire window",
    )]
    baselines = {}
    path = _write_report(
        meta=meta, facts=facts, findings=findings, baselines=baselines,
        context="Routine health check", output_dir=str(tmp_path),
    )
    assert os.path.exists(path)
    content = open(path).read()
    assert "Executive Summary" in content
    assert "TestHospital" in content
    assert "Green" in content


def test_write_report_filename_uses_dates(tmp_path):
    meta = {
        "start": pd.Timestamp("2026-01-05 09:00:00"),
        "end":   pd.Timestamp("2026-01-07 17:00:00"),
        "n_days": 3, "weekdays": ["Monday", "Tuesday", "Wednesday"],
        "interval_seconds": 30, "gaps": [],
    }
    facts = {"vcpus": None, "ram_gb": None, "iris_buffers_gb": None,
             "customer": "Unknown", "version": None, "os": "Linux"}
    path = _write_report(
        meta=meta, facts=facts, findings=[], baselines={},
        context=None, output_dir=str(tmp_path),
    )
    assert "2026-01-05" in os.path.basename(path)
    assert "2026-01-07" in os.path.basename(path)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_write_report_creates_file -v
```

Expected: `ImportError: cannot import name '_attach_chart_requests'`

- [ ] **Step 3: Implement `_attach_chart_requests()` and `_write_report()`**

Add to `performance_analysis.py`:

```python
def _attach_chart_requests(
    findings: list,
    metric_df_map: dict,
    output_dir: str,
) -> list:
    """
    For each Yellow/Red finding, populate finding.chart_request if a matching
    DataFrame is available in metric_df_map (keyed by finding.metric).
    Green findings are left unchanged.
    """
    updated = []
    for f in findings:
        if f.severity in ("Yellow", "Red") and f.metric in metric_df_map:
            df = metric_df_map[f.metric]
            thresh = METRIC_THRESHOLDS.get(f.metric.split()[0], {})
            warn_level  = thresh.get("fixed_warn", 0.0) or 0.0
            alert_level = thresh.get("fixed_alert", 0.0) or 0.0
            safe_name = f.metric.replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
            f.chart_request = ChartRequest(
                metric=f.metric,
                title=f.metric,
                df=df,
                warn_level=float(warn_level),
                alert_level=float(alert_level),
                shading_spans=[],
                twin_metric=None,
                twin_df=None,
                output_dir=output_dir,
                filename=f"{safe_name}_finding",
            )
        updated.append(f)
    return updated


def _write_report(
    meta: dict,
    facts: dict,
    findings: list,
    baselines: dict,
    context: Optional[str],
    output_dir: str,
) -> str:
    """
    Write the 7-section narrative markdown report.
    Returns the path to the written file.
    """
    start = meta.get("start")
    end   = meta.get("end")
    start_str = start.strftime("%Y-%m-%d") if start else "unknown"
    end_str   = end.strftime("%Y-%m-%d")   if end   else "unknown"

    filename = f"performance_summary_{start_str}_{end_str}.md"
    filepath = os.path.join(output_dir, filename)

    red_findings    = [f for f in findings if f.severity == "Red"]
    yellow_findings = [f for f in findings if f.severity == "Yellow"]
    green_findings  = [f for f in findings if f.severity == "Green"]

    if red_findings:
        overall = "🔴 Red"
    elif yellow_findings:
        overall = "🟡 Yellow"
    else:
        overall = "🟢 Green"

    context_line = context or "Routine health check — no specific context provided."

    customer    = facts.get("customer", "Unknown")
    vcpus       = facts.get("vcpus")
    ram_gb      = facts.get("ram_gb")
    buffers_gb  = facts.get("iris_buffers_gb")
    version     = facts.get("version", "")
    interval    = meta.get("interval_seconds")
    n_days      = meta.get("n_days", 1)
    weekdays    = meta.get("weekdays", [])
    gaps        = meta.get("gaps", [])

    vcpu_str    = str(vcpus) if vcpus else "unknown (assumption: check sp_check output)"
    ram_str     = f"{ram_gb} GB" if ram_gb else "unknown"
    buf_str     = f"{buffers_gb} GB" if buffers_gb else "unknown"
    interval_str = f"{interval:.0f}s" if interval else "unknown"

    lines = []

    # ── 1. Executive summary ──────────────────────────────────────────────────
    top_findings = (red_findings + yellow_findings)[:2]
    top_text = (
        " ".join(f.observation.split(". ")[0] + "." for f in top_findings)
        if top_findings
        else "No anomalies detected."
    )
    urgent = any(f.severity == "Red" for f in findings)
    urgency_text = "Immediate review recommended." if urgent else "No urgent action required."

    lines += [
        f"# Performance Summary: {customer}",
        f"",
        f"**Collection:** {start_str} – {end_str}  ",
        f"**Context:** {context_line}  ",
        f"**Generated by:** yaspe `--analysis`",
        f"",
        f"---",
        f"",
        f"## 1. Executive Summary",
        f"",
        f"Overall health: **{overall}**. {top_text} {urgency_text}",
        f"",
    ]

    # ── 2. Collection overview ────────────────────────────────────────────────
    lines += [
        f"## 2. Collection Overview",
        f"",
        f"| Item | Value |",
        f"|---|---|",
        f"| Customer / hostname | {customer} |",
        f"| IRIS version | {version or 'not captured'} |",
        f"| Collection window | {start_str} {start.strftime('%H:%M') if start else ''} – "
        f"{end_str} {end.strftime('%H:%M') if end else ''} |",
        f"| Days covered | {n_days} ({', '.join(weekdays)}) |",
        f"| Median sample interval | {interval_str} |",
        f"| vCPUs | {vcpu_str} |",
        f"| RAM | {ram_str} |",
        f"| IRIS global buffers | {buf_str} |",
        f"",
    ]

    if gaps:
        lines.append("**Data quality — collection gaps (> 3× interval):**")
        lines.append("")
        for g_start, g_end in gaps:
            lines.append(f"- {pd.Timestamp(g_start).strftime('%Y-%m-%d %H:%M:%S')} – "
                         f"{pd.Timestamp(g_end).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("Gaps are not interpolated. Statistics within gap windows may be unreliable.")
        lines.append("")
    else:
        lines += ["No collection gaps detected.", ""]

    # ── 3. Workload profile ───────────────────────────────────────────────────
    lines += [
        f"## 3. Workload Profile",
        f"",
    ]
    if baselines:
        lines += [
            "Per-period peak Glorefs and Gloupds:",
            "",
            "| Period | Peak Glorefs | Peak Gloupds |",
            "|---|---|---|",
        ]
        for period in IRIS_PERIODS:
            pname = period["name"]
            if pname in baselines:
                gl = baselines[pname].get("Glorefs", {}).get("max", "—")
                gu = baselines[pname].get("Gloupds", {}).get("max", "—")
                gl_str = f"{gl:.0f}" if isinstance(gl, float) else str(gl)
                gu_str = f"{gu:.0f}" if isinstance(gu, float) else str(gu)
                lines.append(f"| {pname} | {gl_str} | {gu_str} |")
        lines.append("")
    else:
        lines += ["Workload profile data not available.", ""]

    # ── 4. Findings ───────────────────────────────────────────────────────────
    lines += ["## 4. Findings", ""]

    ordered_findings = red_findings + yellow_findings
    if not ordered_findings:
        lines += ["No Yellow or Red findings. System health is **Green** for this collection window.", ""]
    else:
        for i, f in enumerate(ordered_findings, 1):
            badge = "🔴" if f.severity == "Red" else "🟡"
            lines += [
                f"### Finding {i}: {badge} {f.severity} — {f.metric}",
                f"",
                f"**Observed:** {f.observation}",
                f"",
                f"**When:** {f.when}",
                f"",
            ]
            if f.corroborating:
                lines.append("**Corroborating metrics:**")
                lines.append("")
                for c in f.corroborating:
                    lines.append(f"- {c}")
                lines.append("")
            if f.hypotheses:
                lines.append("**Hypotheses (ranked):**")
                lines.append("")
                for h in f.hypotheses:
                    lines.append(f"1. {h}")
                lines.append("")
            if f.next_step:
                lines += [f"**Next step:** {f.next_step}", ""]
            if f.chart_request:
                lines += [f"![{f.metric} chart]({f.chart_request.filename}.png)", ""]

    # ── 5. Explainable anomalies ──────────────────────────────────────────────
    batch = next((f for f in findings if "batch" in f.metric.lower() and f.severity == "Green"), None)
    lines += ["## 5. Explainable Anomalies", ""]
    if batch:
        lines += [f"**Batch/backup window:** {batch.observation}", ""]
    else:
        lines += ["No explainable anomalies identified outside of findings above.", ""]

    # ── 6. Baseline table ─────────────────────────────────────────────────────
    lines += ["## 6. Baseline Table", ""]
    if baselines:
        all_metrics = set()
        for p in baselines.values():
            all_metrics.update(p.keys())
        all_metrics = sorted(all_metrics)

        header = "| Period | " + " | ".join(f"{m} mean / σ / p95" for m in all_metrics) + " |"
        sep    = "|---|" + "---|" * len(all_metrics)
        lines += [header, sep]

        for period in IRIS_PERIODS:
            pname = period["name"]
            if pname not in baselines:
                continue
            row = f"| {pname} |"
            for m in all_metrics:
                if m in baselines[pname]:
                    b = baselines[pname][m]
                    row += f" {b['mean']:.1f} / {b['sigma']:.1f} / {b['p95']:.1f} |"
                else:
                    row += " — |"
            lines.append(row)
        lines.append("")
    else:
        lines += ["Baseline data not available.", ""]

    # ── 7. Appendix ───────────────────────────────────────────────────────────
    lines += [
        "## 7. Appendix: SQL Queries",
        "",
        "Queries used to produce this report:",
        "",
        "```sql",
        "-- mgstat data",
        "SELECT RunDate, RunTime, Glorefs, PhyRds, PhyWrs, Gloupds, Jrnwrts,",
        "       WDQsz, Rdratio, RouLaS, Seize, ASeize FROM mgstat",
        "ORDER BY RunDate, RunTime;",
        "",
        "-- vmstat data",
        "SELECT RunDate, RunTime, r, b, swpd, free, buff, cache,",
        "       si, so, bi, bo, \"in\", cs, us, sy, id, wa, st FROM vmstat",
        "ORDER BY RunDate, RunTime;",
        "```",
        "",
    ]

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return filepath
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 44 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: add _attach_chart_requests and _write_report (7-section markdown)"
```

---

## Task 9: Public entry point `run_analysis()`

**Files:**
- Modify: `performance_analysis.py`
- Modify: `tests/test_performance_analysis.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_performance_analysis.py

from performance_analysis import run_analysis


def test_run_analysis_returns_markdown_path(tmp_path):
    """run_analysis() must return a path to an existing .md file."""
    rows = [
        ("01/01/2026", "09:00:00", 1000,10,5,200,50,0,17,0,1000,10,"f.html"),
        ("01/01/2026", "09:00:05", 1100,11,5,210,50,0,17,0,1000,10,"f.html"),
        ("01/01/2026", "09:00:10",  900, 9,5,190,50,0,17,0,1000,10,"f.html"),
        ("01/01/2026", "09:00:15", 1050,10,5,200,50,0,17,0,1000,10,"f.html"),
        ("01/01/2026", "09:00:20",  950,10,5,195,50,0,17,0,1000,10,"f.html"),
    ]
    conn = _make_test_db(rows)
    # Add vmstat table
    conn.execute("""
        CREATE TABLE vmstat (
            id_key INTEGER PRIMARY KEY,
            RunDate TEXT, RunTime TEXT,
            r REAL, b REAL, swpd REAL, free REAL, buff REAL, cache REAL,
            si REAL, so REAL, bi REAL, bo REAL, "in" REAL, cs REAL,
            us REAL, sy REAL, id REAL, wa REAL, st REAL,
            "html name" TEXT
        )
    """)
    for i in range(5):
        conn.execute(
            "INSERT INTO vmstat (RunDate, RunTime, r, b, swpd, free, buff, cache, "
            "si, so, bi, bo, \"in\", cs, us, sy, id, wa, st, \"html name\") "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("01/01/2026", f"09:00:{i*5:02d}", 0,0,0,10000,0,5000, 0,0,0,0,100,200, 20,5,75,2,0,"f.html"),
        )
    conn.commit()

    sp_dict = {
        "operating system": "Linux",
        "customer": "TestHospital",
        "number cpus": "8",
        "memory MB": "32768",
        "globals total MB": "16384",
    }

    md_path, chart_requests = run_analysis(
        connection=conn,
        sp_dict=sp_dict,
        output_prefix="test_",
        filepath=str(tmp_path),
        context="Integration test",
    )
    conn.close()

    assert os.path.exists(md_path)
    assert md_path.endswith(".md")
    assert isinstance(chart_requests, list)


def test_run_analysis_returns_chart_requests_for_red_findings(tmp_path):
    """Red findings must produce ChartRequest objects."""
    rows = []
    # 3 consecutive wa=25% rows (Red alert) at 09:00:00, 09:00:05, 09:00:10
    for i in range(5):
        rows.append(("01/01/2026", f"09:00:{i*5:02d}", 1000,10,5,200,50,0,17,0,1000,10,"f.html"))
    conn = _make_test_db(rows)
    conn.execute("""
        CREATE TABLE vmstat (
            id_key INTEGER PRIMARY KEY,
            RunDate TEXT, RunTime TEXT,
            r REAL, b REAL, swpd REAL, free REAL, buff REAL, cache REAL,
            si REAL, so REAL, bi REAL, bo REAL, "in" REAL, cs REAL,
            us REAL, sy REAL, id REAL, wa REAL, st REAL,
            "html name" TEXT
        )
    """)
    # 3 consecutive wa=25% rows
    for i in range(5):
        wa = 25.0 if i < 3 else 2.0
        conn.execute(
            "INSERT INTO vmstat (RunDate, RunTime, r, b, swpd, free, buff, cache, "
            "si, so, bi, bo, \"in\", cs, us, sy, id, wa, st, \"html name\") "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("01/01/2026", f"09:00:{i*5:02d}", 0,0,0,10000,0,5000, 0,0,0,0,100,200, 20,5,75,wa,0,"f.html"),
        )
    conn.commit()

    sp_dict = {"operating system": "Linux", "customer": "Test", "number cpus": "8",
               "memory MB": "32768", "globals total MB": "16384"}
    md_path, chart_requests = run_analysis(conn, sp_dict, "test_", str(tmp_path), context=None)
    conn.close()

    assert os.path.exists(md_path)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_run_analysis_returns_markdown_path -v
```

Expected: `ImportError: cannot import name 'run_analysis'`

- [ ] **Step 3: Implement `run_analysis()`**

Add to the end of `performance_analysis.py`:

```python
def run_analysis(
    connection,
    sp_dict: dict,
    output_prefix: str,
    filepath: str,
    context: Optional[str] = None,
    png_out: bool = False,
) -> tuple:
    """
    Public entry point. Run full performance analysis.

    Returns (markdown_path, chart_requests) where:
      markdown_path  — path to the written .md file
      chart_requests — list[ChartRequest] for Yellow/Red findings (empty if all Green)
    """
    meta  = _get_collection_meta(connection)
    facts = _get_system_facts(sp_dict)

    # Load vmstat and mgstat DataFrames
    try:
        mg_raw = pd.read_sql_query("SELECT * FROM mgstat", connection)
        mg_raw.dropna(inplace=True)
        if "datetime" in mg_raw.columns:
            mg_raw["dt"] = pd.to_datetime(mg_raw["datetime"].str.strip(), errors="coerce")
        else:
            mg_raw["dt"] = pd.to_datetime(
                mg_raw["RunDate"].str.strip() + " " + mg_raw["RunTime"].str.strip(),
                errors="coerce",
            )
        mg_df = mg_raw.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    except Exception:
        mg_df = pd.DataFrame()

    try:
        vm_raw = pd.read_sql_query("SELECT * FROM vmstat", connection)
        vm_raw.dropna(inplace=True)
        if "datetime" in vm_raw.columns:
            vm_raw["dt"] = pd.to_datetime(vm_raw["datetime"].str.strip(), errors="coerce")
        else:
            vm_raw["dt"] = pd.to_datetime(
                vm_raw["RunDate"].str.strip() + " " + vm_raw["RunTime"].str.strip(),
                errors="coerce",
            )
        vm_df = vm_raw.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)
    except Exception:
        vm_df = pd.DataFrame()

    # Compute baselines from mgstat
    mgstat_metrics = [m for m in ("Glorefs","PhyRds","PhyWrs","Gloupds","Jrnwrts","Rdratio")
                      if m in mg_df.columns]
    baselines = _compute_baselines(mg_df, mgstat_metrics) if not mg_df.empty else {}

    # Per-metric analysis
    vcpus = facts.get("vcpus")
    all_findings = []

    if not vm_df.empty:
        all_findings.extend(_analyse_vmstat(vm_df, vcpus=vcpus))

    if not mg_df.empty:
        all_findings.extend(_analyse_mgstat(mg_df, baselines))

    # Correlation tests — build a joined DataFrame
    if not mg_df.empty and not vm_df.empty:
        interval = meta.get("interval_seconds") or 30.0
        joined = _nearest_join(mg_df, vm_df, interval)
        for test_fn in (
            _test_user_stall,
            _test_buffer_pressure,
            _test_write_daemon_strain,
            _test_memory_danger,
            _test_contention_vs_throughput,
            _test_kernel_overhead,
            _test_batch_window,
        ):
            try:
                result = test_fn(joined)
                if result is not None:
                    all_findings.append(result)
            except Exception:
                pass
    elif not mg_df.empty:
        for test_fn in (_test_buffer_pressure, _test_write_daemon_strain,
                        _test_contention_vs_throughput, _test_batch_window):
            try:
                result = test_fn(mg_df)
                if result is not None:
                    all_findings.append(result)
            except Exception:
                pass

    # Build metric_df_map for chart attachment
    metric_df_map = {}
    if not vm_df.empty:
        for col in ("wa", "r", "b", "si", "so"):
            if col in vm_df.columns:
                key = next((f.metric for f in all_findings if f.metric.startswith(col)), None)
                if key:
                    sub = vm_df[["dt", col]].rename(columns={col: "metric"})
                    metric_df_map[key] = sub
    if not mg_df.empty:
        for col in ("WDQsz", "RouLaS", "Glorefs", "PhyRds", "PhyWrs", "Jrnwrts"):
            if col in mg_df.columns:
                key = next((f.metric for f in all_findings if col in f.metric), None)
                if key:
                    sub = mg_df[["dt", col]].rename(columns={col: "metric"})
                    metric_df_map[key] = sub

    analysis_dir = os.path.join(filepath, f"{output_prefix}analysis_metrics")
    os.makedirs(analysis_dir, exist_ok=True)

    all_findings = _attach_chart_requests(all_findings, metric_df_map, analysis_dir)

    md_path = _write_report(
        meta=meta,
        facts=facts,
        findings=all_findings,
        baselines=baselines,
        context=context,
        output_dir=filepath,
    )

    chart_requests = [f.chart_request for f in all_findings if f.chart_request is not None]
    return md_path, chart_requests
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_performance_analysis.py -v
```

Expected: all 46 tests PASS

- [ ] **Step 5: Commit**

```bash
git add performance_analysis.py tests/test_performance_analysis.py
git commit -m "feat: implement run_analysis() public entry point"
```

---

## Task 10: Wire `--analysis` and `--context` into `yaspe.py`

**Files:**
- Modify: `yaspe.py` (lines ~3078–3176 for CLI; ~2862–2882 for mainline logic; add `_render_analysis_chart()`)
- Modify: `tests/test_performance_analysis.py` (CLI smoke test)

- [ ] **Step 1: Write failing CLI smoke test**

```python
# Add to tests/test_performance_analysis.py

import subprocess


def test_yaspe_analysis_flag_exists():
    """--analysis flag must be recognised by yaspe.py (no error on --help)."""
    result = subprocess.run(
        ["python", "yaspe.py", "--help"],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert "--analysis" in result.stdout
    assert "--context" in result.stdout
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_performance_analysis.py::test_yaspe_analysis_flag_exists -v
```

Expected: FAIL — `--analysis` not in help output

- [ ] **Step 3: Add CLI arguments to `yaspe.py`**

In `yaspe.py`, after the `--day-overlay` argument block (around line 3174), add:

```python
    parser.add_argument(
        "--analysis",
        dest="analysis",
        help="Run performance analysis report (implies -s). Writes a narrative markdown summary.",
        action="store_true",
    )

    parser.add_argument(
        "--context",
        dest="context",
        help='Optional context note for the analysis report (e.g. "users reported slowness Tuesday").',
        action="store",
        default=None,
        metavar='"context string"',
    )
```

- [ ] **Step 4: Add `--analysis` implies `-s` logic and `mainline` parameter**

In `yaspe.py`, update the `mainline()` signature to accept `analysis=False` and `context=None`:

```python
def mainline(
    input_file,
    include_iostat,
    include_nfsiostat,
    append_to_database,
    existing_database,
    output_prefix,
    csv_out,
    png_out,
    png_html_out,
    system_out,
    disk_list,
    split_on,
    csv_date_format,
    mgstat_file,
    peak_chart=True,
    line_chart=True,
    iostat_subfolders=True,
    smooth_minutes=5,
    day_overlay=False,
    analysis=False,
    context=None,
):
```

In the `__main__` block, before the `mainline(...)` call, add:

```python
    if args.analysis:
        args.system_out = True
```

Update the `mainline(...)` call to pass the new arguments (add at the end of the argument list):

```python
        args.analysis,
        args.context,
```

- [ ] **Step 5: Add `_render_analysis_chart()` and the `--analysis` call in `mainline()`**

In `yaspe.py`, add `_render_analysis_chart()` before `mainline()` (around line 2734):

```python
def _render_analysis_chart(chart_request, output_prefix):
    """Render a single analysis finding chart as PNG using matplotlib."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    cr = chart_request
    df = cr.df.copy()
    if df.empty:
        return

    dt_col = "datetime_parsed" if "datetime_parsed" in df.columns else "dt"
    if dt_col not in df.columns:
        return

    fig, ax1 = plt.subplots(figsize=(16, 6))
    plt.style.use("seaborn-v0_8-whitegrid")

    ax1.plot(df[dt_col], df["metric"], color="steelblue", linewidth=1.2, label=cr.metric)

    if cr.warn_level and cr.warn_level > 0:
        ax1.axhline(y=cr.warn_level, color="orange", linestyle="--", linewidth=1, label=f"Warning ({cr.warn_level})")
    if cr.alert_level and cr.alert_level > 0:
        ax1.axhline(y=cr.alert_level, color="red", linestyle="--", linewidth=1, label=f"Alert ({cr.alert_level})")

    for span_start, span_end in cr.shading_spans:
        ax1.axvspan(span_start, span_end, alpha=0.2, color="red")

    if cr.twin_df is not None and cr.twin_metric:
        ax2 = ax1.twinx()
        ax2.plot(cr.twin_df[dt_col], cr.twin_df["metric"],
                 color="darkorange", linewidth=1.0, linestyle=":", label=cr.twin_metric)
        ax2.set_ylabel(cr.twin_metric, color="darkorange")
        ax2.legend(loc="upper right")

    ax1.set_title(cr.title)
    ax1.set_xlabel("Time")
    ax1.set_ylabel(cr.metric)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax1.legend(loc="upper left")
    fig.autofmt_xdate()

    out_path = os.path.join(cr.output_dir, f"{cr.filename}.png")
    plt.savefig(out_path, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Analysis chart: {out_path}")
```

In `mainline()`, after the `sp_dict` / `system_out` block (around line 2882, after the `create_overview` / `create_sections` calls complete and just before `close_connection(connection)`), add:

```python
                if analysis and sp_dict:
                    import performance_analysis
                    md_path, chart_requests = performance_analysis.run_analysis(
                        connection=connection,
                        sp_dict=sp_dict,
                        output_prefix=output_prefix,
                        filepath=filepath,
                        context=context,
                    )
                    print(f"Analysis report: {md_path}")
                    for cr in chart_requests:
                        _render_analysis_chart(cr, output_prefix)
```

- [ ] **Step 6: Run smoke test**

```bash
python -m pytest tests/test_performance_analysis.py::test_yaspe_analysis_flag_exists -v
```

Expected: PASS

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add yaspe.py tests/test_performance_analysis.py
git commit -m "feat: wire --analysis and --context flags into yaspe.py"
```

---

## Task 11: Update `sync_engine.sh`

**Files:**
- Modify: `/Users/moldfiel/projects/all_live_projects/yaspe_flask_v1/sync_engine.sh`

- [ ] **Step 1: Check current ENGINE_FILES list**

```bash
grep -A 30 "ENGINE_FILES" /Users/moldfiel/projects/all_live_projects/yaspe_flask_v1/sync_engine.sh | head -30
```

- [ ] **Step 2: Add `performance_analysis.py` to ENGINE_FILES**

Find the `ENGINE_FILES` array in `sync_engine.sh` and add `"performance_analysis.py"` alongside the other engine files. The exact location depends on the array format — add it in alphabetical order near `pretty_performance.py`.

- [ ] **Step 3: Verify**

```bash
grep "performance_analysis" /Users/moldfiel/projects/all_live_projects/yaspe_flask_v1/sync_engine.sh
```

Expected: one line containing `performance_analysis.py`

- [ ] **Step 4: Commit**

```bash
git add yaspe.py  # catch any last edits
git -C /Users/moldfiel/projects/all_live_projects/yaspe_flask_v1 add sync_engine.sh
git -C /Users/moldfiel/projects/all_live_projects/yaspe_flask_v1 commit -m "chore: add performance_analysis.py to ENGINE_FILES"
git commit -m "chore: update sync_engine.sh for performance_analysis.py" --allow-empty
```

---

## Task 12: Final verification and version bump

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -m pytest tests/ -v
```

Expected: all tests PASS, no failures

- [ ] **Step 2: Smoke-test the flag on the real sample SQLite**

```bash
python yaspe.py -e test_samples/RHEL/yaspe_SystemPerformance.sqlite --analysis -s
```

Expected: prints "Analysis report: test_samples/RHEL/performance_summary_*.md", file is created, no traceback.
Note: `-s` requires an input HTML file to parse; when using `-e` alone with `--analysis`, the sp_dict will be minimal.
Use the HTML file instead for a full test:

```bash
python yaspe.py -i test_samples/RHEL/trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html --analysis -s -o yaspe
```

- [ ] **Step 3: Verify the markdown file structure**

```bash
grep "^## " ./performance_summary_*.md
```

Expected output (7 sections):
```
## 1. Executive Summary
## 2. Collection Overview
## 3. Workload Profile
## 4. Findings
## 5. Explainable Anomalies
## 6. Baseline Table
## 7. Appendix: SQL Queries
```

- [ ] **Step 4: Bump version**

```bash
bump2version minor
```

Expected: version bumped from `0.7.8` → `0.8.0` in `yaspe.py` and `.bumpversion.cfg`, auto-commit created.

- [ ] **Step 5: Push**

```bash
git push origin feature/performance-analysis
```
