# CPF Auto Disk Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically identify the iostat device names for IRIS database, journal, and WIJ roles from the CPF `[Databases]` section and Linux filesystem info, and use them to auto-populate the iostat disk list when no `--disk_list` is supplied.

**Architecture:** A new `cpf_disk_resolver.py` module takes the `sp_dict` (already containing `dev mapper *`, `filesystem df *`, and journal/WIJ path keys) and resolves each IRIS role to an iostat device name. `sp_check.system_check()` is extended to parse the CPF `[Databases]` section. `yaspe.py` calls the resolver after `system_check()`, stores roles in `sp_dict` (persisted to the `overview` SQLite table), and auto-builds a `disk_list` at chart time when none was explicitly supplied.

**Tech Stack:** Python 3, pytest, sqlite3, re (stdlib only — no new dependencies)

## Global Constraints

- Linux/Ubuntu only — auto-detection is skipped for Windows and AIX.
- Explicit `--disk_list` CLI argument always takes precedence over auto-detected roles.
- Device names stored in the `overview` table use keys of the form `iris disk role <Role>` (e.g. `iris disk role Database`).
- `:mirror:` database entries in `[Databases]` have no local path and must be skipped.
- Empty `wijdir` means WIJ is in the installation directory — resolve to `None`, not an error.
- `cpf_disk_resolver.py` must be added to `ENGINE_FILES` in `yaspe_flask_v1/sync_engine.sh`.
- Tests live in `tests/test_cpf_disk_resolver.py` and follow the project pattern: `sys.path.insert(0, ...)` at the top, no pytest fixtures file needed.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `cpf_disk_resolver.py` | **Create** | All resolution logic: build maps, resolve paths, return role dict |
| `sp_check.py` | **Modify** | Parse `[Databases]` section into `sp_dict["cpf_databases"]`; display resolved roles in `build_log()` |
| `yaspe.py` | **Modify** | Import resolver; call after `system_check()`; auto-build `disk_list` before `chart_iostat()` |
| `yaspe_flask_v1/sync_engine.sh` | **Modify** | Add `cpf_disk_resolver.py` to `ENGINE_FILES` |
| `tests/test_cpf_disk_resolver.py` | **Create** | Unit tests for all resolver logic |

---

## Task 1: Create `cpf_disk_resolver.py` with core resolution logic

**Files:**
- Create: `cpf_disk_resolver.py`
- Create: `tests/test_cpf_disk_resolver.py`

**Interfaces:**
- Produces: `resolve_iris_disk_roles(sp_dict: dict) -> dict[str, str | None]`
  - Keys: `"Database"`, `"Primary Journal"`, `"Alternate Journal"`, `"WIJ"`
  - Values: iostat device name string (e.g. `"dm-2"`, `"sdb"`) or `None`
- Produces: `_build_mount_map(sp_dict: dict) -> dict[str, str]`
  - Returns `{mount_point: device_name}` where device_name is the bare iostat name
- Produces: `_build_mapper_map(sp_dict: dict) -> dict[str, str]`
  - Returns `{mapper_name: dm_device}` e.g. `{"vgdb-lvdb": "dm-2"}`
- Produces: `_path_to_device(path: str, mount_map: dict[str, str]) -> str | None`
  - Longest-prefix mount match → bare device name or None

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cpf_disk_resolver.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cpf_disk_resolver as cdr


# ── _build_mapper_map ──────────────────────────────────────────────────────────

def _mapper_sp_dict():
    return {
        "dev mapper 0": "lrwxrwxrwx 1 root root       7 May  8 00:44 vgapp-lvapp -> ../dm-3",
        "dev mapper 1": "lrwxrwxrwx 1 root root       7 May  8 00:44 vgdb-lvdb -> ../dm-2",
        "dev mapper 2": "lrwxrwxrwx 1 root root       7 May  8 00:44 vghs-lvprijrn -> ../dm-6",
    }


def test_build_mapper_map_extracts_entries():
    result = cdr._build_mapper_map(_mapper_sp_dict())
    assert result == {"vgapp-lvapp": "dm-3", "vgdb-lvdb": "dm-2", "vghs-lvprijrn": "dm-6"}


def test_build_mapper_map_empty():
    assert cdr._build_mapper_map({}) == {}


# ── _build_mount_map ───────────────────────────────────────────────────────────

def _df_sp_dict():
    return {
        "filesystem df 0": "Filesystem                       1M-blocks    Used Available Use% Mounted on",
        "filesystem df 1": "devtmpfs                             64167       0     64167   0% /dev",
        "filesystem df 2": "tmpfs                                64185       0     64185   0% /dev/shm",
        "filesystem df 3": "/dev/mapper/vgdb-lvdb              6289406 4287252   2002155  69% /trak/live/tc",
        "filesystem df 4": "/dev/mapper/vghs-lvprijrn           921542   12384    909159   2% /trak/live/tc/prijrn",
        "filesystem df 5": "/dev/mapper/vghs-lvaltjrn           358318      33    358285   1% /trak/live/tc/altjrn",
        "filesystem df 6": "/dev/sdb1                             1014     269       746  27% /boot",
        "filesystem df 7": "172.16.201.33:/trak/live/lab/app    204743  159923     44820  79% /trak/live/lab/app",
    }


def test_build_mount_map_mapper_devices():
    result = cdr._build_mount_map(_df_sp_dict(), _mapper_sp_dict())
    assert result["/trak/live/tc"] == "dm-2"
    assert result["/trak/live/tc/prijrn"] == "dm-6"


def test_build_mount_map_bare_device():
    result = cdr._build_mount_map(_df_sp_dict(), _mapper_sp_dict())
    assert result["/boot"] == "sdb"


def test_build_mount_map_excludes_nfs_and_tmpfs():
    result = cdr._build_mount_map(_df_sp_dict(), _mapper_sp_dict())
    assert "/trak/live/lab/app" not in result
    assert "/dev" not in result
    assert "/dev/shm" not in result


# ── _path_to_device ────────────────────────────────────────────────────────────

def test_path_to_device_exact_mount():
    mount_map = {"/trak/live/tc": "dm-2", "/trak/live/tc/prijrn": "dm-6"}
    assert cdr._path_to_device("/trak/live/tc/db/data/", mount_map) == "dm-2"


def test_path_to_device_longer_mount_wins():
    mount_map = {"/trak/live/tc": "dm-2", "/trak/live/tc/prijrn": "dm-6"}
    assert cdr._path_to_device("/trak/live/tc/prijrn/", mount_map) == "dm-6"


def test_path_to_device_no_match():
    mount_map = {"/trak/live/tc": "dm-2"}
    assert cdr._path_to_device("/some/other/path/", mount_map) is None


def test_path_to_device_none_path():
    assert cdr._path_to_device(None, {"/trak": "dm-2"}) is None


def test_path_to_device_empty_path():
    assert cdr._path_to_device("", {"/trak": "dm-2"}) is None


# ── resolve_iris_disk_roles ────────────────────────────────────────────────────

def _full_sp_dict():
    d = {}
    d.update(_mapper_sp_dict())
    d.update(_df_sp_dict())
    d["cpf_databases"] = [
        ("TRAK-DATA", "/trak/live/tc/db/data/,,1"),
        ("TRAK-DOCS", "/trak/live/tc/db/docs/,,1"),
        ("TRAK-LABDATA", ":mirror:PRDLAB:TRAK-LABDATA,PRDLAB"),
    ]
    d["current journal"] = "/trak/live/tc/prijrn/"
    d["alternate journal"] = "/trak/live/tc/altjrn/"
    d["wijdir"] = ""
    return d


def test_resolve_database_role():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Database"] == "dm-2"


def test_resolve_primary_journal():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Primary Journal"] == "dm-6"


def test_resolve_alternate_journal():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Alternate Journal"] == "dm-8"


def test_resolve_wij_empty_is_none():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["WIJ"] is None


def test_resolve_mirror_databases_skipped():
    # Only mirror databases → Database role is None
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = [("TRAK-LABDATA", ":mirror:PRDLAB:TRAK-LABDATA,PRDLAB")]
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] is None


def test_resolve_no_cpf_databases_key():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] is None


def test_resolve_wij_configured():
    sp = _full_sp_dict()
    sp["wijdir"] = "/trak/live/tc/wij/"
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["WIJ"] == "dm-2"


def test_resolve_bare_sdb_device():
    # Journal on a plain partition device
    sp = _full_sp_dict()
    sp["current journal"] = "/boot/"
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Primary Journal"] == "sdb"
```

- [ ] **Step 2: Run tests — expect import error**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -m pytest tests/test_cpf_disk_resolver.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'cpf_disk_resolver'`

- [ ] **Step 3: Implement `cpf_disk_resolver.py`**

```python
# cpf_disk_resolver.py
import re
from collections import Counter


def _build_mapper_map(sp_dict):
    """Parse 'dev mapper N' entries → {mapper_name: dm_device}."""
    mapper_map = {}
    for key, value in sp_dict.items():
        if not key.startswith("dev mapper "):
            continue
        # e.g. "lrwxrwxrwx 1 root root  7 May  8 vgdb-lvdb -> ../dm-2"
        m = re.search(r"(\S+)\s+->\s+\.\./(\S+)", value)
        if m:
            mapper_map[m.group(1)] = m.group(2)
    return mapper_map


def _build_mount_map(sp_dict, mapper_map):
    """
    Parse 'filesystem df N' entries → {mount_point: iostat_device_name}.

    Includes /dev/mapper/* (resolved via mapper_map → dm-N) and bare
    /dev/<name>[digit] (stripped to base device name e.g. sdb).
    Excludes NFS, tmpfs, devtmpfs, and other non-/dev/ entries.
    Skips the header row (filesystem df 0).
    """
    mount_map = {}
    for key, value in sp_dict.items():
        if not key.startswith("filesystem df "):
            continue
        if key == "filesystem df 0":
            continue
        parts = value.split()
        if len(parts) < 2:
            continue
        device_field = parts[0]
        mount_point = parts[-1]
        if not device_field.startswith("/dev/"):
            continue
        if device_field.startswith("/dev/mapper/"):
            mapper_name = device_field[len("/dev/mapper/"):]
            dm_device = mapper_map.get(mapper_name)
            if dm_device:
                mount_map[mount_point] = dm_device
        else:
            # e.g. /dev/sdb1 → sdb, /dev/sda → sda
            bare = device_field[len("/dev/"):]
            bare = bare.rstrip("0123456789")
            if bare:
                mount_map[mount_point] = bare
    return mount_map


def _path_to_device(path, mount_map):
    """
    Return the iostat device name for the given directory path by
    finding the longest matching mount point. Returns None if no match.
    """
    if not path:
        return None
    best_mount = None
    best_len = -1
    for mount_point in mount_map:
        if path.startswith(mount_point) and len(mount_point) > best_len:
            best_mount = mount_point
            best_len = len(mount_point)
    if best_mount is None:
        return None
    return mount_map[best_mount]


def resolve_iris_disk_roles(sp_dict):
    """
    Resolve IRIS storage roles to iostat device names.

    Returns dict with keys "Database", "Primary Journal",
    "Alternate Journal", "WIJ". Values are iostat device name strings
    (e.g. "dm-2", "sdb") or None if the role could not be resolved.
    """
    mapper_map = _build_mapper_map(sp_dict)
    mount_map = _build_mount_map(sp_dict, mapper_map)

    roles = {
        "Database": None,
        "Primary Journal": None,
        "Alternate Journal": None,
        "WIJ": None,
    }

    # Database: collect local (non-mirror) database paths
    cpf_databases = sp_dict.get("cpf_databases", [])
    local_devices = []
    for _name, path in cpf_databases:
        # Strip optional ",,N" suffix from path
        clean_path = path.split(",,")[0]
        if clean_path.startswith(":mirror:"):
            continue
        device = _path_to_device(clean_path, mount_map)
        if device:
            local_devices.append(device)

    if local_devices:
        # Use most-frequent device; deduplicated list preserves one entry
        most_common = Counter(local_devices).most_common(1)[0][0]
        roles["Database"] = most_common
        if len(set(local_devices)) > 1:
            print(f"  Note: databases span multiple devices {set(local_devices)}, using {most_common}")

    # Journal roles
    roles["Primary Journal"] = _path_to_device(
        sp_dict.get("current journal"), mount_map
    )
    roles["Alternate Journal"] = _path_to_device(
        sp_dict.get("alternate journal"), mount_map
    )

    # WIJ: empty string means installation directory — skip
    wijdir = sp_dict.get("wijdir", "")
    if wijdir:
        roles["WIJ"] = _path_to_device(wijdir, mount_map)

    return roles
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -m pytest tests/test_cpf_disk_resolver.py -v
```

Expected: all 18 tests PASS.

- [ ] **Step 5: Add `dm-8` mapping to the test fixture so altjrn resolves**

The `_full_sp_dict()` fixture has `vghs-lvaltjrn` in df but not in `_mapper_sp_dict()`. Add it:

In `tests/test_cpf_disk_resolver.py`, update `_mapper_sp_dict()`:

```python
def _mapper_sp_dict():
    return {
        "dev mapper 0": "lrwxrwxrwx 1 root root       7 May  8 00:44 vgapp-lvapp -> ../dm-3",
        "dev mapper 1": "lrwxrwxrwx 1 root root       7 May  8 00:44 vgdb-lvdb -> ../dm-2",
        "dev mapper 2": "lrwxrwxrwx 1 root root       7 May  8 00:44 vghs-lvprijrn -> ../dm-6",
        "dev mapper 3": "lrwxrwxrwx 1 root root       7 May  8 00:44 vghs-lvaltjrn -> ../dm-8",
    }
```

And update `_df_sp_dict()` to include the altjrn entry (it is already there as `filesystem df 5`). Re-run:

```bash
python -m pytest tests/test_cpf_disk_resolver.py -v
```

Expected: all tests PASS including `test_resolve_alternate_journal`.

- [ ] **Step 6: Commit**

```bash
git add cpf_disk_resolver.py tests/test_cpf_disk_resolver.py
git commit -m "feat: add cpf_disk_resolver module with role resolution logic"
```

---

## Task 2: Parse CPF `[Databases]` section in `sp_check.system_check()`

**Files:**
- Modify: `sp_check.py` (lines ~54–84 variable init block, ~179–218 CPF section block)

**Interfaces:**
- Consumes: nothing new from other tasks
- Produces: `sp_dict["cpf_databases"]` — list of `(name, path_raw)` tuples, e.g. `[("TRAK-DATA", "/trak/live/tc/db/data/,,1"), ("TRAK-LABDATA", ":mirror:PRDLAB:TRAK-LABDATA,PRDLAB")]`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cpf_disk_resolver.py` (or create a small separate test — add to existing file for simplicity):

```python
# Add at the bottom of tests/test_cpf_disk_resolver.py

import tempfile
import sp_check


def _make_html(databases_block, journal_current="/jrn/pri/", journal_alt="/jrn/alt/", wijdir=""):
    """Minimal HTML that looks like a SystemPerformance file to sp_check."""
    return f"""Customer: TestSite
Version String: IRIS for UNIX (RHEL 8 for x86-64) 2024.1
Profile run 2026-06-15
up >TESTIRIS on machine testhost
[ConfigFile]
[Databases]
{databases_block}
[Namespaces]
[Journal]
AlternateDirectory={journal_alt}
CurrentDirectory={journal_current}
[config]
wijdir={wijdir}
!-- beg_mgstat --
"""


def test_sp_check_parses_cpf_databases():
    html = _make_html(
        "IRISSYS=/trak/live/tc/hs/trak/mgr/\n"
        "TRAK-DATA=/trak/live/tc/db/data/,,1\n"
        "TRAK-LABDATA=:mirror:PRDLAB:TRAK-LABDATA,PRDLAB\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        sp_dict = sp_check.system_check(path)
        assert "cpf_databases" in sp_dict
        names = [name for name, _ in sp_dict["cpf_databases"]]
        assert "IRISSYS" in names
        assert "TRAK-DATA" in names
        assert "TRAK-LABDATA" in names
    finally:
        os.unlink(path)


def test_sp_check_cpf_databases_empty_when_no_section():
    html = _make_html("")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        sp_dict = sp_check.system_check(path)
        assert sp_dict.get("cpf_databases", []) == []
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests — expect failures**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_sp_check_parses_cpf_databases tests/test_cpf_disk_resolver.py::test_sp_check_cpf_databases_empty_when_no_section -v
```

Expected: FAIL — `cpf_databases` key not in sp_dict.

- [ ] **Step 3: Add `[Databases]` parsing to `sp_check.system_check()`**

In `sp_check.py`, in the variable initialisation block near the top of `system_check()` (around line 54), add:

```python
    databases_section = False
    cpf_databases = []
```

In the main file-reading loop, after the existing CPF section block (around line 218, after the last `if line.startswith("bbsiz="):` check), add a new block to track `[Databases]` sub-section. The CPF section is already entered at `[ConfigFile]`. Add within the `if cpf_section:` block:

```python
                if line.startswith("[Databases]"):
                    databases_section = True
                elif line.startswith("[") and databases_section:
                    databases_section = False
                elif databases_section and "=" in line and not line.startswith(";"):
                    name, _, path_raw = line.strip().partition("=")
                    if name and path_raw:
                        cpf_databases.append((name, path_raw))
```

At the end of `system_check()`, before `return sp_dict`, store the result:

```python
    sp_dict["cpf_databases"] = cpf_databases
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_sp_check_parses_cpf_databases tests/test_cpf_disk_resolver.py::test_sp_check_cpf_databases_empty_when_no_section -v
```

Expected: both PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add sp_check.py tests/test_cpf_disk_resolver.py
git commit -m "feat: parse CPF [Databases] section into sp_dict cpf_databases"
```

---

## Task 3: Display resolved roles in `sp_check.build_log()`

**Files:**
- Modify: `sp_check.py` — `build_log()` function, Storage block (around line 1443–1449)

**Interfaces:**
- Consumes: `sp_dict["iris disk role Database"]`, `sp_dict["iris disk role Primary Journal"]`, `sp_dict["iris disk role Alternate Journal"]`, `sp_dict["iris disk role WIJ"]` (set by `yaspe.py` Task 4, but `build_log()` reads them gracefully if absent)
- Consumes: `sp_dict.get("iris_disk_role_mount Database")` etc. for the mount point annotation (set by Task 4)

**Note:** `build_log()` is called after `yaspe.py` has already run the resolver and added the role keys to `sp_dict`, so they will be present when `build_log()` runs.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cpf_disk_resolver.py`:

```python
def test_build_log_shows_disk_roles():
    html = _make_html(
        "TRAK-DATA=/trak/live/tc/db/data/,,1\n",
        journal_current="/trak/live/tc/prijrn/",
        journal_alt="/trak/live/tc/altjrn/",
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        sp_dict = sp_check.system_check(path)
        # Simulate what yaspe.py will add after calling the resolver
        sp_dict["iris disk role Database"] = "dm-2"
        sp_dict["iris disk role Primary Journal"] = "dm-6"
        sp_dict["iris disk role Alternate Journal"] = "dm-8"
        sp_dict["iris_disk_role_mount Database"] = "/trak/live/tc"
        sp_dict["iris_disk_role_mount Primary Journal"] = "/trak/live/tc/prijrn"
        sp_dict["iris_disk_role_mount Alternate Journal"] = "/trak/live/tc/altjrn"
        log, _ = sp_check.build_log(sp_dict)
        assert "IRIS disk roles" in log
        assert "Database" in log and "dm-2" in log
        assert "Primary Journal" in log and "dm-6" in log
        assert "Alternate Journal" in log and "dm-8" in log
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run the test — expect failure**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_build_log_shows_disk_roles -v
```

Expected: FAIL — "IRIS disk roles" not in log.

- [ ] **Step 3: Add the disk roles display block to `build_log()`**

In `sp_check.py`, find the Storage block in `build_log()` (around line 1443). After the existing `wijdir` line:

```python
    if "wijdir" in sp_dict:
        log += f"WIJ directory          : {sp_dict['wijdir']}\n"
```

Add:

```python
    role_order = ["Database", "Primary Journal", "Alternate Journal", "WIJ"]
    role_lines = []
    for role in role_order:
        key = f"iris disk role {role}"
        if key in sp_dict:
            device = sp_dict[key]
            mount = sp_dict.get(f"iris_disk_role_mount {role}", "")
            mount_str = f"  ({mount})" if mount else ""
            role_lines.append(f"  {role:<22}: {device}{mount_str}")
        else:
            if role == "WIJ":
                role_lines.append(f"  {role:<22}: not configured (installation directory)")
    if any(f"iris disk role {r}" in sp_dict for r in role_order):
        log += "\nIRIS disk roles (auto-detected):\n"
        log += "\n".join(role_lines) + "\n"
```

- [ ] **Step 4: Run the test — expect pass**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_build_log_shows_disk_roles -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add sp_check.py tests/test_cpf_disk_resolver.py
git commit -m "feat: display IRIS disk roles in overview.txt storage section"
```

---

## Task 4: Wire resolver into `yaspe.py` — store roles and auto-build disk list

**Files:**
- Modify: `yaspe.py` — imports block (top of file), mainline parse section (~line 2945), mainline chart section (~line 3071)

**Interfaces:**
- Consumes: `cpf_disk_resolver.resolve_iris_disk_roles(sp_dict)` from Task 1
- Consumes: `execute_single_read_query(connection, query)` — returns a row tuple where index `[2]` is the value column
- Produces: `sp_dict["iris disk role Database"]` etc. (persisted to `overview` table via existing `create_overview()`)
- Produces: `sp_dict["iris_disk_role_mount Database"]` etc. (mount point annotation for `build_log()`)
- Produces: auto-populated `disk_list` passed to `chart_iostat()` when no explicit list given

- [ ] **Step 1: Add import to `yaspe.py`**

At the top of `yaspe.py`, after the existing `import sp_check` line (line 7), add:

```python
import cpf_disk_resolver
```

- [ ] **Step 2: Call resolver after `system_check()` and before `create_overview()`**

In `mainline()`, find the block starting at line ~2945:

```python
                sp_dict = sp_check.system_check(input_file)
                if system_out:
                    output_log, yaspe_yaml = sp_check.build_log(sp_dict)
```

Insert between `system_check()` and `if system_out:`:

```python
                sp_dict = sp_check.system_check(input_file)

                # Resolve IRIS storage roles from CPF + filesystem info
                iris_roles = cpf_disk_resolver.resolve_iris_disk_roles(sp_dict)
                # Build a helper map of mount points for build_log display
                mapper_map = cpf_disk_resolver._build_mapper_map(sp_dict)
                mount_map = cpf_disk_resolver._build_mount_map(sp_dict, mapper_map)
                # Invert mount_map to get device → mount for annotation
                device_to_mount = {v: k for k, v in mount_map.items()}
                for role, device in iris_roles.items():
                    if device:
                        sp_dict[f"iris disk role {role}"] = device
                        sp_dict[f"iris_disk_role_mount {role}"] = device_to_mount.get(device, "")

                if system_out:
                    output_log, yaspe_yaml = sp_check.build_log(sp_dict)
```

The `create_overview(connection, sp_dict)` call that follows will automatically persist all the new `iris disk role *` keys to the `overview` table.

- [ ] **Step 3: Auto-build disk list at chart time**

In `mainline()`, find the `is_linux` block (around line 3054):

```python
            is_linux = operating_system in ("Linux", "Ubuntu")
```

After this line, add:

```python
            # Auto-detect disk list from CPF roles if none was supplied
            if is_linux and not disk_list:
                role_order = ["Database", "Primary Journal", "Alternate Journal", "WIJ"]
                auto_devices = []
                for role in role_order:
                    row = execute_single_read_query(
                        connection,
                        f"SELECT * FROM overview WHERE field = 'iris disk role {role}';"
                    )
                    if row and row[2]:
                        auto_devices.append(row[2])
                # Deduplicate preserving order
                seen = set()
                resolved = [d for d in auto_devices if not (d in seen or seen.add(d))]
                if resolved:
                    disk_list = resolved
                    print(f"  Auto disk list from CPF: {disk_list}")
```

- [ ] **Step 4: Smoke-test with the sample database**

Run against the test sample in chart-only mode (the existing SQLite has no `iris disk role *` keys yet, so auto-detection won't fire — but it should not crash):

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python yaspe.py -e test_samples/MEUH/yaspe_SystemPerformance.sqlite -p -x 2>&1 | tail -5
```

Expected: runs without error, generates charts (same as before — no auto disk list since the existing DB has no role keys).

- [ ] **Step 5: Full parse+chart test to exercise the new path**

```bash
python yaspe.py -i test_samples/MEUH/UHSMSTRAK-B_PRDTRAKB_20260615_000105_24hours_5.html -a -s -x -o /tmp/yaspe_test_cpf 2>&1 | grep -E "Auto disk|iris disk|Error|Traceback"
```

Expected output includes:
```
  Auto disk list from CPF: ['dm-2', 'dm-6', 'dm-8']
```
No errors or tracebacks.

- [ ] **Step 6: Verify overview.txt contains the disk roles section**

```bash
grep -A 6 "IRIS disk roles" /tmp/yaspe_test_cpf_overview.txt
```

Expected:
```
IRIS disk roles (auto-detected):
  Database              : dm-2  (/trak/live/tc)
  Primary Journal       : dm-6  (/trak/live/tc/prijrn)
  Alternate Journal     : dm-8  (/trak/live/tc/altjrn)
  WIJ                   : not configured (installation directory)
```

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add yaspe.py
git commit -m "feat: wire CPF disk resolver into yaspe.py for auto disk list"
```

---

## Task 5: Update `sync_engine.sh` in the Flask repo

**Files:**
- Modify: `/Users/moldfiel/projects/all_live_projects/yaspe_flask_v1/sync_engine.sh`

**Interfaces:** none — standalone housekeeping step.

- [ ] **Step 1: Add `cpf_disk_resolver.py` to ENGINE_FILES**

In `yaspe_flask_v1/sync_engine.sh`, find the `ENGINE_FILES=(` block and add the new module after `sp_check.py`:

```bash
ENGINE_FILES=(
    yaspe.py
    extract_sections.py
    extract_mgstat.py
    sp_check.py
    cpf_disk_resolver.py
    split_large_file.py
    system_review.py
    chart_output.py
    chart_templates.py
    yaspe_utilities.py
    pretty_performance.py
    yaspe_compare_overlay.py
    yaspe_combined_overlay.py
)
```

- [ ] **Step 2: Verify the sync script finds the new file**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe_flask_v1
bash sync_engine.sh --dry-run 2>&1 | grep cpf_disk_resolver
```

If `--dry-run` is not supported, just confirm the file exists in the CLI repo:

```bash
ls /Users/moldfiel/projects/all_live_projects/yaspe/cpf_disk_resolver.py
```

Expected: file exists.

- [ ] **Step 3: Commit in the Flask repo**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe_flask_v1
git add sync_engine.sh
git commit -m "feat: add cpf_disk_resolver.py to ENGINE_FILES sync list"
```

- [ ] **Step 4: Return to the main repo and do a final full test run**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit plan and memory update in main repo**

```bash
git add docs/superpowers/plans/2026-07-03-cpf-auto-disk-detection.md
git commit -m "docs: add implementation plan for CPF auto disk detection"
```
