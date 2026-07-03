# Design: Auto-detect IRIS disk roles from CPF file

**Date:** 2026-07-03
**Branch:** feature/llm-context-part-a (to be completed separately or on a new branch)
**Scope:** Single-day iostat charting; Linux only

---

## Goal

When charting iostat for a single-day SystemPerformance file, automatically identify which physical devices back the IRIS databases, Primary Journal, Alternate Journal, and WIJ — without requiring the user to pass `--disk_list`. The resolved roles are stored in the SQLite overview table so they are available for both first-time parse+chart (`-i`) and chart-only (`-e`) modes.

---

## Resolution chain

```
CPF [Databases] path (e.g. /trak/live/tc/db/data/)
  → longest-prefix match in df -m output
  → /dev/mapper/<name>  (e.g. /dev/mapper/vgdb-lvdb)
  → /dev/mapper symlink table: vgdb-lvdb -> ../dm-2
  → iostat device name: dm-2
```

Journal and WIJ follow the same chain using their paths from `sp_dict`.

---

## Changes by file

### `sp_check.system_check()` — parse `[Databases]`

Add a `databases_section` boolean that activates on `[Databases]` and deactivates on the next `[` section header. Collect `NAME=path` lines into `sp_dict["cpf_databases"]` as a list of `(name, path)` tuples. Skip lines starting with `;` (comments). Lines where the path starts with `:mirror:` are remote mirror databases — they have no local directory and are excluded from disk resolution.

No changes to how `[Journal]`, `[config]`, or any other CPF sections are parsed.

### New file: `cpf_disk_resolver.py`

Single public function:

```python
def resolve_iris_disk_roles(sp_dict) -> dict[str, str | None]:
    """
    Returns a dict mapping role name → iostat device name (e.g. "dm-2"),
    or None if the role could not be resolved.
    Roles: "Database", "Primary Journal", "Alternate Journal", "WIJ"
    """
```

**Internal steps:**

1. **Build mount-point map** from `filesystem df *` keys in `sp_dict`. Skip the header row (key `filesystem df 0`). Parse each line by splitting on whitespace; take `parts[0]` as device, `parts[-1]` as mount point. Only include entries where the device starts with `/dev/mapper/` (ignore NFS mounts, tmpfs, loopback, etc.).

2. **Build mapper→dm map** from `dev mapper *` keys. Each line looks like `lrwxrwxrwx ... <name> -> ../dm-N`. Extract the symlink name (the word before `->`) and the dm device (the word after `../`).

3. **`_path_to_device(path, mount_map, mapper_map)`** — find the longest mount point that is a prefix of `path`. Extract the `/dev/mapper/<name>` device, strip the `/dev/mapper/` prefix, look up in `mapper_map`. Return `dm-N` or `None`.

4. **Database role** — filter `cpf_databases` to local paths (not `:mirror:`). Resolve each path. Collect all non-None results, deduplicate. If only one unique device: use it. If multiple: use the most frequent (covers installations where app databases share one LV and system databases are on another). Log a note if multiple devices are found.

5. **Journal/WIJ roles** — resolve `sp_dict.get("current journal")`, `sp_dict.get("alternate journal")`, `sp_dict.get("wijdir")`. WIJ: if `wijdir` is empty string or not present, return `None` for WIJ (it's in the installation directory, not a separate device).

6. Returns `{"Database": "dm-2", "Primary Journal": "dm-6", "Alternate Journal": "dm-8", "WIJ": None}`.

### `sp_check.build_log()` — display resolved roles

After the existing Storage block (current journal, alternate journal, wijdir), add an "IRIS disk roles (auto-detected)" sub-section. For each role, show the device and the mount point it was resolved through. If a role is `None`, show a short explanation (e.g. "WIJ: not configured (installation directory)").

Example output:
```
IRIS disk roles (auto-detected):
  Database             : dm-2  (/trak/live/tc)
  Primary Journal      : dm-6  (/trak/live/tc/prijrn)
  Alternate Journal    : dm-8  (/trak/live/tc/altjrn)
  WIJ                  : not configured (installation directory)
```

### `yaspe.py` — wire up resolver and auto disk list

**At parse time** (in `mainline()`, after `sp_check.system_check()` returns and before `create_overview()`):

```python
import cpf_disk_resolver
iris_roles = cpf_disk_resolver.resolve_iris_disk_roles(sp_dict)
sp_dict["iris_disk_roles"] = json.dumps(iris_roles)
for role, device in iris_roles.items():
    if device:
        sp_dict[f"iris disk role {role}"] = device
```

The `create_overview()` call then persists all these keys to the `overview` table automatically.

**At chart time** (in `mainline()`, before calling `chart_iostat()`):

If `disk_list` is `None` or empty and `operating_system` is `"Linux"` or `"Ubuntu"`:

```python
role_order = ["Database", "Primary Journal", "Alternate Journal", "WIJ"]
auto_devices = []
for role in role_order:
    row = execute_single_read_query(
        connection, f"SELECT * FROM overview WHERE field = 'iris disk role {role}';"
    )
    if row and row[2]:
        auto_devices.append(row[2])
# deduplicate preserving order
seen = set()
disk_list = [d for d in auto_devices if not (d in seen or seen.add(d))]
```

Explicit `--disk_list` always takes precedence — this block only runs when `disk_list` is falsy.

### `sync_engine.sh` (Flask repo)

Add `cpf_disk_resolver.py` to `ENGINE_FILES`. It is imported by `yaspe.py` and must be synced.

---

## Edge cases

| Situation | Behaviour |
|-----------|-----------|
| Database path not under any df mount point | Role resolves to `None`; omitted from auto disk list |
| Device not in `/dev/mapper` (e.g. bare `/dev/sdb`) | `_path_to_device` returns `None`; role omitted |
| All databases on the same device as the journal | Both roles still present in dict; disk list deduplicates |
| `wijdir` is empty string | WIJ role is `None`; overview.txt says "not configured" |
| `:mirror:` database entries | Skipped entirely (no local path to resolve) |
| Multiple devices for databases | Most-frequent device wins; note logged to stdout |
| `-e` mode (no HTML parsed) | Roles already in overview table from prior parse; auto disk list reads from DB |
| Windows / AIX OS | Auto-detection skipped entirely (only fires for Linux/Ubuntu) |
| No `[Databases]` section in CPF | `cpf_databases` is empty list; Database role is `None` |

---

## Files changed

| File | Change |
|------|--------|
| `sp_check.py` | Parse `[Databases]` section; display resolved roles in `build_log()` |
| `cpf_disk_resolver.py` | **New** — resolution logic |
| `yaspe.py` | Import resolver; store roles in `sp_dict`; auto-populate `disk_list` |
| `yaspe_flask_v1/sync_engine.sh` | Add `cpf_disk_resolver.py` to `ENGINE_FILES` |

No changes to `extract_sections.py`, `chart_output.py`, `chart_templates.py`, or `system_review.py`.
