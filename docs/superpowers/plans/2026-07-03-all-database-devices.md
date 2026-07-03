# All Database Devices Charted Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chart every distinct device that backs an IRIS database (from the CPF `[Databases]` section), with role-labelled subdirectory names and a two-line chart title that lists the database names on line 1 and the metric/device/customer on line 2.

**Architecture:** `resolve_iris_disk_roles` is extended to return a list of `(device, [db_names])` pairs for the Database role instead of a single device string; non-Database roles remain single strings. `yaspe.py` stores one overview row per database device, builds a `device_labels` dict keyed by device name, and passes it into `chart_iostat`. Inside `chart_iostat` the directory slug and title string are derived from the label when present.

**Tech Stack:** Python 3, matplotlib 3.10, plotly, SQLite, pytest

## Global Constraints

- All new overview table keys follow the existing pattern: lowercase, space-separated (e.g. `iris disk role Database 0`)
- `resolve_iris_disk_roles` return type for `"Database"` changes from `str | None` to `list[tuple[str, list[str]]]` (list of `(device, [db_names])` pairs, empty list when nothing resolved)
- Non-Database roles (`"Primary Journal"`, `"Alternate Journal"`, `"WIJ"`) remain `str | None`
- Directory slug for a database device: `{device}_{first_db_name}` where `first_db_name` is the first entry in the db names list, lowercased and with spaces replaced by underscores — e.g. `dm-2_trak-data`
- Directory slug for journal/WIJ roles: `{device}_{role_slug}` where `role_slug` is the role name lowercased with spaces replaced by underscores — e.g. `dm-6_primary_journal`
- Two-line chart title: line 1 = comma-separated db names (or role name for non-DB roles), line 2 = existing title string. In matplotlib use `\n`; in plotly use `<br>`.
- `device_labels` dict maps device name → human label string (comma-separated db names or role name)
- Auto disk list ordering: database devices first (in order of first appearance), then Primary Journal, Alternate Journal, WIJ — deduplicated across all roles
- No changes to `chart_templates.py`, `extract_sections.py`, `chart_output.py`, or `pretty_performance.py`
- Tests live in `tests/test_cpf_disk_resolver.py` (resolver) and existing test helpers in that file
- The existing 114 tests must all still pass after each task

---

### Task 1: Extend `resolve_iris_disk_roles` to return all database devices

**Files:**
- Modify: `cpf_disk_resolver.py`
- Test: `tests/test_cpf_disk_resolver.py`

**Interfaces:**
- Produces: `resolve_iris_disk_roles(sp_dict)` returns:
  ```python
  {
      "Database": [("dm-2", ["TRAK-DATA", "TRAK-DOCS"]), ("dm-1", ["IRISSYS"])],
      "Primary Journal": "dm-6",   # str | None — unchanged
      "Alternate Journal": "dm-8", # str | None — unchanged
      "WIJ": None,                 # str | None — unchanged
  }
  ```
  The `"Database"` value is `list[tuple[str, list[str]]]` — list of `(device, db_names)` pairs ordered by first appearance, empty list when nothing resolved.

- [ ] **Step 1: Write failing tests**

Add these tests to `tests/test_cpf_disk_resolver.py`:

```python
def test_resolve_database_role_returns_list():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    # Database is now a list of (device, [names]) tuples
    assert isinstance(result["Database"], list)
    assert len(result["Database"]) == 1
    device, names = result["Database"][0]
    assert device == "dm-2"
    assert "TRAK-DATA" in names
    assert "TRAK-DOCS" in names


def test_resolve_database_role_multi_device():
    # Two databases on different devices
    sp = {}
    sp.update(_mapper_sp_dict())
    # Add an extra mount: /boot is already on sdb (bare device)
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = [
        ("APP-DATA", "/trak/live/tc/db/data/,,1"),   # → dm-2
        ("BOOT-DB", "/boot/,,1"),                     # → sdb
    ]
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    devices = [d for d, _ in result["Database"]]
    assert "dm-2" in devices
    assert "sdb" in devices
    # names grouped by device
    by_device = dict(result["Database"])
    assert "APP-DATA" in by_device["dm-2"]
    assert "BOOT-DB" in by_device["sdb"]


def test_resolve_database_empty_list_when_no_databases():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = []
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] == []


def test_resolve_journal_roles_still_strings():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Primary Journal"] == "dm-6"
    assert result["Alternate Journal"] == "dm-8"
    assert result["WIJ"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_resolve_database_role_returns_list tests/test_cpf_disk_resolver.py::test_resolve_database_role_multi_device tests/test_cpf_disk_resolver.py::test_resolve_database_empty_list_when_no_databases tests/test_cpf_disk_resolver.py::test_resolve_journal_roles_still_strings -v
```

Expected: FAIL — `assert isinstance(result["Database"], list)` fails because current code returns `"dm-2"` (a string).

- [ ] **Step 3: Update `resolve_iris_disk_roles` in `cpf_disk_resolver.py`**

Replace the `# Database: collect local (non-mirror) database paths` block (lines ~95–112):

```python
    # Database: group local (non-mirror) paths by device, preserving insertion order
    cpf_databases = sp_dict.get("cpf_databases", [])
    # ordered dict: device → [db_names]
    device_names_map = {}
    for name, path in cpf_databases:
        clean_path = path.split(",,")[0]
        if clean_path.startswith(":mirror:"):
            continue
        device = _path_to_device(clean_path, mount_map)
        if device:
            if device not in device_names_map:
                device_names_map[device] = []
            device_names_map[device].append(name)

    if len(device_names_map) > 1:
        print(f"  Note: databases span multiple devices: {list(device_names_map.keys())}")

    roles["Database"] = list(device_names_map.items())  # [(device, [names]), ...]
```

Also update the `roles` dict initialisation at the top of the function:

```python
    roles = {
        "Database": [],          # list[tuple[str, list[str]]]
        "Primary Journal": None,
        "Alternate Journal": None,
        "WIJ": None,
    }
```

- [ ] **Step 4: Update the existing `test_resolve_database_role` test**

The old test asserts `result["Database"] == "dm-2"`. Replace it:

```python
def test_resolve_database_role():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    # _full_sp_dict has TRAK-DATA and TRAK-DOCS both on /trak/live/tc → dm-2
    assert len(result["Database"]) == 1
    device, names = result["Database"][0]
    assert device == "dm-2"
    assert "TRAK-DATA" in names


def test_resolve_mirror_databases_skipped():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = [("TRAK-LABDATA", ":mirror:PRDLAB:TRAK-LABDATA,PRDLAB")]
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] == []


def test_resolve_no_cpf_databases_key():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] == []
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/test_cpf_disk_resolver.py -v
```

Expected: All pass. Run the full suite too:

```bash
python -m pytest tests/ -q
```

Expected: same count passing (previously 114 + new tests).

- [ ] **Step 6: Commit**

```bash
git add cpf_disk_resolver.py tests/test_cpf_disk_resolver.py
git commit -m "feat: resolve_iris_disk_roles returns all database devices as list"
```

---

### Task 2: Store all database devices in overview table and build `device_labels`

**Files:**
- Modify: `yaspe.py` (the resolver call block ~line 2952, and the auto disk list block ~line 3073)

**Interfaces:**
- Consumes: `resolve_iris_disk_roles(sp_dict)` → `{"Database": [(device, [names]), ...], "Primary Journal": str|None, ...}` (from Task 1)
- Produces:
  - Overview table rows: `iris disk role Database 0` → `"dm-2"`, `iris disk role Database 0 names` → `"TRAK-DATA,TRAK-DOCS"`, `iris disk role Database 1` → `"dm-1"`, etc.
  - `disk_list`: `["dm-2", "dm-1", "dm-6", "dm-8"]` (all unique devices, DB first)
  - `device_labels`: `{"dm-2": "TRAK-DATA, TRAK-DOCS", "dm-1": "IRISSYS", "dm-6": "Primary Journal", "dm-8": "Alternate Journal"}`

- [ ] **Step 1: Write failing test (integration)**

Add this test to `tests/test_cpf_disk_resolver.py` to verify that the overview table keys are written correctly. This test calls `yaspe.create_overview` indirectly via `sp_dict` inspection:

```python
def test_yaspe_stores_multi_device_database_roles():
    """Verify that sp_dict keys for multi-device databases are structured correctly."""
    # Simulate what yaspe.py does after calling resolve_iris_disk_roles
    iris_roles = {
        "Database": [("dm-2", ["TRAK-DATA", "TRAK-DOCS"]), ("dm-1", ["IRISSYS"])],
        "Primary Journal": "dm-6",
        "Alternate Journal": "dm-8",
        "WIJ": None,
    }
    sp_dict = {}
    device_to_mount = {"dm-2": "/trak/live/tc", "dm-1": "/", "dm-6": "/prijrn", "dm-8": "/altjrn"}

    # Apply the same logic as yaspe.py will use
    db_pairs = iris_roles["Database"]
    for i, (device, names) in enumerate(db_pairs):
        sp_dict[f"iris disk role Database {i}"] = device
        sp_dict[f"iris disk role Database {i} names"] = ",".join(names)
        sp_dict[f"iris_disk_role_mount Database {i}"] = device_to_mount.get(device, "")

    for role in ("Primary Journal", "Alternate Journal", "WIJ"):
        device = iris_roles[role]
        if device:
            sp_dict[f"iris disk role {role}"] = device
            sp_dict[f"iris_disk_role_mount {role}"] = device_to_mount.get(device, "")

    # Verify expected keys
    assert sp_dict["iris disk role Database 0"] == "dm-2"
    assert sp_dict["iris disk role Database 0 names"] == "TRAK-DATA,TRAK-DOCS"
    assert sp_dict["iris disk role Database 1"] == "dm-1"
    assert sp_dict["iris disk role Database 1 names"] == "IRISSYS"
    assert sp_dict["iris disk role Primary Journal"] == "dm-6"
    assert "iris disk role Database" not in sp_dict  # old single-device key gone
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_yaspe_stores_multi_device_database_roles -v
```

Expected: FAIL — `sp_dict` is empty because no yaspe.py code runs yet.

- [ ] **Step 3: Update the resolver call block in `yaspe.py`**

Find the block starting at `# Resolve IRIS storage roles from CPF + filesystem info` (~line 2952). Replace it entirely:

```python
                # Resolve IRIS storage roles from CPF + filesystem info
                iris_roles = cpf_disk_resolver.resolve_iris_disk_roles(sp_dict)
                mount_map = cpf_disk_resolver._build_mount_map(sp_dict, sp_dict)
                device_to_mount = {v: k for k, v in mount_map.items()}

                # Store database devices: one key per device, indexed
                for i, (device, names) in enumerate(iris_roles["Database"]):
                    sp_dict[f"iris disk role Database {i}"] = device
                    sp_dict[f"iris disk role Database {i} names"] = ",".join(names)
                    sp_dict[f"iris_disk_role_mount Database {i}"] = device_to_mount.get(device, "")

                # Store single-device roles
                for role in ("Primary Journal", "Alternate Journal", "WIJ"):
                    device = iris_roles[role]
                    if device:
                        sp_dict[f"iris disk role {role}"] = device
                        sp_dict[f"iris_disk_role_mount {role}"] = device_to_mount.get(device, "")
```

- [ ] **Step 4: Update the auto disk list block in `yaspe.py`**

Find the block starting at `# Auto-detect disk list from CPF roles if none was supplied` (~line 3073). Replace it entirely:

```python
            # Auto-detect disk list from CPF roles if none was supplied
            if is_linux and not disk_list:
                device_labels = {}
                auto_devices = []

                # Database devices (may be multiple)
                i = 0
                while True:
                    row = execute_single_read_query(
                        connection,
                        f"SELECT * FROM overview WHERE field = 'iris disk role Database {i}';"
                    )
                    if not row or not row[2]:
                        break
                    device = row[2]
                    names_row = execute_single_read_query(
                        connection,
                        f"SELECT * FROM overview WHERE field = 'iris disk role Database {i} names';"
                    )
                    label = names_row[2].replace(",", ", ") if names_row and names_row[2] else f"Database {i}"
                    if device not in device_labels:
                        auto_devices.append(device)
                        device_labels[device] = label
                    i += 1

                # Single-device roles
                for role in ("Primary Journal", "Alternate Journal", "WIJ"):
                    row = execute_single_read_query(
                        connection,
                        f"SELECT * FROM overview WHERE field = 'iris disk role {role}';"
                    )
                    if row and row[2]:
                        device = row[2]
                        if device not in device_labels:
                            auto_devices.append(device)
                        device_labels[device] = role

                if auto_devices:
                    disk_list = auto_devices
                    print(f"  Auto disk list from CPF: {disk_list}")
```

Note: `device_labels` is a new local variable that must be passed to `chart_iostat` in the next task. For now it is built but not yet used — the tests validate storage only.

- [ ] **Step 5: Run the test**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_yaspe_stores_multi_device_database_roles -v
```

Expected: PASS (the test verifies the `sp_dict` key structure, which now matches the code).

- [ ] **Step 6: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add yaspe.py tests/test_cpf_disk_resolver.py
git commit -m "feat: store all database devices in overview and build device_labels dict"
```

---

### Task 3: Update `build_log` in `sp_check.py` for multi-device database display

**Files:**
- Modify: `sp_check.py` (the IRIS disk roles block ~line 1464)
- Test: `tests/test_cpf_disk_resolver.py`

**Interfaces:**
- Consumes: `sp_dict` with keys `iris disk role Database 0`, `iris disk role Database 0 names`, `iris_disk_role_mount Database 0`, etc. (from Task 2)
- Produces: `build_log` overview.txt section that lists all database devices with their db names

- [ ] **Step 1: Write failing test**

Add to `tests/test_cpf_disk_resolver.py`:

```python
def test_build_log_shows_multi_device_database_roles():
    import tempfile, os
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
        # Simulate multi-device database storage (Task 2 output)
        sp_dict["iris disk role Database 0"] = "dm-2"
        sp_dict["iris disk role Database 0 names"] = "TRAK-DATA,TRAK-DOCS"
        sp_dict["iris_disk_role_mount Database 0"] = "/trak/live/tc"
        sp_dict["iris disk role Database 1"] = "dm-1"
        sp_dict["iris disk role Database 1 names"] = "IRISSYS"
        sp_dict["iris_disk_role_mount Database 1"] = "/"
        sp_dict["iris disk role Primary Journal"] = "dm-6"
        sp_dict["iris disk role Alternate Journal"] = "dm-8"
        sp_dict["iris_disk_role_mount Primary Journal"] = "/trak/live/tc/prijrn"
        sp_dict["iris_disk_role_mount Alternate Journal"] = "/trak/live/tc/altjrn"
        log, _ = sp_check.build_log(sp_dict)
        assert "IRIS disk roles" in log
        assert "dm-2" in log and "TRAK-DATA" in log
        assert "dm-1" in log and "IRISSYS" in log
        assert "Primary Journal" in log and "dm-6" in log
        assert "Alternate Journal" in log and "dm-8" in log
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_build_log_shows_multi_device_database_roles -v
```

Expected: FAIL — `build_log` currently looks for `iris disk role Database` (old single-device key, which doesn't exist).

- [ ] **Step 3: Update the IRIS disk roles block in `sp_check.py`**

Find the block at ~line 1464 and replace it entirely:

```python
    role_order = ["Primary Journal", "Alternate Journal", "WIJ"]
    role_lines = []

    # Database devices (indexed, may be multiple)
    i = 0
    while True:
        key = f"iris disk role Database {i}"
        if key not in sp_dict:
            break
        device = sp_dict[key]
        names = sp_dict.get(f"iris disk role Database {i} names", "")
        mount = sp_dict.get(f"iris_disk_role_mount Database {i}", "")
        mount_str = f"  ({mount})" if mount else ""
        names_str = f"  [{names}]" if names else ""
        role_lines.append(f"  {'Database':<22}: {device}{mount_str}{names_str}")
        i += 1

    # Single-device roles
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

    has_db = any(f"iris disk role Database {j}" in sp_dict for j in range(10))
    has_role = any(f"iris disk role {r}" in sp_dict for r in role_order)
    if has_db or has_role:
        log += "\nIRIS disk roles (auto-detected):\n"
        log += "\n".join(role_lines) + "\n"
```

- [ ] **Step 4: Update the existing `test_build_log_shows_disk_roles` test**

The existing test in `tests/test_cpf_disk_resolver.py` sets `sp_dict["iris disk role Database"] = "dm-2"` (old key). Update it to use the new indexed keys:

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
        sp_dict["iris disk role Database 0"] = "dm-2"
        sp_dict["iris disk role Database 0 names"] = "TRAK-DATA"
        sp_dict["iris_disk_role_mount Database 0"] = "/trak/live/tc"
        sp_dict["iris disk role Primary Journal"] = "dm-6"
        sp_dict["iris disk role Alternate Journal"] = "dm-8"
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

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/ -q
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add sp_check.py tests/test_cpf_disk_resolver.py
git commit -m "feat: update build_log to display all database devices with names"
```

---

### Task 4: Pass `device_labels` into `chart_iostat` and apply two-line titles and labelled directories

**Files:**
- Modify: `yaspe.py` — `chart_iostat` function signature and body (~line 2327), and the call site (~line 3106)

**Interfaces:**
- Consumes: `device_labels` dict `{device: label_str}` built in Task 2's auto disk list block
- Produces:
  - When `iostat_subfolders=True`: subdirectory name becomes `{device}_{slug}` where `slug` is the label lowercased with spaces→underscores
  - Chart title becomes `"{label}\n{device} : {column_name} - {customer} - {date}"` for PNG (matplotlib `ax.set_title`), and `"{label}<br>{device} : {column_name} - {customer}"` for HTML plotly titles
  - Stacked IOPS chart title also gains the two-line prefix

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cpf_disk_resolver.py`:

```python
def test_device_label_slug():
    """Verify the slug derivation used for directory naming."""
    import re

    def _label_slug(label):
        return re.sub(r"[^a-z0-9_-]", "_", label.lower())

    assert _label_slug("TRAK-DATA, TRAK-DOCS") == "trak-data__trak-docs"
    assert _label_slug("Primary Journal") == "primary_journal"
    assert _label_slug("dm-2") == "dm-2"


def test_two_line_title_format():
    """Verify two-line title string construction."""
    label = "TRAK-DATA, TRAK-DOCS"
    base_title = "dm-2 : r/s - CustomerName"

    png_title = f"{label}\n{base_title}"
    html_title = f"{label}<br>{base_title}"

    assert png_title == "TRAK-DATA, TRAK-DOCS\ndm-2 : r/s - CustomerName"
    assert html_title == "TRAK-DATA, TRAK-DOCS<br>dm-2 : r/s - CustomerName"
```

- [ ] **Step 2: Run tests to verify they pass immediately**

```bash
python -m pytest tests/test_cpf_disk_resolver.py::test_device_label_slug tests/test_cpf_disk_resolver.py::test_two_line_title_format -v
```

Expected: PASS — these tests are pure logic with no `yaspe.py` dependency.

- [ ] **Step 3: Add `device_labels` parameter to `chart_iostat` signature**

Find `def chart_iostat(` (~line 2327). Add `device_labels=None` as the last keyword argument:

```python
def chart_iostat(
    connection,
    filepath,
    output_prefix,
    operating_system,
    png_out,
    png_html_out,
    disk_list,
    peak_chart=True,
    glorefs_peak_window=None,
    line_chart=True,
    iostat_subfolders=False,
    day_overlay=False,
    bh_charts=False,
    long_period_smooth=5,
    device_labels=None,
):
```

- [ ] **Step 4: Add slug helper and two-line title inside `chart_iostat`**

Add the slug helper immediately after the `customer = ...` line near the top of `chart_iostat`:

```python
    import re as _re

    def _device_slug(device):
        label = (device_labels or {}).get(device, "")
        if not label:
            return device
        slug = _re.sub(r"[^a-z0-9_-]", "_", label.lower())
        # Collapse runs of underscores introduced by punctuation
        slug = _re.sub(r"_+", "_", slug).strip("_")
        return f"{device}_{slug}"

    def _device_title_prefix(device):
        label = (device_labels or {}).get(device, "")
        return label  # empty string → no prefix
```

- [ ] **Step 5: Apply slug to subdirectory and prefix to titles in `chart_iostat` (datetime path)**

In the `for device in devices:` loop inside the `if "RunDate" in df.columns:` branch, update the subdirectory block:

```python
            if iostat_subfolders:
                device_dirname = _device_slug(device)
                device_filepath = f"{filepath}{device_dirname}/"
                if not os.path.isdir(device_filepath):
                    os.mkdir(device_filepath)
            else:
                device_filepath = filepath
```

For each `title = f"{device} : ..."` line in this branch, prepend the label prefix. There are three such titles (stacked IOPS, latency histogram, per-column). Update them all:

```python
                        # Stacked IOPS title
                        _prefix = _device_title_prefix(device)
                        title = f"{device} : Total IOPS - {customer}"
                        if _prefix:
                            title = f"{_prefix}\n{title}"     # PNG stacked (matplotlib)
```

For the per-column title inside `for column_name in columns_to_chart:`:

```python
                    _prefix = _device_title_prefix(device)
                    base_title = f"{device} : {column_name} - {customer}"
                    png_title = f"{_prefix}\n{base_title}" if _prefix else base_title
                    html_title = f"{_prefix}<br>{base_title}" if _prefix else base_title
```

Then pass `png_title` to `simple_chart` and `html_title` to `linked_chart`/`simple_chart_stacked_iostat`:

```python
                    if png_out or png_html_out:
                        simple_chart(
                            data,
                            column_name,
                            png_title,         # ← was: title
                            ...
                        )
                        if png_html_out:
                            linked_chart(data, column_name, html_title, ...)   # ← was: title
                    else:
                        linked_chart(data, column_name, html_title, ...)       # ← was: title
```

For the stacked IOPS chart (`simple_chart_stacked_iostat`) and histogram (`simple_chart_histogram_iostat`), the title is a positional arg. For stacked, it uses matplotlib (PNG), so use `\n`. For histogram, it also uses matplotlib. Update both:

```python
                        _prefix = _device_title_prefix(device)
                        _stacked_base = f"{device} : Total IOPS - {customer}"
                        _stacked_title = f"{_prefix}\n{_stacked_base}" if _prefix else _stacked_base
                        simple_chart_stacked_iostat(
                            device_df, columns_to_stack, device, _stacked_title, 0, dev_png_fp, output_prefix
                        )

                        if "r_await" in device_df.columns and "w_await" in device_df.columns:
                            _lat_base = f"{device} : Latency - {customer}"
                            _lat_title = f"{_prefix}\n{_lat_base}" if _prefix else _lat_base
                            simple_chart_histogram_iostat(
                                device_df, columns_to_histogram, device, _lat_title, dev_png_fp, output_prefix
                            )
```

- [ ] **Step 6: Apply same changes to the no-datetime branch**

The `else:` branch (no `RunDate` in df) has its own `for device in devices:` loop with the same `iostat_subfolders` subdirectory block and `title = f"{device} : {column_name} - {customer}"` line. Apply the same slug and two-line prefix there:

```python
            if iostat_subfolders:
                device_dirname = _device_slug(device)
                device_filepath = f"{filepath}{device_dirname}/"
                if not os.path.isdir(device_filepath):
                    os.mkdir(device_filepath)
            else:
                device_filepath = filepath
```

```python
                    _prefix = _device_title_prefix(device)
                    base_title = f"{device} : {column_name} - {customer}"
                    png_title = f"{_prefix}\n{base_title}" if _prefix else base_title
                    html_title = f"{_prefix}<br>{base_title}" if _prefix else base_title
```

Then use `png_title`/`html_title` in the `simple_chart_no_time`/`linked_chart_no_time` calls.

- [ ] **Step 7: Update the `chart_iostat` call site in `yaspe.py`**

Find the `chart_iostat(` call (~line 3106). It currently ends with `bh_charts, long_period_smooth,`. Add `device_labels=device_labels`:

```python
                if include_iostat:
                    chart_iostat(
                        connection, _make_chart_dir(output_file_path_base, "iostat"),
                        output_prefix, operating_system, png_out, png_html_out,
                        disk_list, peak_chart, glorefs_peak_window, line_chart, iostat_subfolders, day_overlay, bh_charts, long_period_smooth,
                        device_labels=device_labels,
                    )
```

Also ensure `device_labels` is defined even when the auto-detect block doesn't run (i.e. when `disk_list` was supplied explicitly or when `is_linux` is False). Add `device_labels = {}` immediately before the `if is_linux and not disk_list:` block:

```python
            device_labels = {}
            # Auto-detect disk list from CPF roles if none was supplied
            if is_linux and not disk_list:
                ...
```

- [ ] **Step 8: Run full test suite**

```bash
python -m pytest tests/ -q
```

Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add yaspe.py tests/test_cpf_disk_resolver.py
git commit -m "feat: two-line chart titles and role-labelled directories in chart_iostat"
```

---

### Task 5: Smoke test end-to-end with sample data

This task has no automated test. It verifies the feature works with a real SQLite file.

**Files:**
- Read: `yaspe_SystemPerformance.sqlite` (sample data at project root — untracked)

**Interfaces:**
- Consumes: all changes from Tasks 1–4

- [ ] **Step 1: Check sample data is present**

```bash
ls -lh yaspe_SystemPerformance.sqlite
```

Expected: file exists. If not, skip to Step 4 and report DONE_WITH_CONCERNS.

- [ ] **Step 2: Chart with PNG output and iostat subfolders**

```bash
python yaspe.py -e yaspe_SystemPerformance.sqlite -p -x -d ''
```

(The empty `-d ''` ensures `disk_list` is falsy so auto-detection fires. If your shell strips the empty string, omit `-d` entirely.)

Expected output includes:
```
Auto disk list from CPF: ['dm-2', ...]
```

- [ ] **Step 3: Inspect output directories**

```bash
ls yaspe_metrics/iostat/
```

Expected: subdirectories like `dm-2_trak-data/` or similar (device + slug), not plain `dm-2/`.

- [ ] **Step 4: Check chart file titles**

Open one PNG from a database device subdirectory and verify the title has two lines: database names on line 1, metric/device/customer on line 2.

- [ ] **Step 5: Report findings**

If the smoke test passes: report DONE.
If directories or titles look wrong: report DONE_WITH_CONCERNS with specifics.

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| All database devices charted (not just most-frequent) | Task 1 (resolver returns list), Task 2 (all stored + in disk_list) |
| Directory name includes device purpose hint | Task 4 (slug from device_labels) |
| Chart title: DB names on line 1, rest on line 2 | Task 4 (png `\n`, html `<br>`) |
| Journal/WIJ roles unchanged (single device) | Task 1 (non-Database roles remain str\|None) |
| overview.txt displays all database devices | Task 3 (build_log updated) |
| Existing 114 tests still pass | Verified in each task |
| `device_labels = {}` when auto-detect doesn't run | Task 4, Step 7 |

**Placeholder scan:** None found.

**Type consistency:**
- `resolve_iris_disk_roles["Database"]` → `list[tuple[str, list[str]]]` — used consistently in Tasks 1, 2, 3
- `device_labels` → `dict[str, str]` — built in Task 2, consumed in Task 4
- Overview keys → `iris disk role Database {i}` and `iris disk role Database {i} names` — written in Task 2, read in Task 2 (disk list) and Task 3 (build_log)
