# Windows IRIS Auto-Disk Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Windows perfmon extraction auto-filters disk columns to CPF-resolved IRIS drive letters by default, mirroring the Linux iostat behaviour shipped in v0.11.0.

**Architecture:** One resolver change (drive-letter fast path in `_path_to_device`) plus one gate extension (`create_sections` auto-filter includes Windows). All storage, precedence, and perfmon column-filter machinery already exists.

**Tech Stack:** Python 3.12, pytest. Reference: `test_samples/windows/OVHWEPRD-ENS001_IRIS_20260529_063000_24hours.html`; golden dump `perf_test/win/golden_before.dump` in the scratch dir.

**Spec:** `docs/superpowers/specs/2026-07-19-windows-auto-disk-design.md`

## Global Constraints

- Branch: `feature/windows-auto-disk` off current `main` (dc66447, v0.11.0). Never commit implementation to main.
- Run tests: `python3 -m pytest tests/ -v` from repo root (173 passing at start).
- Golden gate: Windows run with `--all-disks` must be byte-identical to `perf_test/win/golden_before.dump` (scratch dir `/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test/win/`, symlink `win.html` exists).
- Linux regression gate: a default RHEL run must still auto-filter to exactly dm-18, dm-17, dm-7, dm-8 (scratch dir `.../perf_test/`, symlink `day1.html`).
- No new .py modules; ENGINE_FILES unchanged (cpf_disk_resolver.py already listed).

---

### Task 1: Drive-letter resolution in `cpf_disk_resolver` + gate extension + tests

**Files:**
- Modify: `cpf_disk_resolver.py` (`_path_to_device`)
- Modify: `yaspe.py` (`create_sections` auto-filter gate; the comment above it)
- Modify: `README.md` (one sentence: Windows auto-filtering default + `--all-disks`)
- Test: `tests/test_cpf_disk_resolver.py` (extend), `tests/test_extraction_disk_filter.py` (extend)

**Interfaces:**
- Consumes: existing `_path_to_device(path, mount_map)`, `resolve_iris_disk_roles(sp_dict)`, `get_cpf_auto_disk_list(connection)`, `create_sections(..., all_disks=False)`.
- Produces: `_path_to_device` returns `"X:"` (uppercase, colon) for drive-letter paths regardless of mount_map; `create_sections` auto-filter gate covers `("Linux", "Ubuntu", "Windows")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cpf_disk_resolver.py` (follow its existing import/style conventions — read the file first):

```python
def test_path_to_device_windows_drive_letter():
    from cpf_disk_resolver import _path_to_device
    assert _path_to_device("G:\\DB\\IRISTEMP\\", {}) == "G:"
    assert _path_to_device("c:\\intersystems\\iris\\mgr\\", {}) == "C:"
    assert _path_to_device("J:/JOURNAL/", {}) == "J:"


def test_path_to_device_unc_path_returns_none():
    from cpf_disk_resolver import _path_to_device
    assert _path_to_device("\\\\server\\share\\db\\", {}) is None


def test_resolve_roles_windows_sp_dict():
    from cpf_disk_resolver import resolve_iris_disk_roles
    sp_dict = {
        "cpf_databases": [
            ("IRISSYS", "C:\\InterSystems\\IRIS\\mgr\\"),
            ("IRISTEMP", "G:\\DB\\IRISTEMP\\"),
            ("APPDATA", "N:\\DB\\APP\\"),
            ("MIRRORDB", ":mirror:MIRRORSET:\\somewhere\\"),
        ],
        "current journal": "J:\\JOURNAL\\",
        "alternate journal": "G:\\JOURNAL\\",
        "wijdir": "W:\\WIJ\\",
    }
    roles = resolve_iris_disk_roles(sp_dict)
    assert roles["Database"] == [("C:", ["IRISSYS"]), ("G:", ["IRISTEMP"]), ("N:", ["APPDATA"])]
    assert roles["Primary Journal"] == "J:"
    assert roles["Alternate Journal"] == "G:"
    assert roles["WIJ"] == "W:"
```

Append to `tests/test_extraction_disk_filter.py` (uses its existing `_make_overview` helper):

```python
def test_auto_list_windows_drive_letters():
    conn = _make_overview([
        ("operating system", "Windows"),
        ("iris disk role Database 0", "C:"),
        ("iris disk role Database 1", "G:"),
        ("iris disk role Primary Journal", "J:"),
        ("iris disk role WIJ", "W:"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["C:", "G:", "J:", "W:"]
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 -m pytest tests/test_cpf_disk_resolver.py tests/test_extraction_disk_filter.py -v`
Expected: the three new `_path_to_device`/`resolve_roles` tests FAIL (drive-letter paths currently resolve to None via the empty mount map); `test_auto_list_windows_drive_letters` PASSES already (helper is OS-agnostic — it documents that no yaspe.py storage change is needed).

- [ ] **Step 3: Implement the resolver fast path**

In `cpf_disk_resolver.py`, add at the top of `_path_to_device` (after the `if not path: return None` guard):

```python
    # Windows: CPF paths carry the drive letter directly (e.g. "G:\DB\").
    # Resolve to the normalized letter ("G:"), which matches perfmon
    # PhysicalDisk instance names like "2 G:". UNC paths have no letter and
    # fall through to the mount-map logic (no match on Windows -> None).
    m = re.match(r"^([A-Za-z]):([\\/]|$)", path)
    if m:
        return m.group(1).upper() + ":"
```

- [ ] **Step 4: Extend the `create_sections` gate**

In `yaspe.py`, in `create_sections`, change:

```python
    if not disk_list and not all_disks and operating_system in ("Linux", "Ubuntu"):
```

to:

```python
    if not disk_list and not all_disks and operating_system in ("Linux", "Ubuntu", "Windows"):
```

and update the comment above it to mention Windows perfmon columns (drive letters) alongside Linux iostat devices.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass (177 = 173 + 4 new).

- [ ] **Step 6: Real-sample verification (three behaviours + Linux regression)**

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test/win"
# (a) default: auto-filter engages
rm -f wauto_SystemPerformance.sqlite
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i win.html -a -x -o wauto | grep -i "auto disk"
python3 - <<'EOF'
import sqlite3
conn = sqlite3.connect("wauto_SystemPerformance.sqlite")
cols = [r[1] for r in conn.execute("PRAGMA table_info('perfmon')")]
disk = [c for c in cols if "PhysicalDisk" in c or "LogicalDisk" in c]
inst = sorted({c.split("PhysicalDisk")[1][:4] for c in disk if "PhysicalDisk" in c})
print(len(cols), "cols,", len(disk), "disk cols; instances:", inst)
EOF

# (b) --all-disks: byte-identical to golden
rm -f wall_SystemPerformance.sqlite
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i win.html -a -x -o wall --all-disks
sqlite3 wall_SystemPerformance.sqlite .dump > wall.dump
diff golden_before.dump wall.dump && echo "WIN ALL-DISKS GOLDEN CLEAN"

# (c) explicit -d still wins
rm -f wd_SystemPerformance.sqlite
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i win.html -a -x -o wd -d F: | grep -i "auto disk" || echo "no auto message (correct)"

# (d) Linux regression: default RHEL run still auto-filters to 4 devices
cd ..
rm -f lx_SystemPerformance.sqlite
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i day1.html -a -x -o lx | grep -i "auto disk"
sqlite3 lx_SystemPerformance.sqlite "SELECT COUNT(DISTINCT Device) FROM iostat; SELECT DISTINCT Device FROM iostat;"
```

Expected: (a) auto message lists IRIS drive letters; disk columns reduced from 80 to only IRIS-letter instances + `_Total`; (b) `WIN ALL-DISKS GOLDEN CLEAN`; (c) no auto message; (d) message + exactly dm-18, dm-17, dm-7, dm-8.

- [ ] **Step 7: README update**

Extend the disk-filtering paragraph: on Windows, when a CPF is found, perfmon disk
columns are auto-filtered to IRIS drive letters (databases, journals, WIJ) by
default; `--all-disks` stores every disk column; explicit `-d` letters override.

- [ ] **Step 8: Commit**

```bash
git add cpf_disk_resolver.py yaspe.py README.md tests/test_cpf_disk_resolver.py tests/test_extraction_disk_filter.py
git commit -m "feat: auto-select IRIS disks for Windows perfmon from CPF drive letters

_path_to_device resolves drive-letter paths directly (G:\\DB\\ -> G:),
bypassing the Linux mount map; create_sections auto-filter gate now
includes Windows, feeding letters to the existing perfmon column filter.
Explicit -d and --all-disks precedence unchanged; --all-disks verified
byte-identical to the pre-change Windows golden dump."
```
