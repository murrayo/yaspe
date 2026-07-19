# Extraction Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut SystemPerformance HTML extraction from ~55 s to ~5 s per day file by fixing number conversion, seeking directly to needed sections, and filtering iostat to CPF-resolved IRIS disks by default.

**Architecture:** Three independent speedups plus one robustness fix, layered so each is verifiable against a golden SQLite dump of the current code: (1) `get_number_type` loses its per-call `setlocale` and gains a `float()` fast path; (2) `extract_sections` gains a chunk-scanning pre-pass that maps section byte ranges and feeds only those lines to the existing (unchanged) parsing loop, falling back to the current full scan on any inconsistency; (3) `create_sections` computes an effective disk list from CPF roles already stored in the `overview` table, with a new `--all-disks` escape hatch; (4) `to_sql` appends are preceded by `ALTER TABLE ADD COLUMN` alignment so multi-day appends survive column drift.

**Tech Stack:** Python 3.12, pandas, sqlite3, pytest. Reference data: `test_samples/RHEL 1 week/aemedcprehrdb03_MCMELIVETCC_20260212_000005_24hours_5.html` (385 MB, 72 iostat devices).

**Spec:** `docs/superpowers/specs/2026-07-19-extraction-performance-design.md`

## Global Constraints

- Branch: create `feature/extraction-performance` (never commit implementation to `main` directly).
- File encoding for all pButtons reads: `ISO-8859-1`.
- No new `.py` modules → `ENGINE_FILES` in `yaspe_flask_v1/sync_engine.sh` must NOT need updating; do not create new engine files.
- Golden-diff gate: `sqlite3 <db> .dump` output must match the pre-change baseline exactly for Tasks 1–2 (and for Task 3 when run with `--all-disks`).
- Run tests with: `python3 -m pytest tests/ -v` from the repo root.
- Scratch area for baselines/timing: `/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test/` (contains `day1.html` symlink to the reference file).
- Version bump after merge to main: `bump2version minor` (new flag + new default behaviour).

---

### Task 0: Baseline golden dump and timing (no code changes)

**Files:**
- Create (scratch, not committed): `perf_test/golden_before.dump`, `perf_test/baseline_time.txt`

**Interfaces:**
- Produces: `golden_before.dump` — the reference `.dump` all later tasks diff against; `baseline_time.txt` — pre-change wall time.

- [ ] **Step 1: Produce baseline database and dump from current `main` code**

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test"
rm -f golden_SystemPerformance.sqlite
/usr/bin/time -p python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py \
    -i day1.html -a -x -o golden 2> baseline_time.txt
sqlite3 golden_SystemPerformance.sqlite .dump > golden_before.dump
wc -l golden_before.dump && grep real baseline_time.txt
```

Expected: dump has >1.2 M lines; `real` ≈ 55 s. (A prior session measured 55.6 s and 1,244,160 iostat rows across 72 devices.)

- [ ] **Step 2: Record the baseline numbers**

Note the `real` time and dump line count; they go in the PR description at the end.

---

### Task 1: Number conversion rewrite (`yaspe_utilities.py`)

**Files:**
- Modify: `yaspe_utilities.py:19-48` (`get_number_type`, `get_aix_wacky_numbers`; module top for the one-time `setlocale`)
- Test: `tests/test_number_conversion.py` (new)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `get_number_type(s) -> int | float | str` and `get_aix_wacky_numbers(s) -> int | float | str` with identical semantics to today, ~4× faster. Signatures unchanged; all callers untouched.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_number_conversion.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe_utilities import get_number_type, get_aix_wacky_numbers


def test_int_passthrough():
    assert get_number_type("134") == 134
    assert isinstance(get_number_type("134"), int)


def test_plain_float():
    assert get_number_type("0.56") == 0.56
    assert isinstance(get_number_type("0.56"), float)


def test_locale_grouped_float():
    # float() rejects this; locale.atof (en_US) must still handle it
    assert get_number_type("1,035.70") == 1035.70


def test_non_numeric_string_unchanged():
    assert get_number_type("sda") == "sda"
    assert get_number_type("") == ""


def test_none_passthrough():
    assert get_number_type(None) is None


def test_negative_and_exponent():
    assert get_number_type("-3.5") == -3.5
    assert get_number_type("1e3") == 1000.0


def test_no_per_call_setlocale():
    # setlocale must not be called inside get_number_type (that was the
    # 55-second bug: 23.6M setlocale calls per file).
    import inspect
    import yaspe_utilities
    src = inspect.getsource(yaspe_utilities.get_number_type)
    assert "setlocale" not in src


def test_aix_wacky_numbers():
    assert get_aix_wacky_numbers("13") == 13
    assert get_aix_wacky_numbers("65.5K") == 65500
    assert get_aix_wacky_numbers("4.2M") == 4200000
    assert get_aix_wacky_numbers("1.5S") == 1500
    assert get_aix_wacky_numbers("0.6") == 0.6
    assert get_aix_wacky_numbers("hdisk0") == "hdisk0"
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `python3 -m pytest tests/test_number_conversion.py -v`
Expected: `test_no_per_call_setlocale` FAILS (current source contains `setlocale`); the semantics tests PASS (they document current behaviour).

- [ ] **Step 3: Rewrite the conversion functions**

In `yaspe_utilities.py`, replace lines 19–48 with:

```python
# Set once at import. Calling setlocale per value was the dominant cost of
# extraction (23.6M calls per 24-hour file). locale.atof below relies on this.
locale.setlocale(locale.LC_ALL, "en_US.UTF-8")


def get_number_type(s):
    # Don't know if a European number or US
    try:
        return int(s)
    except (ValueError, TypeError):
        pass
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    # Grouped numbers like "1,035.70" fall through to locale-aware parsing
    try:
        return locale.atof(s)
    except (ValueError, TypeError):
        return s


def get_aix_wacky_numbers(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        pass
    try:
        if "K" in s:
            value = s.split("K")[0]
            return int(float(value) * 1000)
        elif "M" in s:
            value = s.split("M")[0]
            return int(float(value) * 1000000)
        elif "S" in s:
            value = s.split("S")[0]
            return int(float(value) * 1000)
    except (ValueError, TypeError):
        return s
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    try:
        return locale.atof(s)
    except (ValueError, TypeError):
        return s
```

Note: `get_aix_wacky_numbers` keeps its exact current behaviour for K/M/S strings (including returning the original string if e.g. `"K"` alone fails to parse — the `except` inside that block returns `s` just as the current single try/except does).

- [ ] **Step 4: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS, including the full existing suite.

- [ ] **Step 5: Golden diff against baseline**

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test"
rm -f t1_SystemPerformance.sqlite
/usr/bin/time -p python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py \
    -i day1.html -a -x -o t1 2> t1_time.txt
sqlite3 t1_SystemPerformance.sqlite .dump > t1.dump
diff golden_before.dump t1.dump && echo "GOLDEN DIFF CLEAN" && grep real t1_time.txt
```

Expected: `GOLDEN DIFF CLEAN`; wall time drops to roughly 15–20 s. If the diff is NOT clean, stop — do not rationalize differences; investigate with superpowers:systematic-debugging.

- [ ] **Step 6: Commit**

```bash
git add yaspe_utilities.py tests/test_number_conversion.py
git commit -m "perf: float-first number conversion, setlocale hoisted to import

get_number_type was 76% of extraction runtime (23.6M calls, each running
setlocale + locale.atof/localeconv). int -> float -> locale.atof ordering
keeps identical results incl. European grouped numbers. Verified via
byte-identical sqlite3 .dump on 385MB RHEL reference file. ~55s -> ~17s."
```

---

### Task 2: Section seeking with full-scan fallback (`extract_sections.py`)

**Files:**
- Modify: `extract_sections.py` (add two functions above `extract_sections`; replace the `with open(...)` loop entry at line 193)
- Test: `tests/test_section_seek.py` (new)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `build_section_ranges(input_file, needed_markers, chunk_size=4*1024*1024) -> list[tuple[int, int]] | None` — line-aligned absolute byte ranges to read, ascending, non-overlapping; `None` means "map unreliable, do a full scan".
  - `read_ranges(input_file, ranges)` — generator yielding decoded lines (with `\n`) from those ranges only.
  - `extract_sections(...)` behaviour unchanged; new optional kwarg `force_full_scan=False` (testing hook).

**Design notes for the implementer:**
- Marker offsets come from C-speed `str.find` over ~4 MB chunks — never a per-line Python loop.
- A section's range runs from the line containing its start marker to the line containing the *next* `div id=`/`<div ` boundary after it (inclusive). Feeding a few extra lines past a section end is safe: the existing loop's own end-detection (`<!-- end_mgstat -->`, `"<div" in line`, etc.) handles them exactly as it does today in a full scan. Feeding fewer lines is what must never happen.
- Range `[0, first_marker_line_start)` is always included: it carries the `Profile run` date line and is ~270 KB in real files.
- The parsing loop body is NOT modified. Only its line source changes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_section_seek.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_sections import build_section_ranges, read_ranges, extract_sections

# Synthetic pButtons file, same shape as tests/test_early_stop.py, with an
# iostat section and a tail that must never be parsed.
SYNTH = """\
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
<div id=IRISALL></div>filler section that seeking must skip<br><pre>
FILLER LINE 1
FILLER LINE 2
</pre>
<div id=mgstat></div>mgstat<br><pre>
<!-- beg_mgstat -->
Date,     Time,      Glorefs, RemGrefs, GRratio, PhyRds, Rdratio, Gloupds, RemGupds, Rourefs, RemRrefs, RouLaS, RemRLaS, PhyWrs, Gloseqz, ObjSz
01/01/26, 00:00:05, 100, 0, 0, 5, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0
01/01/26, 00:00:10, 200, 0, 0, 6, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0
<!-- end_mgstat -->
<div id=vmstat></div>vmstat<br><pre>
<!-- beg_vmstat -->
04/30/26 00:00:00  r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
04/30/26 00:00:05  0  0      0 100000      0      0    0    0     0     0    0    0  1  0 99  0  0
<!-- end_vmstat -->
<div id=free></div>free<br><pre>
Date,     Time,      Memtotal,     used,     free,   shared,buf/cache,available,swap_total,swap_used,swap_free
01/01/26, 00:00:05, 16000, 1000, 14000, 50, 1000, 14000, 0, 0, 0
</pre>
<div id=iostat></div>iostat<br><pre>
Linux 4.18.0 (host) \t01/01/2026 \t_x86_64_\t(4 CPU)
01/01/2026 00:00:05
avg-cpu:  %user   %nice %system %iowait  %steal   %idle
          20.85    0.31    1.58    2.27    0.00   74.99
Device            r/s     w/s     rkB/s     wkB/s   rrqm/s   wrqm/s  %rrqm  %wrqm r_await w_await aqu-sz rareq-sz wareq-sz  svctm  %util
sda              0.56   19.78     12.97   1035.70     0.16     2.18  22.11   9.93    0.30    0.10   0.00    23.27    52.37   0.03   0.20
dm-7             1.00    2.00      3.00      4.00     0.00     0.00   0.00   0.00    0.10    0.10   0.00     3.00     2.00   0.05   0.10
<div id=loadaverage></div>loadaverage<br><pre>
TAIL LINE THAT MUST NEVER BE PARSED
""" + ("PADDING LINE\n" * 200)


def _write(tmp_path, content, name="synth.html"):
    p = tmp_path / name
    p.write_text(content, encoding="ISO-8859-1")
    return str(p)


def _extract(path, force_full_scan):
    return extract_sections(
        operating_system="Linux",
        input_file=path,
        include_iostat=True,
        include_nfsiostat=False,
        html_filename="synth.html",
        disk_list=[],
        force_full_scan=force_full_scan,
    )


def test_ranges_found_and_ordered(tmp_path):
    path = _write(tmp_path, SYNTH)
    markers = ["<!-- beg_mgstat -->", "<!-- beg_vmstat -->", "div id=free", "div id=iostat"]
    ranges = build_section_ranges(path, markers)
    assert ranges is not None
    starts = [r[0] for r in ranges]
    assert starts == sorted(starts)
    assert ranges[0][0] == 0  # header range always included
    for start, end in ranges:
        assert start < end


def test_read_ranges_yields_line_aligned(tmp_path):
    path = _write(tmp_path, SYNTH)
    markers = ["<!-- beg_mgstat -->"]
    ranges = build_section_ranges(path, markers)
    lines = list(read_ranges(path, ranges))
    # every yielded chunk is a complete line
    assert all(l.endswith("\n") or l == lines[-1] for l in lines)
    assert any("beg_mgstat" in l for l in lines)


def test_seek_equals_full_scan(tmp_path):
    """The load-bearing test: seeking and full scan produce identical DataFrames."""
    path = _write(tmp_path, SYNTH)
    dfs_seek = _extract(path, force_full_scan=False)
    dfs_full = _extract(path, force_full_scan=True)
    for seek_df, full_df in zip(dfs_seek, dfs_full):
        assert seek_df.equals(full_df), f"seek/full mismatch:\n{seek_df}\nvs\n{full_df}"
    mgstat_df = dfs_seek[0]
    assert mgstat_df["Glorefs"].tolist() == [100, 200]
    iostat_df = dfs_seek[2]
    assert set(iostat_df["Device"]) == {"sda", "dm-7"}


def test_missing_marker_falls_back(tmp_path, capsys):
    """File without vmstat begin marker: map is unreliable, full scan must engage
    and produce the same output as force_full_scan."""
    broken = SYNTH.replace("<!-- beg_vmstat -->", "")
    path = _write(tmp_path, broken)
    dfs_seek = _extract(path, force_full_scan=False)
    dfs_full = _extract(path, force_full_scan=True)
    for seek_df, full_df in zip(dfs_seek, dfs_full):
        assert seek_df.equals(full_df)
    assert "full scan" in capsys.readouterr().out.lower()


def test_marker_straddles_chunk_boundary(tmp_path):
    """A marker split across two read chunks must still be found."""
    # Position beg_mgstat so it straddles a 1024-byte chunk boundary
    prefix_len = 1024 - len("<!-- beg_mg")
    filler = "x" * (prefix_len - 1) + "\n"
    content = filler + SYNTH
    path = _write(tmp_path, content)
    markers = ["<!-- beg_mgstat -->"]
    ranges = build_section_ranges(path, markers, chunk_size=1024)
    assert ranges is not None
    lines = list(read_ranges(path, ranges))
    assert any("beg_mgstat" in l for l in lines)


def test_disk_list_filters_devices(tmp_path):
    path = _write(tmp_path, SYNTH)
    dfs = extract_sections(
        operating_system="Linux",
        input_file=path,
        include_iostat=True,
        include_nfsiostat=False,
        html_filename="synth.html",
        disk_list=["dm-7"],
    )
    iostat_df = dfs[2]
    assert set(iostat_df["Device"]) == {"dm-7"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_section_seek.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_section_ranges'`.

- [ ] **Step 3: Implement `build_section_ranges` and `read_ranges`**

Add to `extract_sections.py`, after `get_last_needed_section` (before `extract_sections`):

```python
def build_section_ranges(input_file, needed_markers, chunk_size=4 * 1024 * 1024):
    """Chunk-scan the file for section start markers and generic 'div id='/'<div '
    boundaries. Return ascending, line-aligned, non-overlapping [start, end) byte
    ranges covering (a) the header (byte 0 up to the first boundary) and (b) each
    needed section up to and including the line of the next boundary after it.

    Returns None whenever the map cannot be trusted (any needed marker missing,
    unreadable file, or a marker whose line start cannot be located) — the caller
    must then fall back to a full line-by-line scan. The pre-pass is advisory,
    never authoritative.
    """
    boundary_markers = ["div id=", "<div "]
    overlap = 8192  # keeps line starts and straddling markers findable

    marker_hits = {m: [] for m in needed_markers}  # marker -> [line-aligned abs offset]
    boundary_hits = []  # line-aligned abs offsets of all boundaries

    try:
        with open(input_file, "rb") as fh:
            buffer = b""
            buffer_abs_start = 0  # absolute offset of buffer[0]
            seen = set()  # dedupe hits found twice via the overlap
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                buffer += chunk
                for marker, hits in [(m, marker_hits[m]) for m in needed_markers] + [
                    (b_m, None) for b_m in boundary_markers
                ]:
                    m_bytes = marker.encode("ISO-8859-1")
                    search_from = 0
                    while True:
                        idx = buffer.find(m_bytes, search_from)
                        if idx == -1:
                            break
                        nl = buffer.rfind(b"\n", 0, idx)
                        if nl == -1 and buffer_abs_start > 0:
                            # line start lies before our buffer: map unreliable
                            return None
                        line_start_abs = buffer_abs_start + nl + 1  # nl == -1 -> offset 0
                        key = (marker if hits is not None else "boundary", line_start_abs)
                        if key not in seen:
                            seen.add(key)
                            if hits is not None:
                                hits.append(line_start_abs)
                            else:
                                boundary_hits.append(line_start_abs)
                        search_from = idx + 1
                # keep a tail so markers/line-starts straddling chunks are found
                if len(buffer) > overlap:
                    buffer_abs_start += len(buffer) - overlap
                    buffer = buffer[-overlap:]
            file_size = fh.seek(0, 2)
    except OSError:
        return None

    # Every needed marker must appear at least once
    for marker in needed_markers:
        if not marker_hits[marker]:
            return None

    boundary_hits.sort()

    def next_boundary_after(offset):
        for b in boundary_hits:
            if b > offset:
                return b
        return file_size

    # end = start of the line AFTER the next boundary line, i.e. include the
    # boundary line itself so the parsing loop's own end-detection fires.
    ranges = []
    all_marker_offsets = sorted(off for hits in marker_hits.values() for off in hits)
    header_end = min(all_marker_offsets)
    ranges.append((0, header_end))
    for marker in needed_markers:
        for start in marker_hits[marker]:
            boundary = next_boundary_after(start)
            # include the boundary line itself (so the parsing loop's own
            # end-detection fires) but not the whole next section: the range
            # ends at the first newline after the boundary line start
            end = _end_of_line(input_file, boundary, file_size) if boundary < file_size else file_size
            ranges.append((start, end))

    # merge/validate: ascending, non-overlapping
    ranges.sort()
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    for start, end in merged:
        if start >= end:
            return None
    return merged


def _end_of_line(input_file, line_start, file_size):
    """Absolute offset just past the newline of the line beginning at line_start."""
    with open(input_file, "rb") as fh:
        fh.seek(line_start)
        while True:
            block = fh.read(65536)
            if not block:
                return file_size
            nl = block.find(b"\n")
            if nl != -1:
                return fh.tell() - len(block) + nl + 1


def read_ranges(input_file, ranges, chunk_size=4 * 1024 * 1024):
    """Yield decoded lines (ISO-8859-1, '\n'-terminated like file iteration) from
    the given [start, end) byte ranges only, streaming in chunks."""
    with open(input_file, "rb") as fh:
        for start, end in ranges:
            fh.seek(start)
            remaining = end - start
            partial = b""
            while remaining > 0:
                block = fh.read(min(chunk_size, remaining))
                if not block:
                    break
                remaining -= len(block)
                data = partial + block
                lines = data.split(b"\n")
                partial = lines.pop()
                for raw in lines:
                    yield (raw + b"\n").decode("ISO-8859-1")
            if partial:
                yield partial.decode("ISO-8859-1")
```

- [ ] **Step 4: Wire seeking into `extract_sections`**

In `extract_sections.py`:

1. Change the signature (line 67):

```python
def extract_sections(
    operating_system, input_file, include_iostat, include_nfsiostat, html_filename, disk_list,
    force_full_scan=False,
):
```

2. Immediately after the `_completed = set()` line (line 191), add the marker-list construction and line-source selection:

```python
    # Section-seeking pre-pass: map byte ranges of needed sections so the loop
    # below never touches the (often huge) sections between them. On ANY doubt
    # build_section_ranges returns None and we fall back to the full scan.
    _os_l = (operating_system or "").lower()
    _seek_markers = ["<!-- beg_mgstat -->"]
    if _os_l == "windows":
        _seek_markers.append("id=perfmon")
    elif _os_l == "aix":
        _seek_markers.append("<!-- beg_vmstat -->")
        _seek_markers.append("<div id=sar-d>")
        if include_iostat:
            _seek_markers.append("id=iostat")
    else:  # Linux / Ubuntu / default
        _seek_markers.append("<!-- beg_vmstat -->")
        _seek_markers.append("div id=free")
        if include_iostat:
            _seek_markers.append("id=iostat")
        if include_nfsiostat:
            _seek_markers.append("id=nfsiostat")

    _ranges = None if force_full_scan else build_section_ranges(input_file, _seek_markers)
    if _ranges is not None:
        print("Section seek: reading only needed sections")
        _line_source = read_ranges(input_file, _ranges)
    else:
        print("Section seek unavailable, full scan")
        _line_source = open(input_file, "r", encoding="ISO-8859-1")
```

3. Replace the loop entry (line 193):

```python
    with open(input_file, "r", encoding="ISO-8859-1") as file:
        for line in file:
```

with:

```python
    try:
        for line in _line_source:
```

and at the end of the loop body (after the `if _needed.issubset(_completed): ... break` block), close the source:

```python
    finally:
        if hasattr(_line_source, "close"):
            _line_source.close()
```

(De-indent nothing else: `try:` replaces `with ...:` at the same level, the `for` stays at its current indentation.)

- [ ] **Step 5: Run the new tests and the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS, including `tests/test_early_stop.py` (its `extract_sections` call has no `force_full_scan`, default applies).

- [ ] **Step 6: Golden diff and timing on the reference file**

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test"
rm -f t2_SystemPerformance.sqlite
/usr/bin/time -p python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py \
    -i day1.html -a -x -o t2 2> t2_time.txt
sqlite3 t2_SystemPerformance.sqlite .dump > t2.dump
diff golden_before.dump t2.dump && echo "GOLDEN DIFF CLEAN" && grep real t2_time.txt
```

Expected: `GOLDEN DIFF CLEAN`, stdout shows `Section seek: reading only needed sections`, wall time ≈ 10–15 s. If diff is not clean, stop and debug (superpowers:systematic-debugging) — do not proceed.

- [ ] **Step 7: Commit**

```bash
git add extract_sections.py tests/test_section_seek.py
git commit -m "perf: seek directly to needed sections with full-scan fallback

Chunk-scan pre-pass maps line-aligned byte ranges of needed sections;
the unchanged parsing loop is fed only those lines, skipping ~68MB of
irisstat/EnsQCount content per file. Any missing/malformed marker makes
build_section_ranges return None -> identical full scan as before.
Verified byte-identical sqlite3 .dump on 385MB RHEL reference file."
```

---

### Task 3: Extraction-time CPF disk filtering + `--all-disks` (`yaspe.py`)

**Files:**
- Modify: `yaspe.py` — new helper near `create_overview` (~line 321); `create_sections` signature and body (line 176); `mainline` signature (line 2912) and both `create_sections` call sites (lines 3016, 3080); argparse block (add after the `-d/--disk_list` argument at line 3381); `mainline(...)` invocation (~line 3557)
- Modify: `README.md` — document `--all-disks` and the new default
- Test: `tests/test_extraction_disk_filter.py` (new)

**Interfaces:**
- Consumes: `execute_single_read_query(connection, query)` (exists, `yaspe.py:116`).
- Produces: `get_cpf_auto_disk_list(connection) -> list[str]` — CPF-resolved device names from the `overview` table, e.g. `["dm-18", "dm-17", "dm-7", "dm-8"]`; empty list when no roles stored. `create_sections(..., all_disks=False)`; `mainline(..., all_disks=False)` keyword param; CLI flag `--all-disks`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_extraction_disk_filter.py`:

```python
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe import get_cpf_auto_disk_list


def _make_overview(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id_key INTEGER PRIMARY KEY, field TEXT, value TEXT)")
    for field, value in rows:
        conn.execute("INSERT INTO overview (field, value) VALUES (?, ?)", (field, value))
    conn.commit()
    return conn


def test_auto_list_from_cpf_roles():
    conn = _make_overview([
        ("operating system", "Linux"),
        ("iris disk role Database 0", "dm-18"),
        ("iris disk role Database 1", "dm-17"),
        ("iris disk role Primary Journal", "dm-7"),
        ("iris disk role Alternate Journal", "dm-8"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["dm-18", "dm-17", "dm-7", "dm-8"]


def test_auto_list_dedupes_shared_device():
    conn = _make_overview([
        ("iris disk role Database 0", "dm-18"),
        ("iris disk role Primary Journal", "dm-18"),
        ("iris disk role WIJ", "dm-9"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["dm-18", "dm-9"]


def test_auto_list_empty_without_roles():
    conn = _make_overview([("operating system", "Linux")])
    assert get_cpf_auto_disk_list(conn) == []


def test_auto_list_stops_at_gap_in_database_index():
    # Database 0 present, Database 2 present but Database 1 missing:
    # iteration stops at the gap (matches charting-time behaviour).
    conn = _make_overview([
        ("iris disk role Database 0", "dm-18"),
        ("iris disk role Database 2", "dm-99"),
    ])
    assert get_cpf_auto_disk_list(conn) == ["dm-18"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_extraction_disk_filter.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_cpf_auto_disk_list'`.

- [ ] **Step 3: Implement the helper**

Add to `yaspe.py` directly after `create_overview` (after line ~343):

```python
def get_cpf_auto_disk_list(connection):
    """Devices for IRIS disk roles resolved from the CPF, as stored in the
    overview table by create_overview. Order: Database 0..N, then Primary
    Journal, Alternate Journal, WIJ. Empty list if no roles were stored."""
    devices = []
    i = 0
    while True:
        row = execute_single_read_query(
            connection, f"SELECT * FROM overview WHERE field = 'iris disk role Database {i}';"
        )
        if not row or not row[2]:
            break
        if row[2] not in devices:
            devices.append(row[2])
        i += 1
    for role in ("Primary Journal", "Alternate Journal", "WIJ"):
        row = execute_single_read_query(
            connection, f"SELECT * FROM overview WHERE field = 'iris disk role {role}';"
        )
        if row and row[2] and row[2] not in devices:
            devices.append(row[2])
    return devices
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/test_extraction_disk_filter.py -v`
Expected: all PASS.

- [ ] **Step 5: Thread `all_disks` through and apply the filter in `create_sections`**

1. `create_sections` signature (line 176) — append parameter:

```python
def create_sections(
    connection,
    input_file,
    include_iostat,
    include_nfsiostat,
    html_filename,
    csv_out,
    output_filepath_prefix,
    disk_list,
    csv_date_format,
    all_disks=False,
):
```

2. Inside `create_sections`, right after `operating_system` is read (line 189), compute the effective disk list:

```python
    # Effective iostat disk filter: explicit -d list wins; otherwise filter to
    # CPF-resolved IRIS devices unless --all-disks was given. Non-IRIS files
    # (no CPF roles in overview) keep every device.
    effective_disk_list = disk_list
    if not disk_list and not all_disks and operating_system in ("Linux", "Ubuntu"):
        auto_disk_list = get_cpf_auto_disk_list(connection)
        if auto_disk_list:
            print(f"Auto disk list from CPF (extraction): {auto_disk_list}")
            effective_disk_list = auto_disk_list
```

and pass `effective_disk_list` (not `disk_list`) to `extract_sections` (line 195).

3. `mainline` signature (line 2912) — add keyword param at the end:

```python
    combined_overlay=False,
    all_disks=False,
):
```

4. Both `create_sections` call sites (lines 3016 and 3080) — add the argument:

```python
                    disk_list,
                    csv_date_format,
                    all_disks,
                )
```

5. Argparse — add directly after the `-d/--disk_list` block (line 3387):

```python
    parser.add_argument(
        "--all-disks",
        dest="all_disks",
        help="Store every iostat device in SQLite. Default: when a CPF is found, "
             "only IRIS-related disks (databases, journals, WIJ) are stored.",
        action="store_true",
    )
```

6. `mainline(...)` invocation (~line 3557) — add `all_disks=args.all_disks,` as the final argument (keyword form, after `args.combined_overlay`).

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 7: Verify all three behaviours on the reference file**

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test"
# (a) --all-disks must reproduce the golden dump exactly
rm -f t3all_SystemPerformance.sqlite
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i day1.html -a -x -o t3all --all-disks
sqlite3 t3all_SystemPerformance.sqlite .dump > t3all.dump
diff golden_before.dump t3all.dump && echo "ALL-DISKS GOLDEN DIFF CLEAN"

# (b) default run: only CPF devices, big speedup
rm -f t3_SystemPerformance.sqlite
/usr/bin/time -p python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py \
    -i day1.html -a -x -o t3 2> t3_time.txt
sqlite3 t3_SystemPerformance.sqlite \
    "SELECT COUNT(*), COUNT(DISTINCT Device) FROM iostat; SELECT DISTINCT Device FROM iostat;"
grep real t3_time.txt
ls -lah t3_SystemPerformance.sqlite

# (c) explicit -d list still wins
rm -f t3d_SystemPerformance.sqlite
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i day1.html -a -x -o t3d -d sda
sqlite3 t3d_SystemPerformance.sqlite "SELECT DISTINCT Device FROM iostat;"
```

Expected: (a) `ALL-DISKS GOLDEN DIFF CLEAN`; (b) devices are exactly `dm-18, dm-17, dm-7, dm-8` (~69,120 rows), wall time ≈ 5 s, DB ~10–15 MB; (c) only `sda`.

Also confirm charts still render against the filtered DB:

```bash
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -e t3_SystemPerformance.sqlite -p
ls t3_metrics/iostat/ | head
```

Expected: iostat PNGs exist for the four dm devices, no traceback.

- [ ] **Step 8: Update README**

In `README.md`, in the options/flags section, add a row/paragraph:

```markdown
`--all-disks` — store every iostat device in the SQLite database. By default,
when a CPF file is found in the SystemPerformance HTML, only IRIS-related
disks (database, primary/alternate journal, WIJ devices) are stored, which
makes extraction much faster and databases much smaller. Use `--all-disks`
(or an explicit `-d` list) when you need to investigate non-IRIS devices —
re-running extraction is cheap.
```

- [ ] **Step 9: Commit**

```bash
git add yaspe.py README.md tests/test_extraction_disk_filter.py
git commit -m "feat: filter iostat to CPF-resolved IRIS disks at extraction time

CPF disk-role resolution now feeds extraction, not just charting: default
runs store only database/journal/WIJ devices (72 -> 4 devices, 1.24M -> 69K
iostat rows/day on reference file). --all-disks restores the old behaviour;
explicit -d lists are unchanged. Files without CPF info keep all devices."
```

---

### Task 4: Multi-day column-alignment hardening (`yaspe.py`)

**Files:**
- Modify: `yaspe.py` — new helper after `insert_dict_into_table` (~line 134); call it before each of the seven `to_sql` appends in `create_sections` (lines 200, 217, 234, 252, 270, 287, 304)
- Test: `tests/test_column_alignment.py` (new)

**Interfaces:**
- Consumes: sqlite3 connection as used throughout `yaspe.py`.
- Produces: `align_table_columns(connection, table_name, df) -> None` — adds any DataFrame columns missing from an existing table via `ALTER TABLE ADD COLUMN`; no-op when the table doesn't exist yet.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_column_alignment.py`:

```python
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe import align_table_columns


def test_noop_when_table_missing():
    conn = sqlite3.connect(":memory:")
    df = pd.DataFrame({"a": [1]})
    align_table_columns(conn, "vmstat", df)  # must not raise
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert tables == []


def test_day2_with_new_column_appends():
    """Day 2 gained a column: append must succeed, day-1 rows read back NULL."""
    conn = sqlite3.connect(":memory:")
    day1 = pd.DataFrame({"r": [1, 2], "us": [10, 20]})
    day1.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    day2 = pd.DataFrame({"r": [3], "us": [30], "st": [5]})
    align_table_columns(conn, "vmstat", day2)
    day2.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    rows = conn.execute("SELECT r, us, st FROM vmstat ORDER BY r").fetchall()
    assert rows == [(1, 10, None), (2, 20, None), (3, 30, 5)]


def test_day2_with_dropped_column_appends():
    """Day 2 lost a column: append must succeed, day-2 rows read back NULL."""
    conn = sqlite3.connect(":memory:")
    day1 = pd.DataFrame({"r": [1], "us": [10], "st": [5]})
    day1.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    day2 = pd.DataFrame({"r": [2], "us": [20]})
    align_table_columns(conn, "vmstat", day2)
    day2.to_sql("vmstat", conn, if_exists="append", index=True, index_label="id_key")

    rows = conn.execute("SELECT r, us, st FROM vmstat ORDER BY r").fetchall()
    assert rows == [(1, 10, 5), (2, 20, None)]


def test_added_column_types():
    conn = sqlite3.connect(":memory:")
    day1 = pd.DataFrame({"a": [1]})
    day1.to_sql("t", conn, if_exists="append", index=False)
    day2 = pd.DataFrame({"a": [2], "f": [1.5], "s": ["x"], "i": [7]})
    align_table_columns(conn, "t", day2)
    info = {row[1]: row[2] for row in conn.execute("PRAGMA table_info('t')").fetchall()}
    assert info["f"] == "REAL"
    assert info["s"] == "TEXT"
    assert info["i"] == "INTEGER"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_column_alignment.py -v`
Expected: FAIL with `ImportError: cannot import name 'align_table_columns'`.

- [ ] **Step 3: Implement the helper and wire it in**

Add to `yaspe.py` after `insert_dict_into_table` (~line 134):

```python
def align_table_columns(connection, table_name, df):
    """Before a to_sql append: ALTER TABLE ADD COLUMN for any DataFrame column
    the existing table lacks, so a day with new metrics doesn't abort the
    append ("table X has no column named Y"). Columns the DataFrame lacks are
    harmless — pandas inserts only the DataFrame's own columns and SQLite
    fills the rest with NULL. No-op if the table doesn't exist yet."""
    cursor = connection.cursor()
    cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if cursor.fetchone()[0] == 0:
        return
    existing = {row[1] for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()}
    kind_to_sql = {"i": "INTEGER", "u": "INTEGER", "b": "INTEGER", "f": "REAL"}
    for column in df.columns:
        if column not in existing:
            sql_type = kind_to_sql.get(df[column].dtype.kind, "TEXT")
            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{column}" {sql_type}')
    connection.commit()
```

In `create_sections`, insert the matching call immediately before each `to_sql` line:

```python
        align_table_columns(connection, "mgstat", mgstat_df)
        mgstat_df.to_sql("mgstat", connection, if_exists="append", index=True, index_label="id_key")
```

and likewise: `("vmstat", vmstat_df)` before line 217, `("perfmon", perfmon_df)` before 234, `("iostat", iostat_df)` before 252, `("nfsiostat", nfsiostat_df)` before 270, `("aix_sar_d", aix_sar_d_df)` before 287, `("free_memory", free_df)` before 304.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add yaspe.py tests/test_column_alignment.py
git commit -m "fix: survive column drift when appending multiple days to one SQLite

ALTER TABLE ADD COLUMN for any new DataFrame columns before to_sql append;
missing columns already insert as NULL. A day whose vmstat/iostat gained or
lost columns no longer aborts the multi-day append workflow."
```

---

### Task 5: End-to-end week run, timing summary, malformed-file check

**Files:**
- No source changes expected; produces verification evidence for the PR description.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Full-week append run (the real workflow)**

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test"
rm -f week_SystemPerformance.sqlite
time ( for f in "/Users/moldfiel/projects/all_live_projects/yaspe/test_samples/RHEL 1 week"/*.html; do
    python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i "$f" -a -s -x -o week
done )
sqlite3 week_SystemPerformance.sqlite \
    "SELECT COUNT(*) FROM iostat; SELECT COUNT(DISTINCT Device) FROM iostat; SELECT COUNT(DISTINCT RunDate) FROM mgstat;"
ls -lah week_SystemPerformance.sqlite
```

Expected: 7 distinct dates in mgstat, only the CPF devices in iostat, total wall time well under 2 minutes (baseline ≈ 6.5 min), and every file logs `Section seek: reading only needed sections` and `Auto disk list from CPF (extraction): [...]`.

- [ ] **Step 2: Chart the week DB — outputs must render normally**

```bash
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -e week_SystemPerformance.sqlite -p
ls week_metrics/ && ls week_metrics/iostat/ | head
```

Expected: mgstat/vmstat/iostat chart folders populated, no traceback.

- [ ] **Step 3: Malformed-file fallback on real data**

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test"
# Truncate a copy mid-iostat (~150MB point of the 385MB file)
head -c 150000000 day1.html > truncated.html
rm -f trunc_SystemPerformance.sqlite
python3 /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i truncated.html -a -x -o trunc --all-disks
sqlite3 trunc_SystemPerformance.sqlite "SELECT COUNT(*) FROM mgstat; SELECT COUNT(*) FROM iostat;"
```

Expected: no traceback; mgstat fully populated; iostat contains the rows present before the truncation point. (Whether seek or fallback engages depends on which markers survive truncation — either is acceptable; the requirement is graceful completion.)

- [ ] **Step 3b: Cross-OS seek-vs-fallback equivalence (AIX and Windows samples)**

For one HTML file from each of `test_samples/AIX/` and `test_samples/windows/` (pick the largest in each), run extraction twice into fresh databases — once normally and once with seeking disabled — and diff the dumps. Seeking has no CLI switch, so disable it for the second run via an env-guarded temporary edit-free approach: run a tiny driver that calls `extract_sections` directly, or simply corrupt nothing and instead compare a normal run against a run where `build_section_ranges` is monkeypatched to return `None`:

```bash
cd "/private/tmp/claude-1499724556/-Users-moldfiel-projects-all-live-projects-yaspe/5a45a5f2-bac9-472b-9b20-ba8057bc7e95/scratchpad/perf_test"
python3 - <<'EOF'
import glob, sys
sys.path.insert(0, "/Users/moldfiel/projects/all_live_projects/yaspe")
import extract_sections as es

for sample_dir, os_name in [("AIX", "AIX"), ("windows", "Windows")]:
    files = sorted(glob.glob(f"/Users/moldfiel/projects/all_live_projects/yaspe/test_samples/{sample_dir}/*.html"))
    if not files:
        print(f"no sample for {sample_dir}, skipped"); continue
    f = max(files, key=lambda p: __import__("os").path.getsize(p))
    seek = es.extract_sections(os_name, f, True, False, "x.html", [])
    full = es.extract_sections(os_name, f, True, False, "x.html", [], force_full_scan=True)
    for i, (a, b) in enumerate(zip(seek, full)):
        assert a.equals(b), f"{sample_dir}: DataFrame {i} differs between seek and full scan"
    print(f"{sample_dir}: seek == full scan OK ({f.split('/')[-1]})")
EOF
```

Expected: `AIX: seek == full scan OK` and `windows: seek == full scan OK` (or an explicit skip message if a directory has no HTML files). Any assertion failure: stop and debug with superpowers:systematic-debugging.

- [ ] **Step 4: Compare timings and write the summary**

Collect: Task 0 baseline `real`, Task 1/2/3 `real` values, week-loop total, DB sizes. Put the table in the final PR/branch summary.

- [ ] **Step 5: Verify engine-file sync needs no changes**

```bash
grep -c "\.py" /Users/moldfiel/projects/all_live_projects/yaspe_flask_v1/sync_engine.sh
git -C /Users/moldfiel/projects/all_live_projects/yaspe diff --name-only main | grep "\.py$"
```

Expected: only existing engine files (`yaspe.py`, `extract_sections.py`, `yaspe_utilities.py`) were modified — `ENGINE_FILES` unchanged.

- [ ] **Step 6: Finish the branch**

Use superpowers:finishing-a-development-branch: run the full test suite one final time, then present merge/PR options. After merge to `main`: `bump2version minor` and push per CLAUDE.md.
