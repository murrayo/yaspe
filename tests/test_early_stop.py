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
