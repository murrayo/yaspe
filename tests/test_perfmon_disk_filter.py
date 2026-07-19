import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_sections import extract_sections

WIN_HTML = """\
<html><head><title>Test</title></head>
Profile run "test" started by user "u" at 00:00:00 on May 29 2026.
<div id=perfmon></div>perfmon<br><pre>
"(PDH-CSV 4.0) (UTC)(0)","\\\\H\\Memory\\Available MBytes","\\\\H\\PhysicalDisk(0 C:)\\Disk Reads/sec","\\\\H\\PhysicalDisk(1 F:)\\Disk Reads/sec","\\\\H\\PhysicalDisk(_Total)\\Disk Reads/sec","\\\\H\\Processor(_Total)\\% Processor Time"
"05/29/2026 06:30:15.123","1000","5","7","12","55"
"05/29/2026 06:30:45.123","1100","6","8","14","60"
<!-- end_win_perfmon -->
"""


def _write(tmp_path):
    p = tmp_path / "win.html"
    p.write_text(WIN_HTML, encoding="ISO-8859-1")
    return str(p)


def _perfmon_df(path, disk_list):
    dfs = extract_sections(
        operating_system="Windows",
        input_file=path,
        include_iostat=False,
        include_nfsiostat=False,
        html_filename="win.html",
        disk_list=disk_list,
    )
    return dfs[4]  # perfmon_df


def test_no_filter_keeps_all_columns(tmp_path):
    df = _perfmon_df(_write(tmp_path), [])
    disk_cols = [c for c in df.columns if "PhysicalDisk" in c]
    assert len(disk_cols) == 3  # C:, F:, _Total
    assert len(df) == 2


def test_filter_keeps_selected_letter_total_and_nondisk(tmp_path):
    df = _perfmon_df(_write(tmp_path), ["F:"])
    disk_cols = [c for c in df.columns if "PhysicalDisk" in c]
    assert len(disk_cols) == 2  # F: and _Total
    assert any("1_F" in c for c in disk_cols)
    assert all("0_C" not in c for c in disk_cols)
    # non-disk columns untouched
    assert any("Available_MBytes" in c for c in df.columns)
    assert any("Processor_Time" in c for c in df.columns)
    # data still aligned with headers after filtering
    assert len(df) == 2


def test_filter_accepts_bare_letter_case_insensitive(tmp_path):
    df = _perfmon_df(_write(tmp_path), ["f"])
    disk_cols = [c for c in df.columns if "PhysicalDisk" in c]
    assert len(disk_cols) == 2


# Raw header has 6 columns; with -d F: the filtered set is 5 (index 2, the C:
# column, is dropped). The second data row is truncated to 5 fields: >= the
# filtered count but < the raw count. It must NOT be index-filtered (that would
# raise IndexError on keep index 5) — it falls through to the existing
# dict(zip)/dropna handling and is dropped.
WIN_HTML_TRUNCATED = """\
<html><head><title>Test</title></head>
Profile run "test" started by user "u" at 00:00:00 on May 29 2026.
<div id=perfmon></div>perfmon<br><pre>
"(PDH-CSV 4.0) (UTC)(0)","\\\\H\\Memory\\Available MBytes","\\\\H\\PhysicalDisk(0 C:)\\Disk Reads/sec","\\\\H\\PhysicalDisk(1 F:)\\Disk Reads/sec","\\\\H\\PhysicalDisk(_Total)\\Disk Reads/sec","\\\\H\\Processor(_Total)\\% Processor Time"
"05/29/2026 06:30:15.123","1000","5","7","12","55"
"05/29/2026 06:30:45.123","1100","6","8","14"
<!-- end_win_perfmon -->
"""


def test_truncated_row_between_filtered_and_raw_count_does_not_crash(tmp_path):
    p = tmp_path / "win.html"
    p.write_text(WIN_HTML_TRUNCATED, encoding="ISO-8859-1")
    df = _perfmon_df(str(p), ["F:"])  # must not raise IndexError
    # the full-length row survives; the truncated row is dropped by dropna
    assert len(df) == 1
    disk_cols = [c for c in df.columns if "PhysicalDisk" in c]
    assert len(disk_cols) == 2  # F: and _Total
