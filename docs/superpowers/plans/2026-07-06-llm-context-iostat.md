# LLM Context iostat Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add IRIS-role-filtered iostat timeseries to the JSON produced by `--llm-context`, as a separate `timeseries.iostat` section omitted when no role devices are found.

**Architecture:** Three new private functions in `llm_context.py` — a role map loader, a per-device resampler, and an orchestrator — called from `build_llm_context()`. No changes to CLI, `export_llm_context()`, or any other file.

**Tech Stack:** Python 3.9, pandas, sqlite3 (via existing connection pattern)

## Global Constraints

- Branch: `feature/llm-context-clean`
- Python 3.9 compatible — no walrus operator, no `match` statements
- No new dependencies
- All 8 iostat metrics aggregated as **max** per interval
- JSON key names must be valid identifiers: `r/s` → `r_s`, `%util` → `util`, `aqu-sz` → `aqu_sz`, `rkB/s` → `rkB_s`, `wkB/s` → `wkB_s`
- Overview field pattern for roles: `iris disk role *` excluding fields containing `names` or `_mount`
- Section omitted (key absent) when `_build_iostat_timeseries` returns `[]`
- Follow existing patterns in `llm_context.py`: `_load_mg_df` / `_load_vm_df` for DataFrame loading, `pd.NamedAgg` for resampling

---

## File Map

| File | Change |
|------|--------|
| `llm_context.py` | Add `_IOSTAT_COLS`, `_load_iostat_role_map`, `_resample_iostat`, `_build_iostat_timeseries`; update `build_llm_context` and `aggregation_notes` |
| `tests/test_llm_context.py` | Add 7 new tests for the iostat functions |

---

### Task 1: Add `_load_iostat_role_map` and tests

**Files:**
- Modify: `llm_context.py` (after `_load_vm_df`, before `_run_correlation_tests`)
- Modify: `tests/test_llm_context.py` (append at end)

**Interfaces:**
- Produces: `_load_iostat_role_map(connection) -> dict` — e.g. `{"Database 0": "dm-5", "Primary Journal": "dm-8"}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_context.py`:

```python
# ---- Task: iostat role map ----
from llm_context import _load_iostat_role_map


def _make_conn_with_overview(rows):
    """rows: list of (field, value) tuples."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    for i, (field, value) in enumerate(rows):
        conn.execute("INSERT INTO overview VALUES (?,?,?)", (i, field, value))
    conn.commit()
    return conn


def test_load_iostat_role_map_empty_no_table():
    conn = sqlite3.connect(":memory:")
    result = _load_iostat_role_map(conn)
    assert result == {}
    conn.close()


def test_load_iostat_role_map_empty_no_role_rows():
    conn = _make_conn_with_overview([("customer", "ACME"), ("linux hostname", "srv1")])
    result = _load_iostat_role_map(conn)
    assert result == {}
    conn.close()


def test_load_iostat_role_map_filters_names_and_mount():
    conn = _make_conn_with_overview([
        ("iris disk role Database 0", "dm-5"),
        ("iris disk role Database 0 names", "IRISSYS,IRISLIB"),
        ("iris_disk_role_mount Database 0", "/trak/iris"),
        ("iris disk role Primary Journal", "dm-8"),
        ("iris_disk_role_mount Primary Journal", "/trak/jrnpri"),
    ])
    result = _load_iostat_role_map(conn)
    assert result == {"Database 0": "dm-5", "Primary Journal": "dm-8"}
    conn.close()


def test_load_iostat_role_map_returns_all_roles():
    conn = _make_conn_with_overview([
        ("iris disk role Database 0", "dm-5"),
        ("iris disk role Database 1", "dm-2"),
        ("iris disk role WIJ", "dm-3"),
        ("iris disk role Primary Journal", "dm-8"),
        ("iris disk role Alternate Journal", "dm-4"),
    ])
    result = _load_iostat_role_map(conn)
    assert len(result) == 5
    assert result["WIJ"] == "dm-3"
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
pytest tests/test_llm_context.py::test_load_iostat_role_map_empty_no_table \
       tests/test_llm_context.py::test_load_iostat_role_map_empty_no_role_rows \
       tests/test_llm_context.py::test_load_iostat_role_map_filters_names_and_mount \
       tests/test_llm_context.py::test_load_iostat_role_map_returns_all_roles -v
```

Expected: FAIL with `ImportError: cannot import name '_load_iostat_role_map'`

- [ ] **Step 3: Implement `_load_iostat_role_map` in `llm_context.py`**

Add after `_load_vm_df` (around line 160), before `_run_correlation_tests`:

```python
def _load_iostat_role_map(connection) -> dict:
    """
    Return {role_label: device} from overview 'iris disk role *' entries.
    Excludes 'names' and '_mount' variants. Returns {} on any error.
    """
    try:
        rows = connection.execute(
            "SELECT field, value FROM overview WHERE field LIKE 'iris disk role %'"
        ).fetchall()
    except Exception:
        return {}
    result = {}
    for field, value in rows:
        if "names" in field or "_mount" in field:
            continue
        # "iris disk role Database 0" -> "Database 0"
        label = field[len("iris disk role "):]
        result[label] = value
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_llm_context.py::test_load_iostat_role_map_empty_no_table \
       tests/test_llm_context.py::test_load_iostat_role_map_empty_no_role_rows \
       tests/test_llm_context.py::test_load_iostat_role_map_filters_names_and_mount \
       tests/test_llm_context.py::test_load_iostat_role_map_returns_all_roles -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: add _load_iostat_role_map to llm_context"
```

---

### Task 2: Add `_resample_iostat` and tests

**Files:**
- Modify: `llm_context.py` (after `_load_iostat_role_map`)
- Modify: `tests/test_llm_context.py` (append at end)

**Interfaces:**
- Consumes: nothing from earlier tasks (pure DataFrame function)
- Produces: `_resample_iostat(iostat_df: pd.DataFrame, device: str, interval: str) -> list[dict]`
  - `iostat_df` has columns: `Device`, `dt` (datetime64), `r/s`, `w/s`, `rkB/s`, `wkB/s`, `r_await`, `w_await`, `aqu-sz`, `%util`
  - Returns list of dicts with keys: `timestamp`, `r_s`, `w_s`, `rkB_s`, `wkB_s`, `r_await`, `w_await`, `aqu_sz`, `util`

- [ ] **Step 1: Add iostat column constant and write failing tests**

First, add the column constant to `llm_context.py` near the top (after `_VM_MAX_COLS`):

```python
# iostat columns included in timeseries (all aggregated as max)
_IOSTAT_COLS = ["r/s", "w/s", "rkB/s", "wkB/s", "r_await", "w_await", "aqu-sz", "%util"]

# mapping from iostat source column name to JSON-safe key
_IOSTAT_COL_MAP = {
    "r/s": "r_s",
    "w/s": "w_s",
    "rkB/s": "rkB_s",
    "wkB/s": "wkB_s",
    "r_await": "r_await",
    "w_await": "w_await",
    "aqu-sz": "aqu_sz",
    "%util": "util",
}
```

Then append to `tests/test_llm_context.py`:

```python
# ---- Task: _resample_iostat ----
from llm_context import _resample_iostat


def _make_iostat_df(device="dm-5", n=12):
    """12 rows at 30s intervals for one device."""
    base = datetime(2024, 1, 15, 9, 0, 0)
    rows = []
    for i in range(n):
        rows.append({
            "dt": pd.Timestamp(base) + pd.Timedelta(seconds=30 * i),
            "Device": device,
            "r/s": float(i),
            "w/s": float(i * 2),
            "rkB/s": float(i * 10),
            "wkB/s": float(i * 20),
            "r_await": float(i) * 0.1,
            "w_await": float(i) * 0.2,
            "aqu-sz": float(i) * 0.01,
            "%util": float(i),
        })
    return pd.DataFrame(rows)


def test_resample_iostat_returns_list():
    df = _make_iostat_df()
    result = _resample_iostat(df, "dm-5", "5min")
    assert isinstance(result, list)
    assert len(result) > 0


def test_resample_iostat_json_safe_keys():
    df = _make_iostat_df()
    result = _resample_iostat(df, "dm-5", "5min")
    rec = result[0]
    assert "timestamp" in rec
    assert "r_s" in rec
    assert "w_s" in rec
    assert "rkB_s" in rec
    assert "wkB_s" in rec
    assert "r_await" in rec
    assert "w_await" in rec
    assert "aqu_sz" in rec
    assert "util" in rec
    # original names must not appear
    assert "r/s" not in rec
    assert "%util" not in rec
    assert "aqu-sz" not in rec


def test_resample_iostat_all_max():
    df = _make_iostat_df(n=12)
    result = _resample_iostat(df, "dm-5", "5min")
    # r/s values 0..11; first 5min bucket (10 rows at 30s) max = 9
    assert result[0]["r_s"] == pytest.approx(9.0, abs=1.0)


def test_resample_iostat_unknown_device_returns_empty():
    df = _make_iostat_df(device="dm-5")
    result = _resample_iostat(df, "dm-99", "5min")
    assert result == []


def test_resample_iostat_timestamp_format():
    df = _make_iostat_df()
    result = _resample_iostat(df, "dm-5", "5min")
    datetime.strptime(result[0]["timestamp"], "%Y-%m-%d %H:%M:%S")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_llm_context.py::test_resample_iostat_returns_list \
       tests/test_llm_context.py::test_resample_iostat_json_safe_keys \
       tests/test_llm_context.py::test_resample_iostat_all_max \
       tests/test_llm_context.py::test_resample_iostat_unknown_device_returns_empty \
       tests/test_llm_context.py::test_resample_iostat_timestamp_format -v
```

Expected: FAIL with `ImportError: cannot import name '_resample_iostat'`

- [ ] **Step 3: Implement `_resample_iostat` in `llm_context.py`**

Add after `_load_iostat_role_map`:

```python
def _resample_iostat(iostat_df: pd.DataFrame, device: str, interval: str) -> list:
    """
    Resample iostat DataFrame for one device to interval.
    All 8 metrics aggregated as max. Returns [] if device not present.
    """
    df = iostat_df[iostat_df["Device"] == device].copy()
    if df.empty:
        return []

    df = df.set_index("dt").sort_index()

    agg = {}
    for src_col in _IOSTAT_COLS:
        if src_col in df.columns:
            json_key = _IOSTAT_COL_MAP[src_col]
            agg[json_key] = pd.NamedAgg(column=src_col, aggfunc="max")

    if not agg:
        return []

    resampled = df.resample(interval).agg(**agg).dropna(how="all").reset_index()
    resampled.rename(columns={"dt": "timestamp"}, inplace=True)
    resampled["timestamp"] = resampled["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    return resampled.where(resampled.notna(), None).to_dict(orient="records")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_llm_context.py::test_resample_iostat_returns_list \
       tests/test_llm_context.py::test_resample_iostat_json_safe_keys \
       tests/test_llm_context.py::test_resample_iostat_all_max \
       tests/test_llm_context.py::test_resample_iostat_unknown_device_returns_empty \
       tests/test_llm_context.py::test_resample_iostat_timestamp_format -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: add _resample_iostat to llm_context"
```

---

### Task 3: Add `_build_iostat_timeseries`, wire into `build_llm_context`, update tests

**Files:**
- Modify: `llm_context.py` — add `_build_iostat_timeseries`, update `build_llm_context`
- Modify: `tests/test_llm_context.py` — add integration tests

**Interfaces:**
- Consumes: `_load_iostat_role_map(connection)`, `_resample_iostat(df, device, interval)`
- Produces: `_build_iostat_timeseries(connection, interval) -> list[dict]`
  - Each element: `{"role": str, "device": str, "records": list[dict]}`

- [ ] **Step 1: Write failing integration tests**

Append to `tests/test_llm_context.py`:

```python
# ---- Task: _build_iostat_timeseries + build_llm_context integration ----
from llm_context import _build_iostat_timeseries


def _make_sqlite_with_iostat():
    """SQLite with overview roles + iostat table for dm-5 and dm-8."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    overview_rows = [
        (0, "iris disk role Database 0", "dm-5"),
        (1, "iris disk role Database 0 names", "IRISSYS,IRISLIB"),
        (2, "iris_disk_role_mount Database 0", "/trak/iris"),
        (3, "iris disk role Primary Journal", "dm-8"),
        (4, "iris_disk_role_mount Primary Journal", "/trak/jrnpri"),
    ]
    conn.executemany("INSERT INTO overview VALUES (?,?,?)", overview_rows)

    conn.execute("""
        CREATE TABLE iostat (
            id_key INTEGER, RunDate TEXT, RunTime TEXT, Device TEXT,
            "r/s" REAL, "w/s" REAL, "rkB/s" REAL, "wkB/s" REAL,
            "rrqm/s" REAL, "wrqm/s" REAL, "%rrqm" REAL, "%wrqm" REAL,
            r_await REAL, w_await REAL, "aqu-sz" REAL,
            "rareq-sz" REAL, "wareq-sz" REAL, svctm REAL, "%util" REAL,
            "html name" TEXT, datetime TEXT
        )
    """)
    from datetime import datetime, timedelta
    base = datetime(2024, 1, 15, 9, 0, 0)
    for i in range(20):
        ts = base + timedelta(seconds=30 * i)
        dt_str = ts.strftime("%Y/%m/%d %I:%M:%S %p")
        for device in ("dm-5", "dm-8"):
            conn.execute(
                """INSERT INTO iostat VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (i, ts.strftime("%Y/%m/%d"), ts.strftime("%I:%M:%S %p"), device,
                 float(i), float(i*2), float(i*10), float(i*20),
                 0.0, 0.0, 0.0, 0.0,
                 float(i)*0.1, float(i)*0.2, float(i)*0.01,
                 0.0, 0.0, 0.0, float(i),
                 "test_html", dt_str)
            )
    conn.commit()
    return conn


def test_build_iostat_timeseries_returns_list():
    conn = _make_sqlite_with_iostat()
    result = _build_iostat_timeseries(conn, "5min")
    assert isinstance(result, list)
    conn.close()


def test_build_iostat_timeseries_has_both_roles():
    conn = _make_sqlite_with_iostat()
    result = _build_iostat_timeseries(conn, "5min")
    roles = [r["role"] for r in result]
    assert "Database 0" in roles
    assert "Primary Journal" in roles
    conn.close()


def test_build_iostat_timeseries_role_structure():
    conn = _make_sqlite_with_iostat()
    result = _build_iostat_timeseries(conn, "5min")
    db_entry = next(r for r in result if r["role"] == "Database 0")
    assert db_entry["device"] == "dm-5"
    assert isinstance(db_entry["records"], list)
    assert len(db_entry["records"]) > 0
    rec = db_entry["records"][0]
    assert "timestamp" in rec
    assert "r_s" in rec
    assert "util" in rec
    conn.close()


def test_build_iostat_timeseries_empty_when_no_roles():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    conn.execute("CREATE TABLE iostat (id_key INTEGER, RunDate TEXT, RunTime TEXT, Device TEXT, datetime TEXT)")
    conn.commit()
    result = _build_iostat_timeseries(conn, "5min")
    assert result == []
    conn.close()


def test_build_iostat_timeseries_empty_when_no_iostat_table():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER, field TEXT, value TEXT)")
    conn.execute("INSERT INTO overview VALUES (0, 'iris disk role Database 0', 'dm-5')")
    conn.commit()
    result = _build_iostat_timeseries(conn, "5min")
    assert result == []
    conn.close()


def test_build_llm_context_iostat_present():
    conn = _make_sqlite_with_iostat()
    # Also need mgstat + vmstat for build_llm_context
    conn.execute("""
        CREATE TABLE mgstat (
            RunDate TEXT, RunTime TEXT,
            Glorefs REAL, PhyRds REAL, PhyWrs REAL, Gloupds REAL,
            Jrnwrts REAL, WDQsz REAL, Rdratio REAL, RouLaS REAL,
            Seize REAL, ASeize REAL
        )
    """)
    conn.execute("""
        CREATE TABLE vmstat (
            RunDate TEXT, RunTime TEXT,
            r REAL, b REAL, swpd REAL, free REAL, buff REAL, cache REAL,
            si REAL, so REAL, bi REAL, bo REAL, "in" REAL, cs REAL,
            us REAL, sy REAL, id REAL, wa REAL, st REAL
        )
    """)
    conn.commit()
    result = build_llm_context(conn, {})
    assert "iostat" in result["timeseries"]
    roles = [r["role"] for r in result["timeseries"]["iostat"]]
    assert "Database 0" in roles
    conn.close()


def test_build_llm_context_iostat_absent_when_no_table():
    conn = _make_sqlite_with_data()  # existing helper — no overview roles, no iostat table
    result = build_llm_context(conn, {})
    assert "iostat" not in result["timeseries"]
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_llm_context.py::test_build_iostat_timeseries_returns_list \
       tests/test_llm_context.py::test_build_iostat_timeseries_has_both_roles \
       tests/test_llm_context.py::test_build_iostat_timeseries_role_structure \
       tests/test_llm_context.py::test_build_iostat_timeseries_empty_when_no_roles \
       tests/test_llm_context.py::test_build_iostat_timeseries_empty_when_no_iostat_table \
       tests/test_llm_context.py::test_build_llm_context_iostat_present \
       tests/test_llm_context.py::test_build_llm_context_iostat_absent_when_no_table -v
```

Expected: FAIL with `ImportError: cannot import name '_build_iostat_timeseries'`

- [ ] **Step 3: Implement `_build_iostat_timeseries` in `llm_context.py`**

Add after `_resample_iostat`:

```python
def _build_iostat_timeseries(connection, interval: str) -> list:
    """
    Build iostat timeseries for IRIS-role devices only.
    Returns list of {role, device, records} dicts. Returns [] if no roles or no iostat table.
    """
    role_map = _load_iostat_role_map(connection)
    if not role_map:
        return []

    try:
        iostat_df = pd.read_sql_query("SELECT * FROM iostat", connection)
        if iostat_df.empty:
            return []
        if "datetime" in iostat_df.columns:
            iostat_df["dt"] = pd.to_datetime(iostat_df["datetime"].str.strip(), errors="coerce")
        else:
            iostat_df["dt"] = pd.to_datetime(
                iostat_df["RunDate"].str.strip() + " " + iostat_df["RunTime"].str.strip(),
                errors="coerce",
            )
        iostat_df = iostat_df.dropna(subset=["dt"]).reset_index(drop=True)
    except Exception:
        return []

    result = []
    for role, device in role_map.items():
        records = _resample_iostat(iostat_df, device, interval)
        if records:
            result.append({"role": role, "device": device, "records": records})
    return result
```

- [ ] **Step 4: Update `build_llm_context` to include iostat section**

In `build_llm_context`, replace the final `return` block's `timeseries` construction:

```python
    # Timeseries
    mg_records = _resample_mgstat(mg_df, resample_interval) if not mg_df.empty else []
    vm_records = _resample_vmstat(vm_df, resample_interval) if not vm_df.empty else []
    merged_records = _merge_timeseries(mg_records, vm_records)

    iostat_series = _build_iostat_timeseries(connection, resample_interval)

    timeseries = {
        "resample_interval": resample_interval,
        "aggregation_notes": (
            "Most metrics: mean per interval. "
            "r, b aggregated as max (suffixed _max). "
            "WDQsz aggregated as max (suffixed _max). "
            "us_sy derived = us_mean + sy_mean. "
            "iostat metrics (r_s, w_s, rkB_s, wkB_s, r_await, w_await, aqu_sz, util): "
            "max per interval, IRIS-role devices only."
        ),
        "records": merged_records,
    }
    if iostat_series:
        timeseries["iostat"] = iostat_series
```

Then update the `return` statement to use `timeseries` instead of the inline dict:

```python
    return {
        "schema_version": "1.0",
        "generated_by":   "yaspe --llm-context",
        "context":        context,
        "system":         facts,
        "collection":     collection,
        "baselines":      baselines,
        "findings":       [_serialise_finding(f) for f in all_findings],
        "timeseries":     timeseries,
    }
```

- [ ] **Step 5: Run all new tests**

```bash
pytest tests/test_llm_context.py::test_build_iostat_timeseries_returns_list \
       tests/test_llm_context.py::test_build_iostat_timeseries_has_both_roles \
       tests/test_llm_context.py::test_build_iostat_timeseries_role_structure \
       tests/test_llm_context.py::test_build_iostat_timeseries_empty_when_no_roles \
       tests/test_llm_context.py::test_build_iostat_timeseries_empty_when_no_iostat_table \
       tests/test_llm_context.py::test_build_llm_context_iostat_present \
       tests/test_llm_context.py::test_build_llm_context_iostat_absent_when_no_table -v
```

Expected: 7 passed

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
pytest tests/test_llm_context.py -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add llm_context.py tests/test_llm_context.py
git commit -m "feat: add iostat timeseries to LLM context export (IRIS-role devices only)"
```

---

### Task 4: Smoke test against real sample data

**Files:**
- No code changes — runtime verification only

- [ ] **Step 1: Run against the sample SQLite**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -c "
import sqlite3, json
import llm_context as lc

conn = sqlite3.connect('test_samples/1 day_sample/yaspe_SystemPerformance.sqlite')
rows = conn.execute('SELECT field, value FROM overview').fetchall()
sp_dict = {r[0]: r[1] for r in rows}
ctx = lc.build_llm_context(conn, sp_dict, resample_interval='5min')
ts = ctx['timeseries']
print('iostat present:', 'iostat' in ts)
if 'iostat' in ts:
    for entry in ts['iostat']:
        print(f\"  role={entry['role']} device={entry['device']} records={len(entry['records'])}\")
print('aggregation_notes:', ts['aggregation_notes'])
conn.close()
"
```

Expected output (roles may vary):
```
iostat present: True
  role=Database 0 device=dm-5 records=<N>
  role=Database 1 device=dm-2 records=<N>
  role=Primary Journal device=dm-8 records=<N>
  role=Alternate Journal device=dm-4 records=<N>
  role=WIJ device=dm-3 records=<N>
aggregation_notes: Most metrics: mean per interval. ... iostat metrics ...
```

- [ ] **Step 2: Verify JSON is serialisable**

```bash
python -c "
import sqlite3, json
import llm_context as lc

conn = sqlite3.connect('test_samples/1 day_sample/yaspe_SystemPerformance.sqlite')
rows = conn.execute('SELECT field, value FROM overview').fetchall()
sp_dict = {r[0]: r[1] for r in rows}
ctx = lc.build_llm_context(conn, sp_dict)
out = json.dumps(ctx)
print(f'JSON size: {len(out):,} bytes')
conn.close()
"
```

Expected: prints JSON size without raising

- [ ] **Step 3: Commit if any fixes were needed, otherwise no commit required**
