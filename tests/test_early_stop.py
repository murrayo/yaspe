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
