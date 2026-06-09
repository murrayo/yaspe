import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_sections import parse_toc_section_order, get_last_needed_section


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


RHEL_TOC_ORDER = ["irisall", "cpffile", "mgstat", "vmstat", "free", "iostat", "sar-d"]
AIX_TOC_ORDER  = ["irisall", "cpffile", "mgstat", "vmstat", "iostat"]
WIN_TOC_ORDER  = ["irisall", "cpffile", "mgstat", "perfmon"]


def test_last_needed_linux_no_iostat():
    # Default Linux run: needs mgstat, vmstat, free — last in TOC order is free
    result = get_last_needed_section(RHEL_TOC_ORDER, "Linux", include_iostat=False, include_nfsiostat=False)
    assert result == "free"


def test_last_needed_linux_with_iostat():
    # With iostat: also needs iostat — last in TOC order is iostat (sar-d is AIX-only)
    result = get_last_needed_section(RHEL_TOC_ORDER, "Linux", include_iostat=True, include_nfsiostat=False)
    assert result == "iostat"


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


def test_last_needed_returns_none_when_needed_section_absent_from_toc():
    # Older files may have vmstat in TOC but not free — must fall back to full read
    toc_without_free = ["irisall", "cpffile", "mgstat", "linuxinfo", "vmstat"]
    result = get_last_needed_section(toc_without_free, "Linux", include_iostat=False, include_nfsiostat=False)
    assert result is None


def test_early_stop_does_not_lose_data(tmp_path):
    """extract_sections must return the same mgstat rows whether it stops early or reads the whole file."""
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
