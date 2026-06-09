# Design: TOC-driven early stop for HTML parsing

**Date:** 2026-06-09
**Status:** Approved

## Problem

`extract_sections.py` reads every line of the input HTML file regardless of which sections are needed. For a typical default run (mgstat + vmstat, no iostat) on a 24-hour RHEL file, the needed data ends around line 44,000 of 614,000 — the remaining 85% of the file (dominated by iostat and sar-d) is scanned but never used. Files of 60–300 MB are common; some reach several hundred MB.

## Approach: TOC-driven early stop

All pButtons/SystemPerformance HTML files include a table of contents in the first ~84 lines listing every section in document order as `<a href=#SECTIONNAME>` anchors. This order is authoritative and consistent across Linux, AIX, and Windows files.

The fix reads the TOC once, determines which section is the last one needed for this run, and breaks out of the main parsing loop as soon as that section's end marker is seen. No seeking, no second pass, no new dependencies.

If the TOC cannot be parsed (unexpected format, older file), the code falls back to the existing full-file read transparently.

## Components

### 1. `parse_toc_section_order(input_file)`

- Opens the file, reads up to 90 lines, closes it.
- Extracts `href=#SECTIONNAME` values in document order using a simple string search.
- Returns a list of anchor names (lowercase), e.g. `['irisall', 'license', 'cpffile', 'mgstat', ..., 'vmstat', 'free', 'iostat', 'sar-d']`.
- Returns `None` if no anchors are found (fallback trigger).

### 2. `get_last_needed_section(toc_order, operating_system, include_iostat, include_nfsiostat)`

Builds the set of sections needed for this run:

| OS | Always needed | With `include_iostat` | With `include_nfsiostat` |
|---|---|---|---|
| Linux / RHEL / Ubuntu | `mgstat`, `vmstat`, `free` | + `iostat`, `sar-d` | + `nfsiostat` |
| AIX | `mgstat`, `vmstat` | + `iostat` | — |
| Windows | `mgstat`, `perfmon` | — | — |

Walks `toc_order` in reverse and returns the first anchor that appears in the needed set. Returns `None` if no match (fallback).

### 3. Early-stop in `extract_sections` parsing loop

End-marker mapping for each stoppable section:

| TOC anchor | End marker |
|---|---|
| `mgstat` | `<!-- end_mgstat -->` |
| `vmstat` | `<!-- end_vmstat -->` |
| `free` | next `<div` after `div id=free` opens |
| `iostat` | next `<div` after `id=iostat` opens |
| `nfsiostat` | `pre>` terminator after `id=nfsiostat` |
| `sar-d` | `</pre><p align=` |
| `perfmon` | `<!-- end_win_perfmon -->` |

Logic added to `extract_sections`:

1. Call `parse_toc_section_order` and `get_last_needed_section` before the file loop.
2. If a stop target is found, track whether that section's end marker has been seen.
3. On seeing the end marker, set a flag and `break` after the current line is fully processed.
4. If `parse_toc_section_order` returns `None`, skip all of the above — loop runs as before.

The existing `continue` guards for `include_iostat is False` and `include_nfsiostat is False` are kept as defence-in-depth.

## Expected impact

| Scenario | Lines read today | Lines read after |
|---|---|---|
| RHEL default (no iostat), 614k lines | 614,000 | ~44,000 (~7%) |
| AIX default (no iostat), 733k lines | 733,000 | ~53,000 (~7%) |
| Windows default, 55k lines | 55,000 | ~30,000 (~55%) |
| Any OS with iostat requested | full file | full file (no change) |

## Files changed

- `extract_sections.py` — add `parse_toc_section_order`, `get_last_needed_section`, and early-stop logic in `extract_sections`

No changes to `yaspe.py` or any other module. The public signature of `extract_sections` is unchanged.

## Fallback behaviour

Any of these conditions disables the optimisation and falls back to full-file read:

- TOC anchors not found in first 90 lines
- None of the needed section names appear in the TOC
- The end marker for the last needed section is never encountered (e.g. truncated file)
