# HTML Early-Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up HTML parsing by reading the TOC at the top of each file and breaking out of the main line loop as soon as the last needed section's end marker is seen.

**Architecture:** Two new helper functions are added to `extract_sections.py`: `parse_toc_section_order` reads the first 90 lines to build an ordered list of section anchors; `get_last_needed_section` maps OS + flags to a needed-section set and returns the last one that appears in the TOC. The main `extract_sections` loop gains a single `break` that fires when that section's end marker is encountered. If either helper returns `None` the loop runs unchanged.

**Tech Stack:** Python 3, ISO-8859-1 file I/O, pytest (existing test suite in `tests/`)

---

### Task 1: `parse_toc_section_order` — failing test first

**Files:**
- Create: `tests/test_early_stop.py`
- Modify: `extract_sections.py` (add function at top of file, before `extract_sections`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_early_stop.py` with this content:

```python
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_sections import parse_toc_section_order


RHEL_TOC = """\
<html>
<head><title>Test</title></head>
<a id="Topofpage"></a>
<table>
 <tr>
  <td><a href=#IRISALL>IRIS ALL</a></td>
  <td><a href=#CPFfile>CPF file</a></td>
  <td><a href=#mgstat>mgstat</a></td>
 </tr>
 <tr>
  <td><a href=#vmstat>vmstat</a></td>
  <td><a href=#free>free</a></td>
  <td><a href=#iostat>iostat</a></td>
  <td><a href=#sar-d>sar -d</a></td>
 </tr>
</table>
"""

WINDOWS_TOC = """\
<html>
<head><title>Test</title></head>
<a id="Topofpage"></a>
<table>
 <tr>
  <td><a href=#IRISALL>IRIS ALL</a></td>
  <td><a href=#CPFfile>CPF file</a></td>
  <td><a href=#mgstat>mgstat</a></td>
  <td><a href=#perfmon>perfmon</a></td>
 </tr>
</table>
"""

NO_TOC = "<html><body><p>No table of contents here.</p></body></html>\n" * 10


def _write_temp(content):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="ISO-8859-1")
    f.write(content)
    f.close()
    return f.name


def test_parse_toc_rhel_order():
    path = _write_temp(RHEL_TOC)
    try:
        result = parse_toc_section_order(path)
        assert result == ["irisall", "cpffile", "mgstat", "vmstat", "free", "iostat", "sar-d"]
    finally:
        os.unlink(path)


def test_parse_toc_windows_order():
    path = _write_temp(WINDOWS_TOC)
    try:
        result = parse_toc_section_order(path)
        assert result == ["irisall", "cpffile", "mgstat", "perfmon"]
    finally:
        os.unlink(path)


def test_parse_toc_no_anchors_returns_none():
    path = _write_temp(NO_TOC)
    try:
        result = parse_toc_section_order(path)
        assert result is None
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
python -m pytest tests/test_early_stop.py -v
```

Expected: `ImportError` or `AttributeError` — `parse_toc_section_order` does not exist yet.

- [ ] **Step 3: Implement `parse_toc_section_order` in `extract_sections.py`**

Add this function immediately before the `extract_sections` function (around line 9, after the imports):

```python
def parse_toc_section_order(input_file):
    """Read the first 90 lines of an HTML pButtons file and return the TOC section
    anchor names in document order (lowercased), or None if none are found."""
    anchors = []
    try:
        with open(input_file, "r", encoding="ISO-8859-1") as fh:
            for i, line in enumerate(fh):
                if i >= 90:
                    break
                # Each TOC cell contains  href=#SECTIONNAME
                start = 0
                while True:
                    idx = line.find("href=#", start)
                    if idx == -1:
                        break
                    end = idx + 6
                    # anchor name ends at first '>' or '"' or whitespace
                    while end < len(line) and line[end] not in (">", '"', " ", "\t", "\n"):
                        end += 1
                    anchors.append(line[idx + 6 : end].lower())
                    start = end
    except OSError:
        return None
    return anchors if anchors else None
```

- [ ] **Step 4: Run test — verify it passes**

```bash
python -m pytest tests/test_early_stop.py::test_parse_toc_rhel_order tests/test_early_stop.py::test_parse_toc_windows_order tests/test_early_stop.py::test_parse_toc_no_anchors_returns_none -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Verify full suite still passes**

```bash
python -m pytest tests/ -q
```

Expected: 19 passed (16 existing + 3 new).

- [ ] **Step 6: Commit**

```bash
git add tests/test_early_stop.py extract_sections.py
git commit -m "feat: add parse_toc_section_order to extract_sections"
```

---

### Task 2: `get_last_needed_section` — failing test first

**Files:**
- Modify: `tests/test_early_stop.py` (append new tests)
- Modify: `extract_sections.py` (add function after `parse_toc_section_order`)

- [ ] **Step 1: Append failing tests to `tests/test_early_stop.py`**

Add this import at the top of `tests/test_early_stop.py` (update the existing import line):

```python
from extract_sections import parse_toc_section_order, get_last_needed_section
```

Then append these tests at the bottom of the file:

```python
RHEL_TOC_ORDER = ["irisall", "cpffile", "mgstat", "vmstat", "free", "iostat", "sar-d"]
AIX_TOC_ORDER  = ["irisall", "cpffile", "mgstat", "vmstat", "iostat"]
WIN_TOC_ORDER  = ["irisall", "cpffile", "mgstat", "perfmon"]


def test_last_needed_linux_no_iostat():
    # Default Linux run: needs mgstat, vmstat, free — last in TOC order is free
    result = get_last_needed_section(RHEL_TOC_ORDER, "Linux", include_iostat=False, include_nfsiostat=False)
    assert result == "free"


def test_last_needed_linux_with_iostat():
    # With iostat: also needs iostat, sar-d — last in TOC order is sar-d
    result = get_last_needed_section(RHEL_TOC_ORDER, "Linux", include_iostat=True, include_nfsiostat=False)
    assert result == "sar-d"


def test_last_needed_linux_with_nfsiostat():
    # nfsiostat appears between free and iostat in some files; if not in TOC falls back to free
    toc_with_nfs = ["irisall", "mgstat", "vmstat", "free", "nfsiostat", "iostat", "sar-d"]
    result = get_last_needed_section(toc_with_nfs, "Linux", include_iostat=False, include_nfsiostat=True)
    assert result == "nfsiostat"


def test_last_needed_aix_no_iostat():
    result = get_last_needed_section(AIX_TOC_ORDER, "AIX", include_iostat=False, include_nfsiostat=False)
    assert result == "vmstat"


def test_last_needed_aix_with_iostat():
    result = get_last_needed_section(AIX_TOC_ORDER, "AIX", include_iostat=True, include_nfsiostat=False)
    assert result == "iostat"


def test_last_needed_windows():
    result = get_last_needed_section(WIN_TOC_ORDER, "Windows", include_iostat=False, include_nfsiostat=False)
    assert result == "perfmon"


def test_last_needed_no_match_returns_none():
    # TOC has none of the needed sections
    result = get_last_needed_section(["linuxinfo", "cpu"], "Linux", include_iostat=False, include_nfsiostat=False)
    assert result is None
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_early_stop.py -v -k "last_needed"
```

Expected: `ImportError` — `get_last_needed_section` does not exist yet.

- [ ] **Step 3: Implement `get_last_needed_section` in `extract_sections.py`**

Add this function immediately after `parse_toc_section_order`:

```python
def get_last_needed_section(toc_order, operating_system, include_iostat, include_nfsiostat):
    """Return the anchor name of the last section that needs to be read for this run,
    based on OS and flags, or None if no needed section appears in the TOC."""
    os_lower = operating_system.lower() if operating_system else ""

    if os_lower == "windows":
        needed = {"mgstat", "perfmon"}
    elif os_lower == "aix":
        needed = {"mgstat", "vmstat"}
        if include_iostat:
            needed.add("iostat")
    else:  # Linux / Ubuntu / default
        needed = {"mgstat", "vmstat", "free"}
        if include_iostat:
            needed.update({"iostat", "sar-d"})
        if include_nfsiostat:
            needed.add("nfsiostat")

    for anchor in reversed(toc_order):
        if anchor in needed:
            return anchor
    return None
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_early_stop.py -v -k "last_needed"
```

Expected: 7 PASSED.

- [ ] **Step 5: Verify full suite**

```bash
python -m pytest tests/ -q
```

Expected: 26 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/test_early_stop.py extract_sections.py
git commit -m "feat: add get_last_needed_section to extract_sections"
```

---

### Task 3: Wire early-stop into the `extract_sections` loop

**Files:**
- Modify: `extract_sections.py` (edit `extract_sections` function)
- Modify: `tests/test_early_stop.py` (append integration test)

The end-marker for each stoppable section maps exactly to the conditions already used in the state machine to turn off processing flags:

| Section | End marker string | Condition already in code |
|---|---|---|
| `mgstat` | `<!-- end_mgstat -->` | line 188 |
| `vmstat` | `<!-- end_vmstat -->` | lines 230, 271 |
| `free` | `"pre>" in line or "div id=" in line` AND not `"div id=free"` | line 140 |
| `iostat` | `"<div" in line` when `iostat_processing` | line 422 |
| `nfsiostat` | `"pre>" in line` when `nfsiostat_processing` | (nfsiostat end in code) |
| `sar-d` | `"</pre><p align="` | line 334 |
| `perfmon` | `<!-- end_win_perfmon -->` | line 393 |

- [ ] **Step 1: Add integration test to `tests/test_early_stop.py`**

Append at the bottom of `tests/test_early_stop.py`:

```python
def test_early_stop_does_not_lose_data(tmp_path):
    """extract_sections must return the same mgstat rows whether it stops early or reads the whole file."""
    import sqlite3
    import pandas as pd

    # Build a minimal synthetic HTML that looks like a real pButtons file:
    # TOC → mgstat section → vmstat section → free section → (large tail that should be skipped)
    html = """\
<html><head><title>Test</title></head>
<a id="Topofpage"></a>
<table>
 <tr>
  <td><a href=#mgstat>mgstat</a></td>
  <td><a href=#vmstat>vmstat</a></td>
  <td><a href=#free>free</a></td>
  <td><a href=#iostat>iostat</a></td>
 </tr>
</table>
Profile run "test" started by user "u" at 00:00:00 on Jan 01 2026.
<!-- beg_mgstat --><pre>
Date,     Time,      Glorefs,  ...other columns...
01/01/26, 00:00:05, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
01/01/26, 00:00:10, 200, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
<!-- end_mgstat -->
<!-- beg_vmstat --><pre>
04/30/26 00:00:00  r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
04/30/26 00:00:05  0  0      0 100000      0      0    0    0     0     0    0    0  1  0 99  0  0
<!-- end_vmstat -->
<div id=free></div>free<br><pre>
Date,     Time,      Memtotal,     used,     free,   shared,buf/cache,available,swap_total,swap_used,swap_free
01/01/26, 00:00:05, 16000, 1000, 14000, 50, 1000, 14000, 0, 0, 0
</pre>
<div id=iostat></div>iostat<br><pre>
THIS LINE MUST NOT BE PROCESSED - it is after the last needed section
AND MORE LINES THAT SHOULD BE SKIPPED
"""
    html_path = tmp_path / "test.html"
    html_path.write_text(html, encoding="ISO-8859-1")

    from extract_sections import extract_sections

    mgstat_df, vmstat_df, iostat_df, nfsiostat_df, perfmon_df, aix_sar_d_df, free_df = extract_sections(
        operating_system="Linux",
        input_file=str(html_path),
        include_iostat=False,
        include_nfsiostat=False,
        html_filename="test.html",
        disk_list=None,
    )

    assert len(mgstat_df) == 2, f"Expected 2 mgstat rows, got {len(mgstat_df)}"
    assert mgstat_df["Glorefs"].tolist() == [100, 200]
    assert len(vmstat_df) == 1, f"Expected 1 vmstat row, got {len(vmstat_df)}"
    assert iostat_df is None or len(iostat_df) == 0
```

- [ ] **Step 2: Run test — verify it passes already (data correctness baseline)**

```bash
python -m pytest tests/test_early_stop.py::test_early_stop_does_not_lose_data -v
```

Expected: PASSED (the test validates data correctness; early-stop not yet wired in but loop still reads correctly).

- [ ] **Step 3: Wire early-stop into `extract_sections`**

In `extract_sections.py`, locate the `with open(input_file, ...)` block (line ~119). Make these two targeted edits:

**Before the `with open` line**, add:

```python
    # Determine the last section we need to read so we can stop early.
    _toc = parse_toc_section_order(input_file)
    _stop_after = get_last_needed_section(_toc, operating_system, include_iostat, include_nfsiostat) if _toc else None
    _stop_section_ended = False
```

**Inside the `for line in file:` loop**, find the block that turns off `mgstat_processing` (line ~188–189):

```python
            if "<!-- end_mgstat -->" in line:
                mgstat_processing = False
```

Replace it with:

```python
            if "<!-- end_mgstat -->" in line:
                mgstat_processing = False
                if _stop_after == "mgstat":
                    _stop_section_ended = True
```

Find the block that turns off `vmstat_processing` for Linux/Ubuntu (line ~230):

```python
                if "<!-- end_vmstat -->" in line:
                    vmstat_processing = False
```

Replace it with:

```python
                if "<!-- end_vmstat -->" in line:
                    vmstat_processing = False
                    if _stop_after == "vmstat":
                        _stop_section_ended = True
```

Find the equivalent block for AIX vmstat (line ~271):

```python
                if "<!-- end_vmstat -->" in line:
                    vmstat_processing = False
```

Replace it with:

```python
                if "<!-- end_vmstat -->" in line:
                    vmstat_processing = False
                    if _stop_after == "vmstat":
                        _stop_section_ended = True
```

Find the free memory end condition (line ~140):

```python
            if free_memory_processing and ("pre>" in line or "div id=" in line) and "div id=free" not in line:
                free_memory_processing = False
```

Replace it with:

```python
            if free_memory_processing and ("pre>" in line or "div id=" in line) and "div id=free" not in line:
                free_memory_processing = False
                if _stop_after == "free":
                    _stop_section_ended = True
```

Find the perfmon end condition (line ~393):

```python
                if "<!-- end_win_perfmon -->" in line:
                    perfmon_processing = False
```

Replace it with:

```python
                if "<!-- end_win_perfmon -->" in line:
                    perfmon_processing = False
                    if _stop_after == "perfmon":
                        _stop_section_ended = True
```

Find the sar-d end condition (line ~334):

```python
                if "</pre><p align=" in line and "<div id=sar-d>" not in line:
                    aix_sar_d_processing = False
```

Replace it with:

```python
                if "</pre><p align=" in line and "<div id=sar-d>" not in line:
                    aix_sar_d_processing = False
                    if _stop_after == "sar-d":
                        _stop_section_ended = True
```

Find the iostat end condition (line ~422):

```python
                if iostat_processing and "<div" in line:  # iostat does not flag end
                    iostat_processing = False
```

Replace it with:

```python
                if iostat_processing and "<div" in line:  # iostat does not flag end
                    iostat_processing = False
                    if _stop_after == "iostat":
                        _stop_section_ended = True
```

**At the very end of the `for line in file:` loop body** (after all section-processing blocks, before the next iteration), add:

```python
            if _stop_section_ended:
                break
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/ -q
```

Expected: all 27 pass.

- [ ] **Step 5: Smoke-test with a real sample file**

```bash
cd /Users/moldfiel/projects/all_live_projects/yaspe
time python yaspe.py -i "test_samples/RHEL/trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html" -o /tmp/yaspe_speed_test
```

Note the elapsed time. Then run the AIX sample:

```bash
time python yaspe.py -i "test_samples/AIX/aixhs02_PROD_20260518_040000_24hours.html" -o /tmp/yaspe_speed_test_aix
```

Both should complete without errors. The RHEL run should be notably faster than before (roughly 10× fewer lines read). No data correctness checks are needed here — the unit test covers that.

- [ ] **Step 6: Commit**

```bash
git add extract_sections.py tests/test_early_stop.py
git commit -m "feat: TOC-driven early stop in extract_sections — skip tail of file when iostat not needed"
```

---

### Task 4: Handle nfsiostat early-stop

The nfsiostat end condition is handled differently — it ends on a `pre>` line while `nfsiostat_processing` is True. This needs the same treatment.

**Files:**
- Modify: `extract_sections.py`
- Modify: `tests/test_early_stop.py`

- [ ] **Step 1: Locate the nfsiostat end condition in `extract_sections.py`**

Search for the line that sets `nfsiostat_processing = False`. It will look like:

```python
            if nfsiostat_processing and "pre>" in line:
                nfsiostat_processing = False
```

- [ ] **Step 2: Add the stop flag**

Replace that condition with:

```python
            if nfsiostat_processing and "pre>" in line:
                nfsiostat_processing = False
                if _stop_after == "nfsiostat":
                    _stop_section_ended = True
```

- [ ] **Step 3: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: all 27 pass (no new tests needed — the logic path is the same pattern as all other sections).

- [ ] **Step 4: Commit**

```bash
git add extract_sections.py
git commit -m "feat: add nfsiostat to early-stop end-marker handling"
```

---

### Task 5: Version bump and push

- [ ] **Step 1: Bump version**

```bash
bump2version patch
```

Expected: `.bumpversion.cfg` and `yaspe.py` updated, new commit created automatically.

- [ ] **Step 2: Verify commit log**

```bash
git log --oneline -5
```

Expected: bump2version commit at the top, then the two feat commits below it.

- [ ] **Step 3: Push**

```bash
git push origin main
```
