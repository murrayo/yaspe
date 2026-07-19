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
    for seek_df, full_df in zip(dfs_seek, dfs_full, strict=True):
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


def test_empty_marker_list_returns_none(tmp_path):
    """No markers to seek for: the map cannot be trusted, must return None."""
    path = _write(tmp_path, SYNTH)
    assert build_section_ranges(path, []) is None


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
