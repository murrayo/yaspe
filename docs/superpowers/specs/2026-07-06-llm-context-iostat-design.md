# Design spec: iostat data in LLM context export

**Date:** 2026-07-06  
**Branch:** feature/llm-context-clean  
**Relates to:** `llm_context.py`, `--llm-context` CLI flag

---

## Goal

Add per-device iostat timeseries to the JSON produced by `--llm-context`, filtered to only the IRIS-role devices identified by the CPF auto-disk work. The section is omitted entirely when no role devices are found or no iostat table exists.

---

## Data source

The overview table already contains IRIS role→device mappings written by the CPF disk resolver:

```
iris disk role Database 0     → dm-5
iris disk role Database 1     → dm-2
iris disk role Primary Journal → dm-8
iris disk role Alternate Journal → dm-4
iris disk role WIJ             → dm-3
```

These are the only devices included. All other devices (sda, sdb, dm-0, etc.) are ignored.

---

## Output shape

Added as `timeseries.iostat` — an array of role objects. The key is absent if the array would be empty.

```json
{
  "timeseries": {
    "resample_interval": "5min",
    "aggregation_notes": "...",
    "records": [...],
    "iostat": [
      {
        "role": "Database 0",
        "device": "dm-5",
        "records": [
          {
            "timestamp": "2026-06-09 00:05:00",
            "r_s": 9.2,
            "w_s": 77.4,
            "rkB_s": 268.1,
            "wkB_s": 1045.3,
            "r_await": 0.8,
            "w_await": 0.4,
            "aqu_sz": 0.04,
            "util": 4.8
          }
        ]
      }
    ]
  }
}
```

Column names use underscores (JSON-safe): `r/s` → `r_s`, `%util` → `util`, `aqu-sz` → `aqu_sz`.

---

## Aggregation

All 8 metrics aggregated as **max** per interval. Rationale: for storage diagnostics, peak latency and peak utilisation within a window are more meaningful than average — a 5-minute average can hide a 30-second spike that caused user-visible slowness.

| Source column | JSON key  | Aggregation |
|---------------|-----------|-------------|
| `r/s`         | `r_s`     | max         |
| `w/s`         | `w_s`     | max         |
| `rkB/s`       | `rkB_s`   | max         |
| `wkB/s`       | `wkB_s`   | max         |
| `r_await`     | `r_await` | max         |
| `w_await`     | `w_await` | max         |
| `aqu-sz`      | `aqu_sz`  | max         |
| `%util`       | `util`    | max         |

---

## New functions in `llm_context.py`

### `_load_iostat_role_map(connection) -> dict[str, str]`

Queries overview for all fields matching `iris disk role *` (excluding `* names` and `*_mount` variants). Returns `{"Database 0": "dm-5", "Primary Journal": "dm-8", ...}`. Returns `{}` if no entries or no overview table.

### `_resample_iostat(iostat_df, device, interval) -> list[dict]`

Filters `iostat_df` to rows where `Device == device`, sets `dt` as index, resamples to `interval` with max aggregation for all 8 columns, renames columns to JSON-safe names, returns list of dicts. Returns `[]` if no rows for that device.

### `_build_iostat_timeseries(connection, interval) -> list[dict]`

1. Calls `_load_iostat_role_map(connection)`
2. If empty, returns `[]`
3. Loads iostat table into DataFrame (with `dt` column, same pattern as `_load_mg_df`)
4. For each role→device pair, calls `_resample_iostat`, appends `{role, device, records}` if records non-empty
5. Returns the list (may be `[]`)

---

## Changes to `build_llm_context()`

```python
iostat_series = _build_iostat_timeseries(connection, resample_interval)

timeseries = {
    "resample_interval": resample_interval,
    "aggregation_notes": "...",
    "records": merged_records,
}
if iostat_series:
    timeseries["iostat"] = iostat_series
```

No changes to `export_llm_context()` or CLI flags.

---

## Aggregation notes string update

Add a sentence noting iostat metrics:

> "iostat metrics (r_s, w_s, rkB_s, wkB_s, r_await, w_await, aqu_sz, util): max per interval, IRIS-role devices only."

---

## Error handling

- Missing `iostat` table: caught by `try/except` in `_build_iostat_timeseries`, returns `[]`
- Device in role map but absent from iostat table: `_resample_iostat` returns `[]`, that role is skipped
- No CPF role data in overview: `_load_iostat_role_map` returns `{}`, section omitted

---

## Tests

Add to `tests/test_llm_context.py`:

- `test_load_iostat_role_map_empty` — no overview rows → returns `{}`
- `test_load_iostat_role_map_filters_names_and_mount` — overview has role + names + mount rows → only role entries returned
- `test_resample_iostat_basic` — DataFrame with two timestamps, one device → correct resampled records with renamed columns
- `test_resample_iostat_unknown_device` — device not in DataFrame → returns `[]`
- `test_build_iostat_timeseries_no_roles` — no role map → returns `[]`
- `test_build_llm_context_iostat_present` — integration: sqlite with overview roles + iostat table → `timeseries.iostat` populated
- `test_build_llm_context_iostat_absent` — sqlite without iostat table → `timeseries` has no `iostat` key
