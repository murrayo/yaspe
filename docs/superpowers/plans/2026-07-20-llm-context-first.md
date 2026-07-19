# LLM-Context-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `--analysis`, and turn `--llm-context` into an anonymized markdown bundle (schema 2.0) with period stats, the analyst key-metrics scorecard, and a companion LLM prompt file.

**Architecture:** `performance_analysis.py` is trimmed to an analysis library (report writer and chart machinery deleted). `llm_context.py` gains period stats, key metrics, a not-available list, an anonymization scrub, and a markdown renderer; `build_llm_context()` still assembles a plain dict (testable, scrubbable) and a new `_render_markdown()` turns it into the bundle. `export_llm_context()` writes two files: the data bundle and a static prompt.

**Tech Stack:** Python 3.x, pandas, numpy, sqlite3, stdlib `re`/`json`. Tests: pytest. No new pip dependencies.

**Spec:** `docs/superpowers/specs/2026-07-20-llm-context-first-design.md` — read it first.

## Global Constraints

- Branch: `feature/llm-context-anonymize` (already exists, work on it)
- No new pip dependencies
- Linux-only scope; no Windows/AIX branches
- `sync_engine.sh` must NOT be modified (both modules keep their names)
- Bundle filename: `{prefix}performance_context_{start}_{end}.md`; prompt filename: `{prefix}llm_analysis_prompt.md`
- `schema_version` is the string `"2.0"`
- All timestamps `%Y-%m-%d %H:%M:%S`
- Resample default is adaptive: `None` (auto) → 5min for ≤2 days, 15min for 3–4, 30min for ≥5; an explicit `--resample` value always wins
- Floats in rendered output are rounded: ratios 2 decimals, values ≥100 integers, else 1 decimal — never full float repr
- Ratios computed from sums (never mean-of-ratios) when numerator and denominator come from the same rows; cross-source rate ratios use mean/mean and say so in `basis`
- The scrub never raises; export must succeed even if scrubbing fails internally
- Run tests from repo root: `python3 -m pytest tests/... -v`
- Version bump at release time: `bump2version minor` (after merge to main, per CLAUDE.md — not part of this plan's tasks)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `yaspe.py` | Modify | Remove `--analysis` flag, call block, `_render_analysis_chart`; make `--llm-context` imply `-s`; print two output paths |
| `performance_analysis.py` | Modify | Delete `run_analysis`, `_write_report`, `_attach_chart_requests`, `ChartRequest`, `Finding.chart_request` |
| `llm_context.py` | Modify | Add period stats, key metrics, not-available, scrub, markdown renderer, `PROMPT_TEMPLATE`; rework `export_llm_context` |
| `tests/test_performance_analysis.py` | Modify | Remove report/chart tests; keep engine tests |
| `tests/test_llm_context.py` | Modify | Update for schema 2.0 + new tests |
| `README.md` | Modify | Remove `--analysis` docs; document the LLM workflow |

---

## Task 1: Remove `--analysis` and trim `performance_analysis.py`

**Files:**
- Modify: `performance_analysis.py` (delete lines: `ChartRequest` dataclass ~69–81, `chart_request` field ~92, `_attach_chart_requests` ~882–915, `_write_report` ~916–1155, `run_analysis` ~1156–1281 — line numbers approximate, locate by name)
- Modify: `yaspe.py` (`_render_analysis_chart` ~2931–2972, `analysis=False` param ~2997, analysis call block ~3161–3184, `--analysis` argparse ~3545–3550, `if args.analysis:` ~3616, `args.analysis,` in mainline call ~3642)
- Modify: `tests/test_performance_analysis.py`, `tests/test_llm_context.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `Finding` dataclass WITHOUT `chart_request` field (fields: `metric, severity, observation, when, corroborating, hypotheses, next_step`). `performance_analysis.py` exports only the engine: `IRIS_PERIODS`, `METRIC_THRESHOLDS`, `_fmt_n`, `Finding`, `_get_collection_meta`, `_get_system_facts`, `_label_period`, `_compute_baselines`, `_find_breaches`, `_analyse_vmstat`, `_analyse_mgstat`, `_nearest_join`, and the 7 `_test_*` correlation functions. Later tasks rely on exactly these names.

- [ ] **Step 1: Delete report machinery from `performance_analysis.py`**

Delete these blocks entirely (locate by definition name, delete through to the next top-level `def`/`@dataclass`):

- `@dataclass class ChartRequest`
- the `chart_request: Optional[ChartRequest] = None` field in `Finding`
- `_attach_chart_requests()`
- `_write_report()`
- `run_analysis()`

Then remove every `chart_request=None,` argument in the remaining `Finding(...)` constructions:

```bash
grep -c "chart_request" performance_analysis.py    # note the count
python3 - <<'EOF'
import re
s = open("performance_analysis.py").read()
s = re.sub(r"[ \t]*chart_request=None,\n", "", s)
open("performance_analysis.py", "w").write(s)
EOF
grep -n "chart_request\|ChartRequest\|run_analysis\|_write_report\|_attach_chart" performance_analysis.py
```

Expected: final grep prints nothing. Update the module docstring (lines 1–6) to:

```python
"""
Performance analysis engine for yaspe.
Baselines, KPI breach detection, and cross-signal correlation tests
following docs/Performance analysis/PERFORMANCE_ANALYSIS.md.
Consumed by llm_context.py. Linux only.
"""
```

Keep `_fmt_n` (used inside observation strings) and `_test_batch_window` (defined after `run_analysis` — do not delete it by accident).

- [ ] **Step 2: Remove `--analysis` from `yaspe.py`**

1. Delete the whole `_render_analysis_chart()` function.
2. In `mainline(...)` signature, delete the `analysis=False,` parameter (keep `context`, `llm_context`, `resample_interval`).
3. Delete the analysis call block (`# Performance analysis — runs for all modes` through its `finally: close_connection(analysis_conn)`).
4. Delete the `--analysis` `parser.add_argument` block.
5. Change the implies-`-s` gate — `--llm-context` needs the overview table (system facts, iostat role map) just as `--analysis` did:

```python
    if args.llm_context:
        args.system_out = True
```

6. In the `mainline(...)` call in the `__main__` block, delete the `args.analysis,` line (keep `args.context,`).

- [ ] **Step 3: Fix tests broken by the removals**

`tests/test_performance_analysis.py`:
- Remove imports of `run_analysis`, `_attach_chart_requests`, `_write_report` (lines ~11 and ~21).
- Delete `test_chart_request_dataclass` and everything from the comment `# Task 8: _attach_chart_requests and _write_report` to end of file (tests `test_attach_chart_requests_only_nongreen`, `test_write_report_creates_file`, `test_write_report_filename_uses_dates`, `test_run_analysis_returns_markdown_path`, `test_run_analysis_returns_chart_requests_for_red_findings`).
- In the remaining `Finding(...)` constructions, remove `chart_request=None,` kwargs and any `assert f.chart_request is None` line (same `re.sub` trick as Step 1 works for the kwarg).

`tests/test_llm_context.py`:
- In `test_serialise_finding_drops_chart_request`: remove the `chart_request=None,` kwarg from the `Finding(...)` construction. Keep the `assert "chart_request" not in d` (still true). Rename the test to `test_serialise_finding_fields`.

- [ ] **Step 4: Run the full suite**

```bash
python3 -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all PASS, no import errors.

- [ ] **Step 5: Smoke-test the CLI**

```bash
./yaspe.py --help | grep -c "analysis"      # expect 0 hits for --analysis flag (context/llm-context help may mention "analysis" the word — check output manually)
./yaspe.py --analysis 2>&1 | head -3        # expect argparse error: unrecognized arguments
```

- [ ] **Step 6: Commit**

```bash
git add performance_analysis.py yaspe.py tests/test_performance_analysis.py tests/test_llm_context.py
git commit -m "feat!: remove --analysis flag and markdown report; performance_analysis.py becomes analysis library"
```

---

## Task 2: Period statistics

**Files:**
- Modify: `llm_context.py`
- Test: `tests/test_llm_context.py`

**Interfaces:**
- Consumes: `_pa._label_period(time_str) -> Optional[str]`, `_pa.IRIS_PERIODS`
- Produces:
  - `_series_stats(vals) -> Optional[dict]` — `{mean, sigma, p90, p95, max, n_samples}` floats/int, or None for empty input
  - `_add_period_cols(df) -> pd.DataFrame` — copy with `_weekday` (day name) and `_period` (IRIS period name) columns, rows outside all periods dropped
  - `_compute_period_stats(mg_df, vm_df) -> list` — `[{"weekday": str, "period": str, "metrics": {metric: stats_dict}}]` sorted by weekday then period; includes derived `us_sy`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_llm_context.py`:

```python
# ---- Period stats ----
from llm_context import _compute_period_stats, _series_stats


def _make_mg_df_business_hours(n=20):
    """20 rows at 60s starting Tue 2024-01-16 09:30 — inside period 09:00–11:30."""
    base = datetime(2024, 1, 16, 9, 30, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=60 * i),
            "Glorefs": 10000 + i * 100,
            "Gloupds": 500,
            "PhyRds": 50,
            "PhyWrs": 20,
            "Jrnwrts": 30,
            "Rdratio": 95.0,
            "WDQsz": i,
        })
    return pd.DataFrame(rows)


def _make_vm_df_business_hours(n=20):
    base = datetime(2024, 1, 16, 9, 30, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=60 * i),
            "r": i, "b": 0, "us": 30.0, "sy": 10.0, "wa": 2.0, "si": 0, "so": 0,
        })
    return pd.DataFrame(rows)


def test_series_stats_keys():
    s = _series_stats(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert set(s) == {"mean", "sigma", "p90", "p95", "max", "n_samples"}
    assert s["mean"] == pytest.approx(2.5)
    assert s["max"] == 4.0
    assert s["n_samples"] == 4


def test_series_stats_empty_returns_none():
    assert _series_stats(pd.Series([], dtype=float)) is None
    assert _series_stats(pd.Series(["x", None])) is None


def test_period_stats_bucketing():
    result = _compute_period_stats(_make_mg_df_business_hours(), _make_vm_df_business_hours())
    assert len(result) == 1
    entry = result[0]
    assert entry["weekday"] == "Tuesday"
    assert entry["period"] == "09:00–11:30"
    assert "Glorefs" in entry["metrics"]
    assert "r" in entry["metrics"]


def test_period_stats_us_sy_derived():
    result = _compute_period_stats(pd.DataFrame(), _make_vm_df_business_hours())
    assert result[0]["metrics"]["us_sy"]["mean"] == pytest.approx(40.0)


def test_period_stats_has_p90():
    result = _compute_period_stats(_make_mg_df_business_hours(), pd.DataFrame())
    g = result[0]["metrics"]["Glorefs"]
    assert "p90" in g and "p95" in g
    assert g["p90"] <= g["p95"] <= g["max"]


def test_period_stats_empty_inputs():
    assert _compute_period_stats(pd.DataFrame(), pd.DataFrame()) == []


def test_period_stats_ppgupds_when_present():
    mg = _make_mg_df_business_hours()
    mg["PPGupds"] = 250.0
    result = _compute_period_stats(mg, pd.DataFrame())
    assert result[0]["metrics"]["PPGupds"]["mean"] == pytest.approx(250.0)
```

Note: the period name uses an **en-dash** (`09:00–11:30`), matching `_pa.IRIS_PERIODS`.

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_llm_context.py -k "period_stats or series_stats" -v
```

Expected: FAIL, `ImportError: cannot import name '_compute_period_stats'`

- [ ] **Step 3: Implement in `llm_context.py`**

Add `import numpy as np` at the top (next to `import pandas as pd`). Then add after `_merge_timeseries`:

```python
# Columns included in period statistics
_PERIOD_MG_COLS = ["Glorefs", "Gloupds", "PhyRds", "PhyWrs", "Jrnwrts", "Rdratio", "WDQsz", "PPGupds"]
_PERIOD_VM_COLS = ["r", "b", "sy", "wa", "si", "so"]
_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _series_stats(vals) -> Optional[dict]:
    """mean/sigma/p90/p95/max/n_samples for a numeric series; None if no numeric data."""
    vals = pd.to_numeric(vals, errors="coerce").dropna()
    if vals.empty:
        return None
    return {
        "mean": float(vals.mean()),
        "sigma": float(vals.std(ddof=1)) if len(vals) > 1 else 0.0,
        "p90": float(np.percentile(vals, 90)),
        "p95": float(np.percentile(vals, 95)),
        "max": float(vals.max()),
        "n_samples": int(len(vals)),
    }


def _add_period_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of df with _weekday and _period columns; rows outside all IRIS periods dropped."""
    df = df.copy()
    df["_weekday"] = df["dt"].dt.day_name()
    df["_period"] = df["dt"].dt.strftime("%H:%M").apply(_pa._label_period)
    return df.dropna(subset=["_period"])


def _compute_period_stats(mg_df: pd.DataFrame, vm_df: pd.DataFrame) -> list:
    """
    Per weekday × IRIS Health Monitor period stats from full-resolution data.
    Returns [{"weekday", "period", "metrics": {metric: stats}}] sorted by
    weekday then period. vmstat gains a derived us_sy column.
    """
    buckets = {}

    def _collect(df, cols, derive_us_sy=False):
        if df is None or df.empty or "dt" not in df.columns:
            return
        df = _add_period_cols(df)
        if df.empty:
            return
        if derive_us_sy and "us" in df.columns and "sy" in df.columns:
            df["us_sy"] = (pd.to_numeric(df["us"], errors="coerce")
                           + pd.to_numeric(df["sy"], errors="coerce"))
            cols = cols + ["us_sy"]
        for (weekday, period), group in df.groupby(["_weekday", "_period"]):
            metrics = buckets.setdefault((weekday, period), {})
            for col in cols:
                if col in group.columns:
                    stats = _series_stats(group[col])
                    if stats:
                        metrics[col] = stats

    _collect(mg_df, _PERIOD_MG_COLS)
    _collect(vm_df, _PERIOD_VM_COLS, derive_us_sy=True)

    period_order = [p["name"] for p in _pa.IRIS_PERIODS]
    keys = sorted(
        buckets,
        key=lambda k: (
            _WEEKDAY_ORDER.index(k[0]) if k[0] in _WEEKDAY_ORDER else 99,
            period_order.index(k[1]) if k[1] in period_order else 99,
        ),
    )
    return [{"weekday": w, "period": p, "metrics": buckets[(w, p)]} for w, p in keys]
```

- [ ] **Step 4: Run to verify pass, then full file**

```bash
python3 -m pytest tests/test_llm_context.py -v 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: per weekday/period statistics for LLM context"
```

---

## Task 3: Key metrics scorecard and not-available list

**Files:**
- Modify: `llm_context.py`
- Test: `tests/test_llm_context.py`

**Interfaces:**
- Consumes: `_series_stats`, `_add_period_cols` (Task 2), `_load_iostat_role_map(connection)` (existing)
- Produces:
  - `_load_iostat_df(connection) -> pd.DataFrame` — iostat table with `dt` column (refactored out of `_build_iostat_timeseries`, which now calls it)
  - `_compute_key_metrics(mg_df, vm_df, iostat_df, role_map, facts) -> dict` — `{"overall": {name: entry}, "peak_period": {"weekday", "period", "metrics": {...}} | None}`; entry is `{"value": float | stats_dict, "basis": str, "caveat": str?}`
  - `_build_not_available(mg_df, role_map) -> list` — `[{"metric", "reason", "how_to_collect"}]`

- [ ] **Step 1: Refactor the iostat loader (no behavior change)**

In `llm_context.py`, extract the DataFrame-loading half of `_build_iostat_timeseries` into:

```python
def _load_iostat_df(connection) -> pd.DataFrame:
    """Load iostat from SQLite with a 'dt' column. Empty DataFrame on any error."""
    try:
        df = pd.read_sql_query("SELECT * FROM iostat", connection)
        if df.empty:
            return pd.DataFrame()
        if "datetime" in df.columns:
            df["dt"] = pd.to_datetime(df["datetime"].str.strip(), errors="coerce")
        else:
            df["dt"] = pd.to_datetime(
                df["RunDate"].str.strip() + " " + df["RunTime"].str.strip(),
                errors="coerce",
            )
        return df.dropna(subset=["dt"]).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()
```

and change `_build_iostat_timeseries` to:

```python
def _build_iostat_timeseries(connection, interval: str) -> list:
    role_map = _load_iostat_role_map(connection)
    if not role_map:
        return []
    iostat_df = _load_iostat_df(connection)
    if iostat_df.empty:
        return []
    result = []
    for role, device in role_map.items():
        records = _resample_iostat(iostat_df, device, interval)
        if records:
            result.append({"role": role, "device": device, "records": records})
    return result
```

Run `python3 -m pytest tests/test_llm_context.py -v 2>&1 | tail -3` — all existing tests still PASS.

- [ ] **Step 2: Write failing tests**

Append to `tests/test_llm_context.py`:

```python
# ---- Key metrics + not_available ----
from llm_context import _compute_key_metrics, _build_not_available


def _make_iostat_role_df(n=20):
    """iostat rows for one Database device (dm-3) and one IRIS device (dm-9)."""
    base = datetime(2024, 1, 16, 9, 30, 0)
    rows = []
    for i in range(n):
        for dev, r_s, w_s, r_await, w_await in (("dm-3", 200.0, 100.0, 1.5, 0.8),
                                                ("dm-9", 5.0, 50.0, 0.5, 0.6)):
            rows.append({
                "dt": pd.Timestamp(base) + pd.Timedelta(seconds=60 * i),
                "Device": dev, "r/s": r_s, "w/s": w_s,
                "r_await": r_await, "w_await": w_await,
            })
    return pd.DataFrame(rows)


_FACTS = {"vcpus": 4, "ram_gb": 16, "iris_buffers_gb": 8, "version": "x", "os": "Linux"}
_ROLE_MAP = {"Database 0": "dm-3", "IRIS 0": "dm-9"}


def test_key_metrics_ratio_from_sums():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    # PhyRds=50, PhyWrs=20 constant → sum ratio = 2.5
    assert km["overall"]["physical_read_write_ratio"]["value"] == pytest.approx(2.5)


def test_key_metrics_cpu_distribution():
    km = _compute_key_metrics(pd.DataFrame(), _make_vm_df_business_hours(), pd.DataFrame(), {}, _FACTS)
    cpu = km["overall"]["cpu_utilization"]["value"]
    assert cpu["mean"] == pytest.approx(40.0)
    assert "p95" in cpu


def test_key_metrics_glorefs_per_core():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    g = km["overall"]["glorefs_distribution"]["value"]
    gpc = km["overall"]["glorefs_per_core"]["value"]
    assert gpc["max"] == pytest.approx(g["max"] / 4)


def test_key_metrics_db_disk_from_role():
    km = _compute_key_metrics(pd.DataFrame(), pd.DataFrame(), _make_iostat_role_df(), _ROLE_MAP, _FACTS)
    o = km["overall"]
    assert o["db_disk_reads_per_sec"]["value"]["mean"] == pytest.approx(200.0)
    assert o["db_disk_read_response_ms"]["value"]["mean"] == pytest.approx(1.5)
    assert o["db_disk_read_write_ratio"]["value"] == pytest.approx(2.0)


def test_key_metrics_ppg_conditional():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    assert "ppg_update_rate" not in km["overall"]
    mg["PPGupds"] = 250.0
    km2 = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    assert km2["overall"]["ppg_update_rate"]["value"]["mean"] == pytest.approx(250.0)
    assert km2["overall"]["ppg_to_global_update_ratio"]["value"] == pytest.approx(0.5)


def test_key_metrics_max_memory():
    # free=8000000 KB + cache=2000000 KB of 16 GB (16777216 KB) → used ≈ 40.4%
    vm = _make_vm_df_business_hours()
    vm["free"] = 8000000
    vm["cache"] = 2000000
    km = _compute_key_metrics(pd.DataFrame(), vm, pd.DataFrame(), {}, _FACTS)
    val = km["overall"]["max_memory_utilization_pct"]["value"]
    assert val == pytest.approx((16 * 1024 * 1024 - 10000000) / (16 * 1024 * 1024) * 100, abs=0.5)


def test_key_metrics_peak_period():
    mg = _make_mg_df_business_hours()
    km = _compute_key_metrics(mg, pd.DataFrame(), pd.DataFrame(), {}, _FACTS)
    peak = km["peak_period"]
    assert peak["weekday"] == "Tuesday"
    assert peak["period"] == "09:00–11:30"
    assert "glorefs_distribution" in peak["metrics"]


def test_not_available_static_entries():
    na = _build_not_available(pd.DataFrame(), {})
    metrics = [e["metric"] for e in na]
    assert any("transaction rate" in m for m in metrics)
    assert any("kill" in m for m in metrics)
    assert all({"metric", "reason", "how_to_collect"} <= set(e) for e in na)


def test_not_available_ppg_conditional():
    mg = _make_mg_df_business_hours()
    na = _build_not_available(mg, {"Database 0": "dm-3"})
    assert any("PPG" in e["metric"] for e in na)
    mg["PPGupds"] = 1.0
    na2 = _build_not_available(mg, {"Database 0": "dm-3"})
    assert not any("PPG" in e["metric"] for e in na2)


def test_not_available_db_disk_conditional():
    na = _build_not_available(pd.DataFrame(), {})
    assert any("disk" in e["metric"].lower() for e in na)
    na2 = _build_not_available(pd.DataFrame(), {"Database 0": "dm-3"})
    assert not any(e["metric"] == "database disk I/O metrics" for e in na2)
```

- [ ] **Step 3: Run to verify failure**

```bash
python3 -m pytest tests/test_llm_context.py -k "key_metrics or not_available" -v
```

Expected: FAIL with `ImportError: cannot import name '_compute_key_metrics'`

- [ ] **Step 4: Implement**

Add to `llm_context.py`:

```python
def _sum_ratio(num, den) -> Optional[float]:
    """Ratio of sums; None if denominator sums to <= 0."""
    num = pd.to_numeric(num, errors="coerce").dropna()
    den = pd.to_numeric(den, errors="coerce").dropna()
    total = float(den.sum())
    if total <= 0:
        return None
    return float(num.sum()) / total


def _role_devices(role_map: dict, prefix: str) -> list:
    return [dev for label, dev in role_map.items() if label.startswith(prefix)]


def _db_disk_metrics(iostat_df: pd.DataFrame, devices: list) -> dict:
    """Database-role disk scorecard entries. Rates summed across devices; response times from worst device."""
    entries = {}
    sub = iostat_df[iostat_df["Device"].isin(devices)]
    if sub.empty:
        return entries

    rate_cols = [c for c in ("r/s", "w/s") if c in sub.columns]
    if rate_cols:
        rates = sub.groupby("dt")[rate_cols].sum()
        if "r/s" in rates.columns:
            stats = _series_stats(rates["r/s"])
            if stats:
                entries["db_disk_reads_per_sec"] = {
                    "value": stats, "basis": "iostat r/s summed across Database-role devices"}
        if "w/s" in rates.columns:
            stats = _series_stats(rates["w/s"])
            if stats:
                entries["db_disk_writes_per_sec"] = {
                    "value": stats, "basis": "iostat w/s summed across Database-role devices"}
        if {"r/s", "w/s"} <= set(rates.columns):
            ratio = _sum_ratio(rates["r/s"], rates["w/s"])
            if ratio is not None:
                entries["db_disk_read_write_ratio"] = {
                    "value": ratio, "basis": "sum(r/s) / sum(w/s) on Database-role devices"}

    for col, name, label in (("r_await", "db_disk_read_response_ms", "read"),
                             ("w_await", "db_disk_write_response_ms", "write")):
        if col not in sub.columns:
            continue
        worst, worst_dev = None, None
        for dev in devices:
            stats = _series_stats(sub[sub["Device"] == dev][col])
            if stats and (worst is None or stats["p95"] > worst["p95"]):
                worst, worst_dev = stats, dev
        if worst:
            entries[name] = {
                "value": worst,
                "basis": f"iostat {col} on worst Database-role device ({worst_dev}, highest p95)"}
    return entries


def _key_metrics_slice(mg_df, vm_df, iostat_df, role_map, facts) -> dict:
    """Scorecard entries computable from the given (already time-filtered) frames."""
    km = {}
    ram_gb = facts.get("ram_gb")
    vcpus = facts.get("vcpus")

    if vm_df is not None and not vm_df.empty:
        mem_cols = [c for c in ("free", "buff", "cache") if c in vm_df.columns]
        if mem_cols and ram_gb:
            ram_kb = ram_gb * 1024 * 1024
            avail = vm_df[mem_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
            used_pct = ((ram_kb - avail) / ram_kb * 100).dropna()
            if not used_pct.empty:
                km["max_memory_utilization_pct"] = {
                    "value": float(used_pct.max()),
                    "basis": "max of (RAM − (free+buff+cache)) / RAM from vmstat",
                    "caveat": "page cache counted as used; reclaimable in practice"}
        if "us" in vm_df.columns and "sy" in vm_df.columns:
            us_sy = (pd.to_numeric(vm_df["us"], errors="coerce")
                     + pd.to_numeric(vm_df["sy"], errors="coerce"))
            stats = _series_stats(us_sy)
            if stats:
                km["cpu_utilization"] = {
                    "value": stats, "basis": "vmstat us+sy; p95 is the headline number"}

    if mg_df is not None and not mg_df.empty:
        if "Glorefs" in mg_df.columns:
            stats = _series_stats(mg_df["Glorefs"])
            if stats:
                km["glorefs_distribution"] = {
                    "value": stats, "basis": "mgstat Glorefs; p90 is the headline number"}
                if vcpus:
                    km["glorefs_per_core"] = {
                        "value": {k: stats[k] / vcpus for k in ("mean", "p90", "p95", "max")},
                        "basis": f"Glorefs ÷ {vcpus} vCPUs — capacity benchmark"}
        if "Gloupds" in mg_df.columns:
            stats = _series_stats(mg_df["Gloupds"])
            if stats:
                km["global_update_rate"] = {"value": stats, "basis": "mgstat Gloupds"}
        if {"PhyRds", "PhyWrs"} <= set(mg_df.columns):
            ratio = _sum_ratio(mg_df["PhyRds"], mg_df["PhyWrs"])
            if ratio is not None:
                km["physical_read_write_ratio"] = {
                    "value": ratio, "basis": "sum(PhyRds) / sum(PhyWrs)"}
        if {"Rdratio", "PhyRds"} <= set(mg_df.columns):
            rr = pd.to_numeric(mg_df["Rdratio"], errors="coerce")
            pr = pd.to_numeric(mg_df["PhyRds"], errors="coerce")
            logical = (rr * pr).dropna()
            denom = float(pr.dropna().sum())
            if denom > 0 and not logical.empty:
                agg_rdratio = float(logical.sum()) / denom
                if agg_rdratio > 1:
                    km["global_cache_hit_ratio_pct"] = {
                        "value": (1 - 1 / agg_rdratio) * 100,
                        "basis": "1 − 1/Rdratio with Rdratio = sum(Rdratio×PhyRds)/sum(PhyRds)",
                        "caveat": "block-level approximation of cache hit ratio"}
        if "PPGupds" in mg_df.columns:
            stats = _series_stats(mg_df["PPGupds"])
            if stats:
                km["ppg_update_rate"] = {"value": stats, "basis": "mgstat PPGupds"}
            if "Gloupds" in mg_df.columns:
                ratio = _sum_ratio(mg_df["PPGupds"], mg_df["Gloupds"])
                if ratio is not None:
                    km["ppg_to_global_update_ratio"] = {
                        "value": ratio, "basis": "sum(PPGupds) / sum(Gloupds)"}

    db_devices = _role_devices(role_map, "Database")
    if iostat_df is not None and not iostat_df.empty and db_devices:
        km.update(_db_disk_metrics(iostat_df, db_devices))

    iris_devices = _role_devices(role_map, "IRIS")
    if (iostat_df is not None and not iostat_df.empty and iris_devices
            and mg_df is not None and not mg_df.empty
            and "PPGupds" in mg_df.columns and "w/s" in iostat_df.columns):
        sub = iostat_df[iostat_df["Device"].isin(iris_devices)]
        ws_mean = pd.to_numeric(sub["w/s"], errors="coerce").dropna().mean() if not sub.empty else None
        ppg_mean = pd.to_numeric(mg_df["PPGupds"], errors="coerce").dropna().mean()
        if ws_mean and ws_mean > 0 and pd.notna(ppg_mean):
            km["ppg_to_iristemp_writes_ratio"] = {
                "value": float(ppg_mean) / float(ws_mean),
                "basis": "mean(PPGupds) / mean(w/s on IRIS-role devices) — cross-source, mean-based",
                "caveat": "IRIS-role device carries more than IRISTEMP"}
    return km


def _slice_by_period(df, weekday: str, period: str):
    if df is None or df.empty or "dt" not in getattr(df, "columns", []):
        return pd.DataFrame()
    d = _add_period_cols(df)
    return d[(d["_weekday"] == weekday) & (d["_period"] == period)]


def _compute_key_metrics(mg_df, vm_df, iostat_df, role_map, facts) -> dict:
    """Analyst scorecard: overall window plus the peak (highest mean Glorefs) weekday×period."""
    overall = _key_metrics_slice(mg_df, vm_df, iostat_df, role_map, facts)
    peak = None
    if mg_df is not None and not mg_df.empty and "Glorefs" in mg_df.columns:
        dfp = _add_period_cols(mg_df)
        if not dfp.empty:
            means = dfp.groupby(["_weekday", "_period"])["Glorefs"].mean()
            if not means.empty:
                weekday, period = means.idxmax()
                peak = {
                    "weekday": weekday,
                    "period": period,
                    "metrics": _key_metrics_slice(
                        _slice_by_period(mg_df, weekday, period),
                        _slice_by_period(vm_df, weekday, period),
                        _slice_by_period(iostat_df, weekday, period),
                        role_map, facts),
                }
    return {"overall": overall, "peak_period": peak}


def _build_not_available(mg_df, role_map) -> list:
    """Metrics this dataset cannot provide, with collection advice. Seeds the LLM's data-request list."""
    na = [
        {"metric": "transaction rate",
         "reason": "journal files are not part of a SystemPerformance capture",
         "how_to_collect": "journal file analysis (Begin/Commit records)"},
        {"metric": "global updates per transaction",
         "reason": "requires the journal-derived transaction rate",
         "how_to_collect": "journal file analysis"},
        {"metric": "ECP synch rate",
         "reason": "ECP synch records live in journal files",
         "how_to_collect": "journal file analysis"},
        {"metric": "global kill rate",
         "reason": "mgstat Gloupds merges sets and kills",
         "how_to_collect": "^GLOSTAT collection"},
        {"metric": "bitsets rate / bitsets-to-update ratio",
         "reason": "not reported by mgstat",
         "how_to_collect": "^GLOSTAT collection"},
        {"metric": "max IRIS / user processes",
         "reason": "process counts are not captured as a timeseries",
         "how_to_collect": "license/process count monitoring during the window"},
        {"metric": "average memory per IRIS process",
         "reason": "per-process memory is not captured",
         "how_to_collect": "periodic ps RSS sampling"},
        {"metric": "routine buffer statistics",
         "reason": "irisstat -R output is not in standard profiles",
         "how_to_collect": "irisstat -R snapshots"},
    ]
    has_ppg = mg_df is not None and not mg_df.empty and "PPGupds" in mg_df.columns
    if not has_ppg:
        na.append({"metric": "PPG update rate and ratios",
                   "reason": "mgstat from this IRIS version has no PPGupds column",
                   "how_to_collect": "capture from a newer IRIS version or ^GLOSTAT"})
    if not _role_devices(role_map, "Database"):
        na.append({"metric": "database disk I/O metrics",
                   "reason": "no Database-role device identified (CPF or iostat missing from capture)",
                   "how_to_collect": "re-run yaspe on a capture containing the CPF and iostat sections"})
    return na
```

- [ ] **Step 5: Run to verify pass, then the whole file**

```bash
python3 -m pytest tests/test_llm_context.py -v 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: analyst key-metrics scorecard and not-available list"
```

---

## Task 4: Anonymization scrub

**Files:**
- Modify: `llm_context.py`
- Test: `tests/test_llm_context.py`

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `_gather_secrets(sp_dict) -> list[str]` — identifying strings, longest first; short/allowlisted dropped
  - `_scrub(obj, secrets) -> obj` — recursive, case-insensitive, word-boundary redaction; never raises

- [ ] **Step 1: Write failing tests**

Append to `tests/test_llm_context.py`:

```python
# ---- Anonymization scrub ----
from llm_context import _gather_secrets, _scrub


def test_gather_secrets_collects_identifiers():
    sp = {"customer": "Acme Hospital", "linux hostname": "acmedb01.acme.local",
          "instance": "ACMEPROD", "up instance 1": "ACMEPROD on machine acmedb01"}
    secrets = _gather_secrets(sp)
    assert "Acme Hospital" in secrets
    assert "acmedb01.acme.local" in secrets
    assert "acmedb01" in secrets          # short-hostname variant of the FQDN
    assert "ACMEPROD" in secrets


def test_gather_secrets_skips_short_and_allowlisted():
    sp = {"customer": "abc", "instance": "IRIS", "linux hostname": "prod"}
    assert _gather_secrets(sp) == []


def test_gather_secrets_longest_first():
    sp = {"customer": "Acme", "linux hostname": "acmedb01.acme.local"}
    secrets = _gather_secrets(sp)
    assert secrets[0] == "acmedb01.acme.local"


def test_scrub_redacts_case_insensitive_nested():
    secrets = ["Acme Hospital", "acmedb01"]
    obj = {"note": "Users at ACME HOSPITAL reported slowness",
           "list": [{"deep": "host acmedb01 was rebooted"}]}
    out = _scrub(obj, secrets)
    assert out["note"] == "Users at [redacted] reported slowness"
    assert out["list"][0]["deep"] == "host [redacted] was rebooted"


def test_scrub_word_boundary_no_partial_mangling():
    out = _scrub("The acmedb011 host and acmedb01 host", ["acmedb01"])
    # acmedb011 is a different token — must NOT be redacted
    assert out == "The acmedb011 host and [redacted] host"


def test_scrub_non_string_passthrough():
    assert _scrub(42, ["secret"]) == 42
    assert _scrub(None, ["secret"]) is None
    assert _scrub(3.14, ["secret"]) == 3.14


def test_scrub_empty_secrets_identity():
    obj = {"a": "unchanged"}
    assert _scrub(obj, []) == obj
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_llm_context.py -k scrub -v
```

Expected: FAIL, `ImportError: cannot import name '_gather_secrets'`

- [ ] **Step 3: Implement**

Add `import re` to the stdlib imports of `llm_context.py`, then:

```python
_SCRUB_ALLOWLIST = {"IRIS", "LINUX", "TEST", "PROD", "DEV", "LIVE"}
_REDACTED = "[redacted]"


def _gather_secrets(sp_dict: dict) -> list:
    """
    Identifying strings from sp_dict (customer, hostname, instance names),
    plus short-hostname variants of FQDNs. Longest first so FQDNs are
    redacted before their prefixes. Secrets < 4 chars or on the allowlist
    are dropped (an instance literally named IRIS must not shred output).
    """
    if not sp_dict:
        return []
    raw = []
    for key in ("customer", "linux hostname", "instance"):
        value = sp_dict.get(key)
        if value:
            raw.append(str(value).strip())
    for key, value in sp_dict.items():
        if key.startswith("up instance") and value:
            raw.append(str(value).strip())
    secrets = set()
    for value in raw:
        if value:
            secrets.add(value)
            if "." in value:
                secrets.add(value.split(".", 1)[0])
    keep = [s for s in secrets if len(s) >= 4 and s.upper() not in _SCRUB_ALLOWLIST]
    return sorted(keep, key=len, reverse=True)


def _scrub(obj, secrets: list):
    """
    Recursively redact secrets in all strings of a dict/list structure.
    Case-insensitive, word-boundary matched. Best-effort: never raises.
    """
    if not secrets:
        return obj
    try:
        if isinstance(obj, str):
            for secret in secrets:
                pattern = re.compile(
                    r"(?<![A-Za-z0-9])" + re.escape(secret) + r"(?![A-Za-z0-9])",
                    re.IGNORECASE,
                )
                obj = pattern.sub(_REDACTED, obj)
            return obj
        if isinstance(obj, dict):
            return {k: _scrub(v, secrets) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_scrub(v, secrets) for v in obj]
        return obj
    except Exception:
        return obj
```

Note on `test_gather_secrets_collects_identifiers`: the value `"ACMEPROD on machine acmedb01"` from `up instance 1` is itself a secret string — the whole phrase gets added, plus `customer`/`hostname`/`instance` values. The assertions only check that the four expected strings are present; extra entries are fine.

- [ ] **Step 4: Run to verify pass, then whole file**

```bash
python3 -m pytest tests/test_llm_context.py -v 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: anonymization scrub for LLM context export"
```

---

## Task 5: `build_llm_context()` schema 2.0

**Files:**
- Modify: `llm_context.py` (`build_llm_context` only)
- Test: `tests/test_llm_context.py`

**Interfaces:**
- Consumes: `_compute_period_stats` (Task 2), `_compute_key_metrics`, `_build_not_available`, `_load_iostat_df`, `_load_iostat_role_map` (Task 3), `_gather_secrets`, `_scrub` (Task 4)
- Produces:
  - `_auto_resample_interval(n_days) -> str` — `"5min"` for ≤2 days (or None), `"15min"` for 3–4, `"30min"` for ≥5
  - `build_llm_context(connection, sp_dict, resample_interval=None, context=None) -> dict` with keys `schema_version ("2.0"), generated_by, context, system (NO customer), collection, baselines, findings, period_stats, key_metrics, not_available, timeseries` — fully scrubbed; `resample_interval=None` resolves via `_auto_resample_interval(meta["n_days"])`

- [ ] **Step 1: Update existing tests and add new ones**

In `tests/test_llm_context.py` modify:

- `test_build_llm_context_top_level_keys`: change the schema assertion and add the new keys:

```python
    assert result["schema_version"] == "2.0"
    for key in ("system", "collection", "baselines", "findings",
                "period_stats", "key_metrics", "not_available", "timeseries"):
        assert key in result
```

- `test_build_llm_context_system_facts`: add at the end (before `conn.close()`):

```python
    assert "customer" not in result["system"]
```

Then append new tests:

```python
# ---- Schema 2.0 integration ----

def test_build_llm_context_no_customer_even_when_present():
    conn = _make_sqlite_with_data()
    sp_dict = {"number cpus": "4", "customer": "Acme Hospital"}
    result = build_llm_context(conn, sp_dict)
    assert "customer" not in result["system"]
    conn.close()


def test_build_llm_context_scrubs_context_note():
    conn = _make_sqlite_with_data()
    sp_dict = {"customer": "Acme Hospital", "linux hostname": "acmedb01"}
    result = build_llm_context(conn, sp_dict, context="Acme Hospital users on acmedb01 reported slowness")
    assert "Acme Hospital" not in result["context"]
    assert "acmedb01" not in result["context"]
    assert "[redacted]" in result["context"]
    conn.close()


def test_build_llm_context_period_stats_populated():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {})
    assert isinstance(result["period_stats"], list)
    # _make_sqlite_with_data rows start 09:00 → inside 09:00–11:30
    assert result["period_stats"], "expected at least one period bucket"
    assert "Glorefs" in result["period_stats"][0]["metrics"]
    conn.close()


def test_build_llm_context_key_metrics_populated():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {"number cpus": "4", "memory MB": "16384"})
    assert "physical_read_write_ratio" in result["key_metrics"]["overall"]
    assert result["key_metrics"]["peak_period"] is not None
    conn.close()


def test_build_llm_context_not_available_populated():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {})
    assert any("transaction rate" in e["metric"] for e in result["not_available"])
    conn.close()


def test_auto_resample_interval_boundaries():
    from llm_context import _auto_resample_interval
    assert _auto_resample_interval(None) == "5min"
    assert _auto_resample_interval(1) == "5min"
    assert _auto_resample_interval(2) == "5min"
    assert _auto_resample_interval(3) == "15min"
    assert _auto_resample_interval(4) == "15min"
    assert _auto_resample_interval(5) == "30min"
    assert _auto_resample_interval(7) == "30min"


def test_build_llm_context_auto_resample_default():
    conn = _make_sqlite_with_data()
    # fixture is a single day → auto resolves to 5min
    result = build_llm_context(conn, {})
    assert result["timeseries"]["resample_interval"] == "5min"
    conn.close()


def test_build_llm_context_explicit_resample_wins():
    conn = _make_sqlite_with_data()
    result = build_llm_context(conn, {}, resample_interval="10min")
    assert result["timeseries"]["resample_interval"] == "10min"
    conn.close()
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_llm_context.py -k "build_llm_context" -v
```

Expected: schema/new-key assertions FAIL (schema is still "1.0", new keys missing).

- [ ] **Step 3: Update `build_llm_context`**

Add the auto-interval helper:

```python
def _auto_resample_interval(n_days) -> str:
    """Timeseries interval scaled to window length so bundles stay chat-sized."""
    if not n_days or n_days <= 2:
        return "5min"
    if n_days <= 4:
        return "15min"
    return "30min"
```

Modify the existing function: change the signature default to `resample_interval: Optional[str] = None`; after `meta = _pa._get_collection_meta(connection)` add:

```python
    if resample_interval is None:
        resample_interval = _auto_resample_interval(meta.get("n_days"))
```

After `facts = _pa._get_system_facts(sp_dict)` add `facts.pop("customer", None)`. After the timeseries assembly, add the new sections and scrub before returning:

```python
    role_map = _load_iostat_role_map(connection)
    iostat_df = _load_iostat_df(connection)

    period_stats = _compute_period_stats(mg_df, vm_df)
    key_metrics = _compute_key_metrics(mg_df, vm_df, iostat_df, role_map, facts)
    not_available = _build_not_available(mg_df, role_map)

    ctx = {
        "schema_version": "2.0",
        "generated_by":   "yaspe --llm-context",
        "context":        context,
        "system":         facts,
        "collection":     collection,
        "baselines":      baselines,
        "findings":       [_serialise_finding(f) for f in all_findings],
        "period_stats":   period_stats,
        "key_metrics":    key_metrics,
        "not_available":  not_available,
        "timeseries":     timeseries,
    }
    return _scrub(ctx, _gather_secrets(sp_dict or {}))
```

(`_build_iostat_timeseries` already loads its own frame; leave it as-is — the duplicate read is cheap and keeps the diff minimal.)

- [ ] **Step 4: Run the whole file; fix any old tests still asserting "1.0"**

```bash
python3 -m pytest tests/test_llm_context.py -v 2>&1 | tail -8
```

`test_export_llm_context_writes_file` asserts `data["schema_version"] == "1.0"` — change it to `"2.0"` (it gets fully reworked in Task 6 anyway). Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: schema 2.0 context — period stats, scorecard, not-available, scrubbed, no customer"
```

---

## Task 6: Markdown renderer

**Files:**
- Modify: `llm_context.py`
- Test: `tests/test_llm_context.py`

**Interfaces:**
- Consumes: the schema-2.0 dict from `build_llm_context`
- Produces:
  - `_fmt_num(v, ratio=False) -> str` — rounding rules; empty string for None
  - `_csv_block(records, columns) -> str` — fenced ```` ```csv ```` block
  - `_render_markdown(ctx) -> str` — the full bundle document

- [ ] **Step 1: Write failing tests**

Append to `tests/test_llm_context.py`:

```python
# ---- Markdown renderer ----
import io
from llm_context import _fmt_num, _csv_block, _render_markdown


def test_fmt_num_rules():
    assert _fmt_num(None) == ""
    assert _fmt_num(12345.678) == "12346"        # >=100 → integer
    assert _fmt_num(18.349) == "18.3"            # <100 → 1 decimal
    assert _fmt_num(2.5, ratio=True) == "2.50"   # ratio → 2 decimals
    assert _fmt_num(7) == "7"
    assert _fmt_num("2024-01-15 09:00:00") == "2024-01-15 09:00:00"


def test_csv_block_shape():
    records = [{"timestamp": "2024-01-15 09:00:00", "Glorefs": 10450.333, "us": None}]
    block = _csv_block(records, ["timestamp", "Glorefs", "us"])
    assert block.startswith("```csv\n")
    assert block.endswith("\n```")
    lines = block.splitlines()
    assert lines[1] == "timestamp,Glorefs,us"
    assert lines[2] == "2024-01-15 09:00:00,10450,"   # rounded, empty cell for None


def _built_ctx():
    conn = _make_sqlite_with_data()
    ctx = build_llm_context(conn, {"number cpus": "4", "memory MB": "16384"},
                            context="users reported slowness")
    conn.close()
    return ctx


def test_render_markdown_yaml_header():
    md = _render_markdown(_built_ctx())
    assert md.startswith("---\n")
    header = md.split("---")[1]
    assert 'schema_version: "2.0"' in header
    assert "customer" not in header
    import yaml
    parsed = yaml.safe_load(header)
    assert parsed["schema_version"] == "2.0"
    assert parsed["system"]["vcpus"] == 4


def test_render_markdown_sections_present():
    md = _render_markdown(_built_ctx())
    for heading in ("## Findings", "## Key metrics", "## Not available",
                    "## Period statistics", "## Timeseries"):
        assert heading in md, f"missing {heading}"


def test_render_markdown_timeseries_csv_roundtrip():
    md = _render_markdown(_built_ctx())
    ts_section = md.split("## Timeseries")[1]
    csv_text = ts_section.split("```csv\n")[1].split("\n```")[0]
    df = pd.read_csv(io.StringIO(csv_text))
    assert "timestamp" in df.columns
    assert "Glorefs" in df.columns
    assert len(df) > 0


def test_render_markdown_no_full_float_repr():
    md = _render_markdown(_built_ctx())
    import re as _re
    assert not _re.search(r"\d+\.\d{4,}", md), "unrounded float leaked into bundle"
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_llm_context.py -k "fmt_num or csv_block or render_markdown" -v
```

Expected: `ImportError: cannot import name '_fmt_num'`

- [ ] **Step 3: Implement the renderer**

Add to `llm_context.py`:

```python
def _fmt_num(v, ratio: bool = False) -> str:
    """Rounded string form: ratios 2dp, >=100 integer, else 1dp. None -> empty."""
    if v is None:
        return ""
    if isinstance(v, bool) or isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if ratio:
            return f"{v:.2f}"
        if abs(v) >= 100:
            return f"{v:.0f}"
        return f"{v:.1f}"
    return str(v)


def _csv_block(records: list, columns: list) -> str:
    """Fenced csv block; header once, None -> empty cell, floats rounded."""
    lines = [",".join(columns)]
    for rec in records:
        lines.append(",".join(_fmt_num(rec.get(col)) for col in columns))
    return "```csv\n" + "\n".join(lines) + "\n```"


def _ordered_columns(records: list) -> list:
    cols = ["timestamp"]
    for rec in records:
        for key in rec:
            if key not in cols:
                cols.append(key)
    return cols


def _yaml_header(ctx: dict) -> str:
    y = ["---",
         f'schema_version: "{ctx["schema_version"]}"',
         f'generated_by: {ctx["generated_by"]}']
    if ctx.get("context"):
        y.append(f'context: "{ctx["context"]}"')
    y.append("system:")
    for key, value in ctx["system"].items():
        y.append(f"  {key}: {value if value is not None else 'null'}")
    coll = ctx["collection"]
    y.append("collection:")
    for key in ("start", "end", "n_days", "interval_seconds"):
        value = coll.get(key)
        if value is None:
            y.append(f"  {key}: null")
        elif key in ("start", "end"):
            y.append(f'  {key}: "{value}"')     # contains spaces/colons — YAML needs quoting
        else:
            y.append(f"  {key}: {value}")
    y.append(f"  weekdays: [{', '.join(coll.get('weekdays') or [])}]")
    gaps = coll.get("gaps") or []
    if gaps:
        y.append("  gaps:")
        for gap in gaps:
            y.append(f'    - ["{gap[0]}", "{gap[1]}"]')
    else:
        y.append("  gaps: []")
    y.append("---")
    return "\n".join(y)
```

Continue with the section renderers:

```python
def _render_key_metrics_table(title: str, metrics: dict) -> str:
    rows = [f"### {title}", "",
            "| Metric | Mean | p90 | p95 | Max | Value | Basis | Caveat |",
            "|---|---|---|---|---|---|---|---|"]
    for name, entry in metrics.items():
        value = entry.get("value")
        is_ratio = "_ratio" in name
        basis = entry.get("basis", "")
        caveat = entry.get("caveat", "")
        if isinstance(value, dict):
            rows.append(
                f"| {name} | {_fmt_num(value.get('mean'))} | {_fmt_num(value.get('p90'))} "
                f"| {_fmt_num(value.get('p95'))} | {_fmt_num(value.get('max'))} |  | {basis} | {caveat} |")
        else:
            rows.append(f"| {name} |  |  |  |  | {_fmt_num(value, ratio=is_ratio)} | {basis} | {caveat} |")
    return "\n".join(rows)


def _render_markdown(ctx: dict) -> str:
    parts = [_yaml_header(ctx)]
    parts.append(
        "# Performance context bundle\n\n"
        "Anonymized IRIS/EHR performance capture produced by yaspe. "
        "Read alongside the companion prompt file (llm_analysis_prompt.md).")

    # Baselines
    baselines = ctx.get("baselines") or {}
    if baselines:
        rows = ["## Baselines", "",
                "Per IRIS Health Monitor period, from full-resolution mgstat.", "",
                "| Period | Metric | Mean | Sigma | p95 | Max |", "|---|---|---|---|---|---|"]
        for period, metrics in baselines.items():
            for metric, stats in metrics.items():
                rows.append(f"| {period} | {metric} | {_fmt_num(stats.get('mean'))} "
                            f"| {_fmt_num(stats.get('sigma'))} | {_fmt_num(stats.get('p95'))} "
                            f"| {_fmt_num(stats.get('max'))} |")
        parts.append("\n".join(rows))

    # Findings
    findings = ctx.get("findings") or []
    fparts = ["## Findings (pre-computed)", "",
              "Deterministic breach/correlation detections. Verify against the data; extend, do not parrot."]
    if findings:
        for f in findings:
            fparts.append(f"- **{f['severity']} — {f['metric']}**: {f['observation']}")
            if f.get("when"):
                fparts.append(f"  - When: {f['when']}")
            if f.get("corroborating"):
                fparts.append(f"  - Corroborating: {'; '.join(f['corroborating'])}")
            if f.get("hypotheses"):
                fparts.append(f"  - Hypotheses: {'; '.join(f['hypotheses'])}")
            if f.get("next_step"):
                fparts.append(f"  - Next step: {f['next_step']}")
    else:
        fparts.append("- No findings triggered.")
    parts.append("\n".join(fparts))

    # Key metrics
    km = ctx.get("key_metrics") or {}
    kparts = ["## Key metrics", "",
              "Analyst headline scorecard. Ratios are sums-based unless the basis says otherwise."]
    if km.get("overall"):
        kparts.append("")
        kparts.append(_render_key_metrics_table("Overall window", km["overall"]))
    peak = km.get("peak_period")
    if peak:
        kparts.append("")
        kparts.append(_render_key_metrics_table(
            f"Peak period — {peak['weekday']} {peak['period']} (highest mean Glorefs)",
            peak["metrics"]))
    parts.append("\n".join(kparts))

    # Not available
    na = ctx.get("not_available") or []
    if na:
        rows = ["## Not available", "",
                "Metrics this dataset cannot provide — candidates for the data-to-request list.", "",
                "| Metric | Reason | How to collect |", "|---|---|---|"]
        for entry in na:
            rows.append(f"| {entry['metric']} | {entry['reason']} | {entry['how_to_collect']} |")
        parts.append("\n".join(rows))

    # Period statistics
    ps = ctx.get("period_stats") or []
    if ps:
        records = []
        for entry in ps:
            for metric, stats in entry["metrics"].items():
                records.append({"weekday": entry["weekday"], "period": entry["period"],
                                "metric": metric, **stats})
        columns = ["weekday", "period", "metric", "mean", "sigma", "p90", "p95", "max", "n_samples"]
        parts.append("## Period statistics\n\n"
                     "Per weekday × IRIS period, from full-resolution samples (long format).\n\n"
                     + _csv_block(records, columns))

    # Timeseries
    ts = ctx.get("timeseries") or {}
    tparts = ["## Timeseries", "",
              f"Resampled to {ts.get('resample_interval')}. {ts.get('aggregation_notes', '')}"]
    records = ts.get("records") or []
    if records:
        tparts.append("")
        tparts.append("### mgstat + vmstat (merged)")
        tparts.append("")
        tparts.append(_csv_block(records, _ordered_columns(records)))
    for series in ts.get("iostat") or []:
        tparts.append("")
        tparts.append(f"### iostat — {series['role']} ({series['device']}), max per interval")
        tparts.append("")
        tparts.append(_csv_block(series["records"], _ordered_columns(series["records"])))
    parts.append("\n".join(tparts))

    return "\n\n".join(parts) + "\n"
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_llm_context.py -v 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: markdown bundle renderer with rounded CSV blocks and YAML header"
```

---

## Task 7: Prompt template, two-file export, CLI polish

**Files:**
- Modify: `llm_context.py` (`PROMPT_TEMPLATE`, rework `export_llm_context`)
- Modify: `yaspe.py` (help texts, two-path print)
- Test: `tests/test_llm_context.py`

**Interfaces:**
- Consumes: `build_llm_context`, `_render_markdown`
- Produces: `export_llm_context(connection, sp_dict, output_prefix, filepath, resample_interval="5min", context=None) -> tuple[str, str]` — `(bundle_path, prompt_path)`. **Return type changes from `str`.**

- [ ] **Step 1: Update export tests**

In `tests/test_llm_context.py`, replace the bodies of the three export tests:

```python
def test_export_llm_context_writes_bundle_and_prompt():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path, prompt_path = export_llm_context(
            connection=conn, sp_dict={"number cpus": "4"},
            output_prefix="test_", filepath=tmpdir)
        assert os.path.isfile(bundle_path) and bundle_path.endswith(".md")
        assert os.path.isfile(prompt_path) and prompt_path.endswith("llm_analysis_prompt.md")
        content = open(bundle_path).read()
        assert 'schema_version: "2.0"' in content
        assert "## Timeseries" in content
        prompt = open(prompt_path).read()
        assert "consecutive" in prompt.lower()      # methodology present
        assert "Glorefs" in prompt                  # KPI tables present
    conn.close()


def test_export_llm_context_filename_contains_dates():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path, _ = export_llm_context(conn, {}, output_prefix="", filepath=tmpdir)
        fname = os.path.basename(bundle_path)
        assert fname.startswith("performance_context_")
        assert fname.endswith(".md")
        assert "2024-01-15" in fname
    conn.close()


def test_export_llm_context_invalid_interval_raises():
    conn = _make_sqlite_with_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError):
            export_llm_context(conn, {}, output_prefix="", filepath=tmpdir,
                               resample_interval="bogus")
    conn.close()
```

Delete the old `test_export_llm_context_writes_file` if its name differs.

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_llm_context.py -k export -v
```

Expected: FAIL (export still returns a single JSON path).

- [ ] **Step 3: Add `PROMPT_TEMPLATE` and rework `export_llm_context`**

Add near the top of `llm_context.py` (after the column constants):

````python
PROMPT_TEMPLATE = """\
# IRIS Performance Review — LLM Analysis Prompt

You are an experienced InterSystems IRIS performance analyst. You have been
given a **performance context bundle** (a markdown file produced by yaspe from
a SystemPerformance / pButtons capture of an EHR-style application on IRIS,
typically RHEL). Your job: produce a narrative system-health summary suitable
for a performance review meeting.

The bundle is **anonymized** — customer name, hostnames, and instance names
were redacted by the tool. The reviewer you are working with holds the
identity and business context; ask them rather than guessing. If a `context`
note is present in the bundle header, treat it as the reviewer's own framing.

## 1. What is in the bundle

- **YAML header** — `system` (vCPUs, RAM GB, IRIS global buffers GB, IRIS
  version, OS) and `collection` (window start/end, days, weekdays, sample
  interval in seconds, gaps). Gaps are collection outages: call them out,
  never interpolate across them. vCPU count is required to interpret the run
  queue; if missing, ask.
- **Baselines** — per IRIS Health Monitor period mean/sigma/p95/max for the
  baseline-relative mgstat metrics. Use these to judge "normal for this site".
- **Findings (pre-computed)** — deterministic breach and correlation
  detections made by yaspe. They are hints, not conclusions: verify each
  against the period statistics and timeseries, look for what they missed,
  and correlate findings with each other. Do not simply restate them.
- **Key metrics** — the analyst scorecard (overall window and the peak
  period). Ratios are computed from sums unless the basis column says
  otherwise. Lead your review with these numbers.
- **Not available** — metrics this capture cannot provide. Put these in your
  "data to request" section; do not speculate about their values.
- **Period statistics** — CSV, long format: per weekday x period x metric,
  mean/sigma/p90/p95/max/n_samples, computed from full-resolution samples.
  This is your primary quantitative source — prefer it over recomputing from
  the timeseries.
- **Timeseries** — CSV resampled to the interval stated in the caption. Most
  columns are per-interval means; columns suffixed `_max` are per-interval
  maxima; iostat blocks are per-interval maxima for IRIS-role disks only.
  Use the timeseries for shape, timing, and cross-metric correlation — not
  for precise statistics (the resampling already smoothed the peaks).

## 2. Method

Work **period by period** — EHR workload is strongly cyclical and whole-window
averages hide everything. The periods (IRIS Health Monitor defaults) are:
00:15-02:45, 03:00-06:00, 06:15-08:45, 09:00-11:30, 11:45-13:15, 13:30-16:00,
16:15-18:00, 18:15-20:45, 21:00-23:59, per weekday.

Breach evaluation uses the **consecutive-readings rule**: 3+ consecutive
samples over the alert threshold = alert event; 5+ consecutive over warning =
warning event. A single spike is noted only if extreme. For baseline-relative
metrics the per-period lines are:

```
alert   = 2.0 x MAX(mean + 3*sigma, highest + sigma)
warning = 1.6 x MAX(base, mean + 2*sigma, highest)
```

If the capture covers a single day, baselines derive from quiet periods of
that same day — say so explicitly and lower your confidence accordingly.

## 3. KPI thresholds

### vmstat (OS)
| Metric | Base | Alert | Warning |
|---|---|---|---|
| r (run queue) | vCPUs | > 2x vCPUs sustained | > 1x vCPUs sustained |
| b (blocked) | 0 | > 10-25% of vCPUs sustained | > 1-2 sustained |
| us+sy (CPU %) | 50 | 85 | 75 |
| sy (share of total CPU) | 10% | > 50% of total in kernel | > 30% of total |
| wa (I/O wait %) | 5 | > 20% sustained | > 10% sustained |
| si / so (swap) | 0 | any sustained so > 0 | any non-zero si/so |

On a dedicated IRIS server **any sustained swapping is an alert** — the shared
memory segment (global buffers) must never page. High sy relative to us at
similar workload points at huge pages, NUMA, interrupts, or network — not
application load.

### mgstat (IRIS)
| Metric | Base | Alert | Warning |
|---|---|---|---|
| Glorefs | baseline/period | > 2x norm, OR sustained drop toward 0 in business hours (stall) | > 1.6x norm |
| Gloupds | baseline | > 2x norm | > 1.6x norm |
| Rdratio | baseline | sustained fall to < ~10% of norm | declining trend |
| PhyRds | ~17/s | > 2x norm sustained | > 1.6x norm |
| PhyWrs | baseline | > 2x norm | > 1.6x norm |
| WDQsz | 0 | growing across consecutive write-daemon cycles | persistently non-zero |
| Jrnwrts | ~17/s | > 2x norm | > 1.6x norm |
| RouLaS | ~0 warm | sustained high (routine buffer undersized) | persistently > 0 |

### iostat (IRIS-role disks; general guidance)
| Metric | Healthy (flash-era) | Concerning |
|---|---|---|
| r_await / w_await | < ~1-2 ms typical | sustained > 10 ms, or growing with queue |
| aqu-sz | low single digits | sustained growth alongside await |
| %util | workload-dependent | 100% plus rising await |

## 4. Correlation patterns to test

1. **User stall** — Glorefs drops sharply in business hours: check WDQsz,
   vmstat b, wa at the same timestamps. Rising together = storage-side stall;
   not rising = upstream/application cause.
2. **Buffer pool pressure** — Rdratio trending down while PhyRds trends up:
   global buffers undersized for the working set. Quantify (first vs last day).
3. **Write daemon strain** — WDQsz non-zero between cycles + rising wa +
   PhyWrs at norm: write-path (storage/WIJ/journal) latency.
4. **Memory danger** — free trending down + cache shrinking + any si/so:
   flag prominently even without user impact yet.
5. **Contention vs throughput** — Seize rising in proportion to Glorefs is
   normal scaling; ASeize fraction rising is genuine contention.
6. **Kernel overhead** — sy growing relative to us at similar Glorefs.
7. **Batch/backup window** — identify the overnight PhyWrs/Jrnwrts surge and
   confirm it ends before the morning ramp; overlap is a finding.

## 5. Required output

1. **Executive summary** (<= 5 sentences): overall verdict (Green/Yellow/Red),
   the one or two findings that matter, urgency.
2. **Collection overview**: window, interval, gaps, data-quality caveats.
3. **Workload profile**: peak periods with timestamps, day-over-day
   consistency, the batch window, key-metrics scorecard commentary.
4. **Findings by severity** — each with value, threshold, duration, timestamps
   and recurrence, corroborating metrics, ranked hypotheses (observation vs
   inference clearly separated), and a concrete next step.
5. **Unusual but explainable** items (e.g. backup-window I/O) so reviewers do
   not rediscover them.
6. **Data limitations and data to request** — seed from the bundle's
   "Not available" section plus anything you found yourself missing.

Style: prose narrative, not bullet spam. Every claim carries value, threshold,
and duration ("wa averaged 18% (warning >= 10%) for 22 minutes from 09:42") —
never vague. No finding without timestamps. No alarmism — a single 5-second
spike is not an event. If the data is healthy, say so plainly and keep it
short. Where the data cannot support a root cause, offer ranked hypotheses
and the question that would discriminate between them.

---
*Prompt generated by yaspe --llm-context. Methodology source:
docs/Performance analysis/ in the yaspe repository. Before sharing the bundle
externally, eyeball it — anonymization is best-effort and only redacts
identifiers found in the capture header.*
"""
````

Replace `export_llm_context` with:

```python
def export_llm_context(
    connection,
    sp_dict: dict,
    output_prefix: str,
    filepath: str,
    resample_interval: Optional[str] = None,
    context: Optional[str] = None,
) -> tuple:
    """
    Build and write the LLM context bundle and companion prompt.
    resample_interval None = auto (scaled to window length).
    Returns (bundle_path, prompt_path).
    """
    if resample_interval is not None:
        try:
            pd.tseries.frequencies.to_offset(resample_interval)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid resample interval: {resample_interval!r}. "
                "Examples: '5min', '10min', '1min'."
            )

    ctx = build_llm_context(connection, sp_dict, resample_interval, context)

    start_str = (ctx["collection"].get("start") or "unknown")[:10]
    end_str   = (ctx["collection"].get("end")   or "unknown")[:10]

    os.makedirs(filepath, exist_ok=True)

    bundle_path = os.path.join(
        filepath, f"{output_prefix}performance_context_{start_str}_{end_str}.md")
    with open(bundle_path, "w", encoding="utf-8") as fh:
        fh.write(_render_markdown(ctx))

    prompt_path = os.path.join(filepath, f"{output_prefix}llm_analysis_prompt.md")
    with open(prompt_path, "w", encoding="utf-8") as fh:
        fh.write(PROMPT_TEMPLATE)

    return bundle_path, prompt_path
```

`import json` may now be unused in `llm_context.py` — remove it if so (`grep -n "json" llm_context.py`).

- [ ] **Step 4: Update `yaspe.py`**

In the `--llm-context` call block:

```python
            bundle_path, prompt_path = _llm_context.export_llm_context(
                connection=llm_conn,
                sp_dict=sp_dict,
                output_prefix=output_prefix,
                filepath=filepath,
                resample_interval=resample_interval,
                context=context,
            )
            print(f"LLM context bundle: {bundle_path}")
            print(f"LLM analysis prompt: {prompt_path}")
```

Help-text updates:

```python
    parser.add_argument(
        "--llm-context",
        dest="llm_context",
        help="Export an anonymized markdown context bundle plus analysis prompt "
             "for LLM-based performance review (implies -s).",
        action="store_true",
    )
```

```python
    parser.add_argument(
        "--context",
        dest="context",
        help='Optional context note included in the LLM context bundle '
             '(e.g. "users reported slowness Tuesday").',
        action="store",
        default=None,
        metavar='"context string"',
    )
```

```python
    parser.add_argument(
        "--resample",
        dest="resample_interval",
        help="Resample interval for timeseries in the LLM context bundle. "
             "Default: auto — 5min for up to 2 days of data, 15min for 3-4, "
             "30min for 5+. Examples: 5min, 10min, 30min.",
        action="store",
        default=None,
        metavar="INTERVAL",
    )
```

Also change the `mainline(...)` parameter default from `resample_interval="5min"` to `resample_interval=None`.

- [ ] **Step 5: Run all tests**

```bash
python3 -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add llm_context.py yaspe.py tests/test_llm_context.py
git commit -m "feat: two-file LLM export — markdown bundle + companion analysis prompt"
```

---

## Task 8: README, smoke test, final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

```bash
grep -n "analysis\|llm" README.md | head -20
```

Remove/replace any `--analysis` documentation. Add (near the other flag docs, matching the README's existing style) a short section:

```markdown
### LLM-assisted performance review

`--llm-context` exports two files alongside the SQLite database:

- `{prefix}performance_context_{start}_{end}.md` — an anonymized data bundle:
  system facts, per-period statistics, an analyst key-metrics scorecard,
  pre-computed findings, and resampled mgstat/vmstat/iostat timeseries as CSV
  blocks. Customer name, hostnames, and instance names are redacted so the
  bundle can be used with public LLMs.
- `{prefix}llm_analysis_prompt.md` — the companion prompt: methodology,
  KPI thresholds, and the required output shape for a performance review.

Attach **both** files to your LLM chat of choice. Use `--context "note"` to
embed a free-text note (it is redacted like everything else) and `--resample`
to override the timeseries interval (default: auto — 5min for up to 2 days,
15min for 3–4, 30min for 5+, so multi-day bundles stay LLM-sized).

    ./yaspe.py -e yaspe_SystemPerformance.sqlite --llm-context -o yaspe

Anonymization is best-effort — eyeball the bundle before sharing it
externally.
```

- [ ] **Step 2: Smoke test against a real database**

A populated SQLite is needed. If `yaspe_SystemPerformance.sqlite` in the repo root is empty (it was at planning time), regenerate one from any sample SystemPerformance HTML first (ask the user for a sample file if none is at hand — do not fabricate data), then:

```bash
./yaspe.py -e <real>_SystemPerformance.sqlite --llm-context -o smoketest
head -60 smoketest_performance_context_*.md
grep -c "redacted" smoketest_performance_context_*.md   # informational
python3 -c "import yaml; yaml.safe_load(open([p for p in __import__('glob').glob('smoketest_performance_context_*.md')][0]).read().split('---')[1])"
```

Verify by eye: YAML header has no customer/hostname; CSV blocks look sane; both files printed by the CLI. Delete the smoke-test outputs afterwards.

- [ ] **Step 3: Full suite + flag checks**

```bash
python3 -m pytest tests/ 2>&1 | tail -3
./yaspe.py --analysis 2>&1 | head -2      # expect: unrecognized arguments
./yaspe.py --help | grep -A2 "llm-context"
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README — LLM context bundle workflow replaces --analysis"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Remove `--analysis` flag, call block, chart renderer | 1 |
| `--llm-context` implies `-s` | 1 |
| Trim `performance_analysis.py` to library; keep engine | 1 |
| `Finding.chart_request` + `ChartRequest` removed | 1 |
| `sync_engine.sh` untouched | global (no task touches it) |
| `period_stats` per weekday × period, p90+p95, full-resolution | 2 |
| `key_metrics` all 15 entries, sums-based ratios, peak period, multi-device rule | 3 |
| `not_available` static + conditional entries | 3 |
| Scrub: secrets from sp_dict, FQDN short forms, word-boundary, allowlist, never raises | 4 |
| `system.customer` removed at source | 5 |
| Schema `"2.0"`, scrub applied to whole dict incl. context note | 5 |
| Adaptive resample default (auto by n_days, explicit wins) | 5, 7 |
| Markdown bundle: YAML header, tables, fenced CSV, rounding rules | 6 |
| CSV round-trips via pandas; no full float repr | 6 |
| `PROMPT_TEMPLATE` with all 7 spec content sections | 7 |
| Two files written, both paths printed | 7 |
| README workflow docs | 8 |
| `bump2version minor` at release | global note |

**Placeholder scan:** none — every code step carries complete code.

**Type consistency:** `_series_stats` dict keys (`mean/sigma/p90/p95/max/n_samples`) used consistently in Tasks 2, 3, 6; `export_llm_context` returns `tuple` in Task 7 and `yaspe.py` unpacks two values in the same task; `_compute_key_metrics` shape `{"overall", "peak_period"}` matches renderer access in Task 6.
