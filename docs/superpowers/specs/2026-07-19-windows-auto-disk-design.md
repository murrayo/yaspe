# Windows IRIS auto-disk selection for perfmon extraction

**Date:** 2026-07-19
**Status:** Approved

## Problem

v0.11.0 auto-filters Linux iostat devices to CPF-resolved IRIS disks at extraction
time, but Windows perfmon has no auto-detection — only manual `-d F: J:`. The CPF
data needed is already captured on Windows (`sp_check.system_check` returns
`cpf_databases` with paths like `G:\DB\IRISTEMP\`, `current journal: J:\JOURNAL\`,
`alternate journal: G:\JOURNAL\`, `wijdir: W:\WIJ\`); roles fail to resolve only
because `cpf_disk_resolver._path_to_device` depends on the Linux mount map
(`filesystem df` / `dev mapper` sections), which is empty on Windows.

Verified on `test_samples/windows/OVHWEPRD-ENS001_IRIS_20260529_063000_24hours.html`:
40 databases across C:, G:, N:, …; perfmon disk instances `0 C:` … `8 I:` carry the
same drive letters the CPF paths use.

## Design

1. **`cpf_disk_resolver._path_to_device`**: if the path matches `^[A-Za-z]:[\\/]`
   (or is exactly `X:`), return the normalized drive letter `"X:"` (uppercase, with
   colon) directly, bypassing the mount map. UNC paths (`\\server\share\...`) have
   no drive letter → return None via the existing no-match path. Everything
   downstream is unchanged: `resolve_iris_disk_roles` groups databases by "device"
   (now drive letter), mirror-prefixed paths are already skipped, and yaspe.py's
   existing first-run block stores `iris disk role Database N` / journal / WIJ
   fields in the `overview` table with no changes.
2. **`create_sections` gate** (yaspe.py): extend the extraction-time auto-filter
   condition from `("Linux", "Ubuntu")` to include `"Windows"`. The resulting drive
   letters flow into `extract_sections`' `disk_list`, where the existing perfmon
   column filter accepts letters case-insensitively with/without colon. Precedence
   unchanged: explicit `-d` wins → CPF auto-list → `--all-disks` opts out → no CPF
   info keeps everything.
3. **Untouched**: AIX (excluded by the gate), the Linux charting-time auto-detect
   block, perfmon `_Total`/non-disk counters (always kept by the existing filter),
   Linux iostat behaviour.

## Behaviour change

Default Windows runs store only IRIS-drive perfmon disk columns plus `_Total` and
all non-disk counters. `--all-disks` restores the previous full output
byte-identically. Flows to the Flask app via the normal engine sync; no
ENGINE_FILES change needed (cpf_disk_resolver.py verified already listed).

## Testing

- Unit (tests/test_cpf_disk_resolver.py, extend): drive-letter resolution for each
  role from a Windows-shaped sp_dict; lowercase letter normalized; UNC path
  skipped; `:mirror:` database skipped; databases grouped by letter with names.
- Integration: default run on the real Windows sample logs
  `Auto disk list from CPF (extraction): [...]` and stores only IRIS-letter disk
  columns (+ `_Total`, + non-disk counters); `-d F:` still wins over auto.
- Golden gate: `--all-disks` run must be byte-identical to
  `perf_test/win/golden_before.dump`. Linux golden (default run on RHEL day file)
  must be unaffected — re-run one RHEL default extraction and confirm device set
  is still the 4 CPF devices.
- Full suite green (173 at start).

## Version

`bump2version minor` after merge (new default behaviour on Windows).
