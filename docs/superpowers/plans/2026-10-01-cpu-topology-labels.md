# CPU Topology Labels and Chart Footnotes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse real CPU topology from Linux SystemPerformance files, tell bare metal from VMs, and label every CPU chart with an accurate count plus a footnote stating what is known and telling the reader to review the true processor architecture.

**Architecture:** `sp_check.py` parses the lscpu / `/proc/cpuinfo` lines inside the `<div id=cpu>` section into `sp_dict` and classifies the host once (`cpu host type`). `sp_dict` already flows into the SQLite `overview` table and the yaspe yaml. A pure function `cpu_topology_text(overview)` in `yaspe_utilities.py` turns those fields into `(title_label, footnote)`. Chart functions in `yaspe.py` gain a `footnote` kwarg rendered below the x axis by two small helpers (matplotlib and Plotly).

**Tech Stack:** Python 3, pytest, matplotlib, plotly, pandas, sqlite3.

**Spec:** `docs/superpowers/specs/2026-10-01-cpu-topology-labels-design.md`

## Global Constraints

- No new `.py` module — `yaspe_flask_v1/sync_engine.sh` is unchanged.
- yaml `CPUs` stays numeric (`system_review.py:101` reads it as a count).
- The user-supplied `subtitle` kwarg is untouched; `footnote` is a separate kwarg defaulting to `""`. With `footnote=""` every chart must render exactly as today.
- Title labels use ASCII `x`; footnotes use `×`.
- Bare metal title labels include sockets: `256 threads (4 sockets x 32 cores x 2 HT)`, `64 physical cores (2 sockets x 32 cores, no HT)`. VM titles omit sockets: `38 vCPUs (VMware)`.
- Every footnote ends with an instruction to review the (true / host) processor architecture before making capacity assumptions.
- Older SQLite files and Windows/AIX/`.mgst` inputs lack the new fields and must fall into the Unknown wording, never raise.
- Baseline: 4 tests in `tests/test_performance_analysis.py` already fail before this work. Do not fix them; just don't add to them.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Newer lscpu output indents fields** (util-linux ≥ 2.34 nests `Thread(s) per core:` under `Model name:` with leading spaces) — parsing must still find them. Pinned in Task 1 (`test_indented_lscpu_fields`).
2. **`CPU(s):` look-alikes** — `On-line CPU(s) list:` and `NUMA node0 CPU(s):` must not set `lscpu cpus`; the name match is exact after stripping. Pinned in Task 1 (`test_cpu_lookalikes_ignored` puts both look-alikes before the real `CPU(s):` line, so first-occurrence-wins alone would not hide a prefix-match bug).
3. **Overview values come back from SQLite as strings** (`"4"`, `"True"`) — `cpu_topology_text` must accept strings. Pinned in Task 3 (`test_string_values_from_sqlite`).
4. **Multi-day SQLite has duplicate overview rows** (one set per appended day) — the reader must take the first occurrence, matching `execute_single_read_query`. Pinned in Task 5 (`test_get_overview_dict_first_occurrence_wins`).
5. **Old SQLite without an `overview` table or without topology fields** — charts must still render with the Unknown label. Pinned in Task 5 (`test_get_overview_dict_missing_table` and `test_chart_vmstat_unknown_topology_label`).

---

## File Structure

| File | Change |
|---|---|
| `sp_check.py` | `_LSCPU_KEYS`, `_parse_cpu_line`, `_finalise_cpu_topology`, `cpu_topology_log_lines`, `cpu_topology_yaml`; hook into `system_check` loop and `build_log` |
| `yaspe_utilities.py` | `cpu_topology_text(overview) -> (label, footnote)` |
| `yaspe.py` | `get_overview_dict`, `_add_png_footnote`, `_add_plotly_footnote`; `footnote` kwarg through chart functions; wire `chart_vmstat`, `chart_perfmon`, `chart_glorefs_cpu` |
| `chart_output.py` | run queue reference label uses `cpu_label` kwarg |
| `system_review.py` | vmstat title uses `cpu_topology_text` built from yaml |
| `tests/test_cpu_topology.py` | new — parsing, overview/yaml text, label/footnote text |
| `tests/test_cpu_footnote_charts.py` | new — footnote rendering and chart wiring |
| `docs/superpowers/specs/2026-10-01-cpu-topology-labels-design.md` | refinements recorded (host type key, extra yaml keys, platform set in `system_check`) |

---

### Task 1: Parse CPU topology in `sp_check.system_check`

**Files:**
- Modify: `sp_check.py` (module-level helpers above `system_check`; loop hook after the `# Linux cpu info` block near line 171; call before `return sp_dict` near line 437)
- Test: `tests/test_cpu_topology.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces `sp_dict` keys (ints unless noted): `lscpu cpus`, `lscpu threads per core`, `lscpu cores per socket`, `lscpu sockets`, `lscpu numa nodes`, `hypervisor vendor` (str), `hypervisor flag` (`True`), `cpu topology source` (`"lscpu"` | `"/proc/cpuinfo"`), `cpu host type` (`"bare metal"` | `"virtual"`; absent when topology unknown). `platform` is set to the hypervisor vendor or `"Bare metal"` only if not already set.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cpu_topology.py`:

```python
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sp_check

HEADER = '<b><font face="Arial" size="4" color="#0000FF"><div id=cpu></div>cpu</font></b><br><pre>\n'
FOOTER = '</pre><p align="right"></p><hr size="4" noshade><b><div id=ipcs></div>ipcs</b><br><pre>\nprocessor\t: 99\n'


def _cpuinfo_block(processor, physical_id, core_id, flags="fpu vme ht"):
    return (
        f"processor\t: {processor}\n"
        "model name\t: Intel(R) Xeon(R) Gold 6448H\n"
        f"physical id\t: {physical_id}\n"
        f"core id\t\t: {core_id}\n"
        f"flags\t\t: {flags}\n\n"
    )


BARE_METAL_LSCPU = (
    "lscpu:\n"
    "Architecture:        x86_64\n"
    "CPU(s):              256\n"
    "On-line CPU(s) list: 0-255\n"
    "Thread(s) per core:  2\n"
    "Core(s) per socket:  32\n"
    "Socket(s):           4\n"
    "NUMA node(s):        4\n"
    "Model name:          Intel(R) Xeon(R) Gold 6448H\n"
    "Virtualization:      VT-x\n"
    "NUMA node0 CPU(s):   0,4,8\n"
    "Flags:               fpu vme de pse tsc ht vmx\n\n"
)

VMWARE_LSCPU = (
    "lscpu:\n"
    "CPU(s):              38\n"
    "On-line CPU(s) list: 0-37\n"
    "Thread(s) per core:  1\n"
    "Core(s) per socket:  19\n"
    "Socket(s):           2\n"
    "NUMA node(s):        2\n"
    "Model name:          Intel(R) Xeon(R) Silver 4216 CPU @ 2.10GHz\n"
    "Hypervisor vendor:   VMware\n"
    "Virtualization type: full\n"
    "NUMA node0 CPU(s):   0-18\n"
    "Flags:               fpu vme ht hypervisor lahf_lm\n\n"
)

AWS_LSCPU = (
    "lscpu:\n"
    "CPU(s):              16\n"
    "Thread(s) per core:  2\n"
    "Core(s) per socket:  8\n"
    "Socket(s):           1\n"
    "NUMA node(s):        1\n"
    "Model name:          Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz\n"
    "Hypervisor vendor:   KVM\n"
    "Virtualization type: full\n"
    "Flags:               fpu vme ht hypervisor lahf_lm\n\n"
)


def _check(tmp_path, body):
    f = tmp_path / "sp.html"
    f.write_text(HEADER + body + FOOTER, encoding="ISO-8859-1")
    return sp_check.system_check(str(f))


def test_bare_metal_lscpu(tmp_path):
    d = _check(tmp_path, BARE_METAL_LSCPU + "/proc/cpuinfo:\n" + _cpuinfo_block(0, 0, 0))
    assert d["lscpu cpus"] == 256
    assert d["lscpu threads per core"] == 2
    assert d["lscpu cores per socket"] == 32
    assert d["lscpu sockets"] == 4
    assert d["lscpu numa nodes"] == 4
    assert d["cpu topology source"] == "lscpu"
    assert d["cpu host type"] == "bare metal"
    assert d["platform"] == "Bare metal"
    assert "hypervisor vendor" not in d
    assert "hypervisor flag" not in d


def test_vmware_lscpu(tmp_path):
    d = _check(tmp_path, VMWARE_LSCPU)
    assert d["lscpu cpus"] == 38
    assert d["lscpu sockets"] == 2
    assert d["lscpu cores per socket"] == 19
    assert d["lscpu threads per core"] == 1
    assert d["hypervisor vendor"] == "VMware"
    assert d["hypervisor flag"] is True
    assert d["cpu host type"] == "virtual"
    assert d["platform"] == "VMware"


def test_aws_kvm_lscpu(tmp_path):
    d = _check(tmp_path, AWS_LSCPU)
    assert d["lscpu cpus"] == 16
    assert d["hypervisor vendor"] == "KVM"
    assert d["cpu host type"] == "virtual"
    assert d["platform"] == "KVM"


def test_cpuinfo_fallback_bare_metal(tmp_path):
    # 2 sockets x 2 cores x 2 threads = 8 processors, no lscpu block
    blocks = "".join(
        _cpuinfo_block(p, physical_id=p % 2, core_id=(p // 2) % 2) for p in range(8)
    )
    d = _check(tmp_path, "/proc/cpuinfo:\n" + blocks)
    assert d["cpu topology source"] == "/proc/cpuinfo"
    assert d["lscpu sockets"] == 2
    assert d["lscpu cores per socket"] == 2
    assert d["lscpu threads per core"] == 2
    assert d["lscpu cpus"] == 8
    assert d["cpu host type"] == "bare metal"


def test_cpuinfo_fallback_hypervisor_flag(tmp_path):
    blocks = "".join(_cpuinfo_block(p, 0, p, flags="fpu hypervisor") for p in range(4))
    d = _check(tmp_path, "/proc/cpuinfo:\n" + blocks)
    assert d["cpu host type"] == "virtual"
    assert "hypervisor vendor" not in d
    assert "platform" not in d  # build_log later defaults to N/A


def test_no_cpu_section_leaves_topology_unknown(tmp_path):
    f = tmp_path / "sp.html"
    f.write_text("<div id=mgstat></div>\nnothing here\n", encoding="ISO-8859-1")
    d = sp_check.system_check(str(f))
    assert "cpu host type" not in d
    assert "lscpu sockets" not in d


def test_cpuinfo_outside_cpu_section_ignored(tmp_path):
    # FOOTER contains "processor : 99" after <div id=ipcs>; it must not be counted
    blocks = "".join(_cpuinfo_block(p, 0, p) for p in range(4))
    d = _check(tmp_path, "/proc/cpuinfo:\n" + blocks)
    assert d["lscpu cpus"] == 4


def test_indented_lscpu_fields(tmp_path):
    body = (
        "lscpu:\n"
        "CPU(s):                  64\n"
        "Model name:              AMD EPYC 7543\n"
        "    Thread(s) per core:  2\n"
        "    Core(s) per socket:  32\n"
        "    Socket(s):           1\n"
        "NUMA:\n"
        "  NUMA node(s):          1\n"
    )
    d = _check(tmp_path, body)
    assert d["lscpu threads per core"] == 2
    assert d["lscpu cores per socket"] == 32
    assert d["lscpu sockets"] == 1
    assert d["lscpu numa nodes"] == 1
    assert d["cpu host type"] == "bare metal"


def test_cpu_lookalikes_ignored(tmp_path):
    body = (
        "lscpu:\n"
        "NUMA node0 CPU(s):   0-18\n"
        "On-line CPU(s) list: 0-37\n"
        "CPU(s):              38\n"
        "Thread(s) per core:  1\n"
        "Core(s) per socket:  19\n"
        "Socket(s):           2\n"
    )
    d = _check(tmp_path, body)
    assert d["lscpu cpus"] == 38


def test_real_rhel_sample_is_vmware():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "test_samples", "RHEL", "trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html",
    )
    if not os.path.exists(path):
        pytest.skip("sample file not present")
    d = sp_check.system_check(path)
    assert d["lscpu cpus"] == 20
    assert d["lscpu sockets"] == 20
    assert d["lscpu cores per socket"] == 1
    assert d["lscpu threads per core"] == 1
    assert d["hypervisor vendor"] == "VMware"
    assert d["cpu host type"] == "virtual"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cpu_topology.py -v`
Expected: FAIL — `KeyError: 'lscpu cpus'` (and similar) on every test except `test_no_cpu_section_leaves_topology_unknown`.

- [ ] **Step 3: Implement**

In `sp_check.py`, add above `def system_check(input_file):`:

```python
_LSCPU_KEYS = {
    "CPU(s)": "lscpu cpus",
    "Thread(s) per core": "lscpu threads per core",
    "Core(s) per socket": "lscpu cores per socket",
    "Socket(s)": "lscpu sockets",
    "NUMA node(s)": "lscpu numa nodes",
}


def _new_cpuinfo_state():
    return {"processors": 0, "physical id": None, "sockets": set(), "cores": set()}


def _parse_cpu_line(line, sp_dict, cpuinfo):
    name, sep, value = line.partition(":")
    if not sep:
        return
    name = name.strip()
    value = value.strip()
    if name in _LSCPU_KEYS:
        if value.isdigit():
            sp_dict.setdefault(_LSCPU_KEYS[name], int(value))
    elif name == "Hypervisor vendor":
        sp_dict.setdefault("hypervisor vendor", value)
    elif name in ("Flags", "flags"):
        if "hypervisor" in value.split():
            sp_dict["hypervisor flag"] = True
    elif name == "processor":
        cpuinfo["processors"] += 1
    elif name == "physical id":
        cpuinfo["physical id"] = value
        cpuinfo["sockets"].add(value)
    elif name == "core id":
        cpuinfo["cores"].add((cpuinfo["physical id"], value))


def _finalise_cpu_topology(sp_dict, cpuinfo):
    lscpu_keys = ("lscpu sockets", "lscpu cores per socket", "lscpu threads per core")
    if all(k in sp_dict for k in lscpu_keys):
        sp_dict["cpu topology source"] = "lscpu"
    elif cpuinfo["processors"] and cpuinfo["sockets"] and cpuinfo["cores"]:
        sockets = len(cpuinfo["sockets"])
        cores = len(cpuinfo["cores"])
        sp_dict["lscpu sockets"] = sockets
        sp_dict["lscpu cores per socket"] = max(1, cores // sockets)
        sp_dict["lscpu threads per core"] = max(1, cpuinfo["processors"] // cores)
        sp_dict.setdefault("lscpu cpus", cpuinfo["processors"])
        sp_dict["cpu topology source"] = "/proc/cpuinfo"
    else:
        return

    if "hypervisor vendor" in sp_dict or sp_dict.get("hypervisor flag"):
        sp_dict["cpu host type"] = "virtual"
        if "platform" not in sp_dict and sp_dict.get("hypervisor vendor"):
            sp_dict["platform"] = sp_dict["hypervisor vendor"]
    else:
        sp_dict["cpu host type"] = "bare metal"
        sp_dict.setdefault("platform", "Bare metal")
```

In `system_check`, next to the other section flags before `with open(...)` (around line 70), add:

```python
    cpu_section = False
    cpuinfo = _new_cpuinfo_state()
```

Inside the `for line in file:` loop, directly after the existing `# Linux cpu info` / `model name` block (around line 175), add:

```python
            if "<div id=cpu>" in line:
                cpu_section = True
            elif "<div id=" in line:
                cpu_section = False
            if cpu_section:
                _parse_cpu_line(line, sp_dict, cpuinfo)
```

Directly before `sp_dict["cpf_databases"] = cpf_databases` (around line 435), add:

```python
    _finalise_cpu_topology(sp_dict, cpuinfo)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cpu_topology.py -v`
Expected: all PASS.

Run: `python3 -m pytest -q`
Expected: only the 4 pre-existing `test_performance_analysis.py` failures.

- [ ] **Step 5: Commit**

```bash
git add sp_check.py tests/test_cpu_topology.py
git commit -m "feat: parse lscpu/cpuinfo topology and detect bare metal vs VM"
```

---

### Task 2: Topology lines in `_overview.txt` and the yaspe yaml

**Files:**
- Modify: `sp_check.py` (new helpers near `build_log`; calls in `build_log` after the `CPUs` lines near line 1405 and after the yaml `CPUs` line near line 1643)
- Test: `tests/test_cpu_topology.py` (append)

**Interfaces:**
- Consumes: Task 1 `sp_dict` keys.
- Produces: `cpu_topology_log_lines(sp_dict) -> str` and `cpu_topology_yaml(sp_dict) -> str` (both `""` when `cpu host type` absent). yaml keys: `CPU host type`, `Hypervisor vendor` (VMs with a vendor), `Sockets`, `Cores per socket`, `Threads per core`, `NUMA nodes` (if known), `Physical cores` (bare metal only), `CPU topology source`. Task 6 reads these yaml keys.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cpu_topology.py`:

```python
BARE = {
    "lscpu cpus": 256, "lscpu sockets": 4, "lscpu cores per socket": 32,
    "lscpu threads per core": 2, "lscpu numa nodes": 4,
    "cpu host type": "bare metal", "cpu topology source": "lscpu",
}
VM = {
    "lscpu cpus": 38, "lscpu sockets": 2, "lscpu cores per socket": 19,
    "lscpu threads per core": 1, "lscpu numa nodes": 2, "hypervisor vendor": "VMware",
    "hypervisor flag": True, "cpu host type": "virtual", "cpu topology source": "lscpu",
}


def test_log_lines_bare_metal():
    assert sp_check.cpu_topology_log_lines(BARE) == (
        "CPU topology     : 4 sockets x 32 cores x 2 threads per core\n"
        "Physical cores   : 128\n"
        "Threads          : 256 (Hyper-Threading enabled)\n"
        "NUMA nodes       : 4\n"
    )


def test_log_lines_bare_metal_no_ht():
    d = dict(BARE, **{"lscpu threads per core": 1, "lscpu cpus": 128})
    out = sp_check.cpu_topology_log_lines(d)
    assert "4 sockets x 32 cores x 1 thread per core\n" in out
    assert "Threads          : 128 (no Hyper-Threading)\n" in out


def test_log_lines_vm():
    assert sp_check.cpu_topology_log_lines(VM) == (
        "CPU topology     : 2 sockets x 19 cores x 1 thread per core "
        "(as presented by VMware, not host physical cores)\n"
        "NUMA nodes       : 2\n"
    )


def test_log_lines_unknown_is_empty():
    assert sp_check.cpu_topology_log_lines({"number cpus": "8"}) == ""
    assert sp_check.cpu_topology_yaml({"number cpus": "8"}) == ""


def test_yaml_bare_metal():
    assert sp_check.cpu_topology_yaml(BARE) == (
        "  CPU host type: bare metal\n"
        "  Sockets: 4\n"
        "  Cores per socket: 32\n"
        "  Threads per core: 2\n"
        "  NUMA nodes: 4\n"
        "  Physical cores: 128\n"
        "  CPU topology source: lscpu\n"
    )


def test_yaml_vm_parses_as_yaml():
    import yaml
    parsed = yaml.safe_load("yaspe:\n  CPUs: 38\n" + sp_check.cpu_topology_yaml(VM))["yaspe"]
    assert parsed["CPUs"] == 38
    assert parsed["CPU host type"] == "virtual"
    assert parsed["Hypervisor vendor"] == "VMware"
    assert parsed["Sockets"] == 2
    assert "Physical cores" not in parsed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cpu_topology.py -v -k "log_lines or yaml"`
Expected: FAIL with `AttributeError: module 'sp_check' has no attribute 'cpu_topology_log_lines'`.

- [ ] **Step 3: Implement**

In `sp_check.py`, add directly above `def build_log(sp_dict):`:

```python
def _threads_word(n):
    return "thread" if n == 1 else "threads"


def cpu_topology_log_lines(sp_dict):
    host_type = sp_dict.get("cpu host type")
    if host_type is None:
        return ""
    sockets = sp_dict["lscpu sockets"]
    cores_per_socket = sp_dict["lscpu cores per socket"]
    threads_per_core = sp_dict["lscpu threads per core"]

    line = (
        f"CPU topology     : {sockets} sockets x {cores_per_socket} cores x "
        f"{threads_per_core} {_threads_word(threads_per_core)} per core"
    )
    if host_type == "virtual":
        vendor = sp_dict.get("hypervisor vendor") or "the hypervisor"
        line += f" (as presented by {vendor}, not host physical cores)"
    out = line + "\n"

    if host_type == "bare metal":
        threads = sp_dict.get("lscpu cpus", sockets * cores_per_socket * threads_per_core)
        ht = "Hyper-Threading enabled" if threads_per_core > 1 else "no Hyper-Threading"
        out += f"Physical cores   : {sockets * cores_per_socket}\n"
        out += f"Threads          : {threads} ({ht})\n"

    if "lscpu numa nodes" in sp_dict:
        out += f"NUMA nodes       : {sp_dict['lscpu numa nodes']}\n"
    return out


def cpu_topology_yaml(sp_dict):
    host_type = sp_dict.get("cpu host type")
    if host_type is None:
        return ""
    out = f"  CPU host type: {host_type}\n"
    if sp_dict.get("hypervisor vendor"):
        out += f"  Hypervisor vendor: {sp_dict['hypervisor vendor'].replace(':', '-')}\n"
    out += f"  Sockets: {sp_dict['lscpu sockets']}\n"
    out += f"  Cores per socket: {sp_dict['lscpu cores per socket']}\n"
    out += f"  Threads per core: {sp_dict['lscpu threads per core']}\n"
    if "lscpu numa nodes" in sp_dict:
        out += f"  NUMA nodes: {sp_dict['lscpu numa nodes']}\n"
    if host_type == "bare metal":
        out += f"  Physical cores: {sp_dict['lscpu sockets'] * sp_dict['lscpu cores per socket']}\n"
    out += f"  CPU topology source: {sp_dict['cpu topology source']}\n"
    return out
```

In `build_log`, the block currently reads:

```python
    else:
        if "number cpus" in sp_dict:
            log += f"CPUs             : {sp_dict['number cpus']}\n"
    log += f"Processor model  : {sp_dict['processor model']}\n"
```

Change it to:

```python
    else:
        if "number cpus" in sp_dict:
            log += f"CPUs             : {sp_dict['number cpus']}\n"
        log += cpu_topology_log_lines(sp_dict)
    log += f"Processor model  : {sp_dict['processor model']}\n"
```

And the yaml block:

```python
    if "number cpus" in sp_dict:
        yaspe_yaml += f"  CPUs: {sp_dict['number cpus']}\n"
```

becomes:

```python
    if "number cpus" in sp_dict:
        yaspe_yaml += f"  CPUs: {sp_dict['number cpus']}\n"
    yaspe_yaml += cpu_topology_yaml(sp_dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cpu_topology.py -v`
Expected: all PASS.

Run on the real sample and eyeball the new lines:

```bash
python3 -c "
import sp_check
d = sp_check.system_check('test_samples/RHEL/trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html')
log, y = sp_check.build_log(d)
print(log[:900]); print(y)
"
```

Expected: `Platform         : VMware`, `CPUs             : 20`, `CPU topology     : 20 sockets x 1 cores x 1 thread per core (as presented by VMware, not host physical cores)`, `NUMA nodes       : 2`; yaml contains `CPU host type: virtual` and `Hypervisor vendor: VMware`.

- [ ] **Step 5: Commit**

```bash
git add sp_check.py tests/test_cpu_topology.py
git commit -m "feat: show CPU topology in overview text and yaspe yaml"
```

---

### Task 3: `cpu_topology_text` label and footnote

**Files:**
- Modify: `yaspe_utilities.py` (append)
- Test: `tests/test_cpu_topology.py` (append)

**Interfaces:**
- Consumes: overview-style dict (values may be `int` or `str`): `lscpu cpus`, `number cpus`, `lscpu sockets`, `lscpu cores per socket`, `lscpu threads per core`, `cpu host type`, `hypervisor vendor`, `cpu topology source`, `processor model`.
- Produces: `cpu_topology_text(overview: dict) -> tuple[str, str]` → `(title_label, footnote)`. Used by Tasks 5 and 6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cpu_topology.py`:

```python
from yaspe_utilities import cpu_topology_text

REVIEW = "Review the processor architecture before making capacity assumptions."

OV_BARE = {
    "lscpu cpus": "256", "number cpus": "256", "lscpu sockets": "4",
    "lscpu cores per socket": "32", "lscpu threads per core": "2",
    "cpu host type": "bare metal", "cpu topology source": "lscpu",
    "processor model": "Intel(R) Xeon(R) Gold 6448H",
}
OV_VMWARE = {
    "lscpu cpus": "38", "lscpu sockets": "2", "lscpu cores per socket": "19",
    "lscpu threads per core": "1", "cpu host type": "virtual", "hypervisor vendor": "VMware",
    "cpu topology source": "lscpu", "processor model": "Intel(R) Xeon(R) Silver 4216 CPU @ 2.10GHz",
}
OV_KVM = {
    "lscpu cpus": "16", "lscpu sockets": "1", "lscpu cores per socket": "8",
    "lscpu threads per core": "2", "cpu host type": "virtual", "hypervisor vendor": "KVM",
    "cpu topology source": "lscpu", "processor model": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
}


def test_text_bare_metal_ht():
    label, foot = cpu_topology_text(OV_BARE)
    assert label == "256 threads (4 sockets x 32 cores x 2 HT)"
    assert foot == (
        "CPU topology (lscpu): bare metal, no hypervisor detected. "
        "4 sockets × 32 physical cores × 2 threads = 256 logical CPUs (Intel(R) Xeon(R) Gold 6448H). "
        "100% = all 256 threads busy. "
        "A Hyper-Threading thread shares a physical core and is not equivalent to a full core. "
        + REVIEW
    )


def test_text_bare_metal_no_ht():
    ov = dict(OV_BARE, **{"lscpu threads per core": "1", "lscpu cpus": "64",
                          "lscpu sockets": "2", "lscpu cores per socket": "32"})
    label, foot = cpu_topology_text(ov)
    assert label == "64 physical cores (2 sockets x 32 cores, no HT)"
    assert "2 sockets × 32 physical cores × 1 thread = 64 logical CPUs" in foot
    assert "100% = all 64 cores busy." in foot
    assert "Hyper-Threading" not in foot
    assert foot.endswith(REVIEW)


def test_text_vmware():
    label, foot = cpu_topology_text(OV_VMWARE)
    assert label == "38 vCPUs (VMware)"
    assert foot == (
        "CPU topology (lscpu): VMware VM. "
        "38 vCPUs presented as 2 sockets × 19 cores × 1 thread — this is VM configuration, not host hardware. "
        "Host CPU model: Intel(R) Xeon(R) Silver 4216 CPU @ 2.10GHz. "
        "Host physical cores, Hyper-Threading and overcommit are not visible from inside the guest. "
        "Review the host architecture and vCenter CPU Ready (%RDY) before making capacity assumptions."
    )


def test_text_kvm():
    label, foot = cpu_topology_text(OV_KVM)
    assert label == "16 vCPUs (KVM)"
    assert foot == (
        "CPU topology (lscpu): KVM VM. 16 vCPUs presented as 8 cores × 2 threads. "
        "On cloud instances each vCPU is typically one hyperthread, not a full core. "
        "Host contention appears as vmstat st (steal). "
        "Review the instance type and host architecture before making capacity assumptions."
    )


def test_text_other_hypervisor_has_no_vcenter_clause():
    ov = dict(OV_VMWARE, **{"hypervisor vendor": "Microsoft"})
    label, foot = cpu_topology_text(ov)
    assert label == "38 vCPUs (Microsoft)"
    assert foot.startswith("CPU topology (lscpu): Microsoft VM.")
    assert "vCenter" not in foot
    assert foot.endswith("Review the host architecture before making capacity assumptions.")


def test_text_virtual_without_vendor():
    ov = dict(OV_VMWARE)
    del ov["hypervisor vendor"]
    label, foot = cpu_topology_text(ov)
    assert label == "38 vCPUs (VM)"
    assert foot.startswith("CPU topology (lscpu): virtual machine, hypervisor not identified.")


def test_text_cpuinfo_source():
    ov = dict(OV_BARE, **{"cpu topology source": "/proc/cpuinfo"})
    _, foot = cpu_topology_text(ov)
    assert foot.startswith("CPU topology (/proc/cpuinfo): bare metal")


def test_text_unknown_with_count():
    label, foot = cpu_topology_text({"number cpus": "256"})
    assert label == "256 logical CPUs"
    assert foot == (
        "CPU topology not available in this file. 256 is the logical CPU count reported by IRIS, "
        "which may be threads or vCPUs. "
        "Review the true processor architecture before making capacity assumptions."
    )


def test_text_unknown_without_count():
    label, foot = cpu_topology_text({})
    assert label == ""
    assert foot == (
        "CPU topology not available in this file. "
        "Review the true processor architecture before making capacity assumptions."
    )


def test_string_values_from_sqlite():
    # SQLite TEXT column returns strings, including None for NULL
    ov = dict(OV_BARE, **{"lscpu numa nodes": None, "hypervisor flag": None})
    label, _ = cpu_topology_text(ov)
    assert label == "256 threads (4 sockets x 32 cores x 2 HT)"


def test_bad_numbers_fall_back_to_unknown():
    ov = dict(OV_BARE, **{"lscpu sockets": "n/a"})
    label, foot = cpu_topology_text(ov)
    assert label == "256 logical CPUs"
    assert foot.startswith("CPU topology not available in this file.")


def test_unknown_processor_model_omitted():
    ov = dict(OV_BARE, **{"processor model": "Unknown Processor"})
    _, foot = cpu_topology_text(ov)
    assert "= 256 logical CPUs. 100%" in foot
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cpu_topology.py -v -k text`
Expected: FAIL with `ImportError: cannot import name 'cpu_topology_text'`.

- [ ] **Step 3: Implement**

Append to `yaspe_utilities.py`:

```python
def _overview_int(overview, key):
    try:
        return int(str(overview.get(key)).strip())
    except (TypeError, ValueError):
        return None


def _threads(n):
    return f"{n} thread" if n == 1 else f"{n} threads"


def cpu_topology_text(overview):
    """Return (title_label, footnote) describing CPU capacity from overview fields."""
    sockets = _overview_int(overview, "lscpu sockets")
    cores_per_socket = _overview_int(overview, "lscpu cores per socket")
    threads_per_core = _overview_int(overview, "lscpu threads per core")
    logical = _overview_int(overview, "lscpu cpus") or _overview_int(overview, "number cpus")
    host_type = overview.get("cpu host type")

    if None in (sockets, cores_per_socket, threads_per_core) or host_type not in ("bare metal", "virtual"):
        if logical is None:
            return "", (
                "CPU topology not available in this file. "
                "Review the true processor architecture before making capacity assumptions."
            )
        return f"{logical} logical CPUs", (
            f"CPU topology not available in this file. {logical} is the logical CPU count reported by IRIS, "
            "which may be threads or vCPUs. "
            "Review the true processor architecture before making capacity assumptions."
        )

    if logical is None:
        logical = sockets * cores_per_socket * threads_per_core
    cores = sockets * cores_per_socket
    source = overview.get("cpu topology source") or "lscpu"
    model = overview.get("processor model") or ""
    if model == "Unknown Processor":
        model = ""

    if host_type == "bare metal":
        model_text = f" ({model})" if model else ""
        topology = (
            f"{sockets} sockets × {cores_per_socket} physical cores × {_threads(threads_per_core)} "
            f"= {logical} logical CPUs{model_text}."
        )
        if threads_per_core > 1:
            label = f"{logical} threads ({sockets} sockets x {cores_per_socket} cores x {threads_per_core} HT)"
            busy = (
                f"100% = all {logical} threads busy. "
                "A Hyper-Threading thread shares a physical core and is not equivalent to a full core."
            )
        else:
            label = f"{cores} physical cores ({sockets} sockets x {cores_per_socket} cores, no HT)"
            busy = f"100% = all {cores} cores busy."
        return label, (
            f"CPU topology ({source}): bare metal, no hypervisor detected. {topology} {busy} "
            "Review the processor architecture before making capacity assumptions."
        )

    vendor = overview.get("hypervisor vendor") or ""
    label = f"{logical} vCPUs ({vendor or 'VM'})"

    if vendor == "KVM":
        return label, (
            f"CPU topology ({source}): KVM VM. {logical} vCPUs presented as "
            f"{cores} cores × {_threads(threads_per_core)}. "
            "On cloud instances each vCPU is typically one hyperthread, not a full core. "
            "Host contention appears as vmstat st (steal). "
            "Review the instance type and host architecture before making capacity assumptions."
        )

    who = f"{vendor} VM" if vendor else "virtual machine, hypervisor not identified"
    model_text = f"Host CPU model: {model}. " if model else ""
    vcenter = " and vCenter CPU Ready (%RDY)" if vendor == "VMware" else ""
    return label, (
        f"CPU topology ({source}): {who}. {logical} vCPUs presented as {sockets} sockets × "
        f"{cores_per_socket} cores × {_threads(threads_per_core)} — this is VM configuration, not host hardware. "
        f"{model_text}"
        "Host physical cores, Hyper-Threading and overcommit are not visible from inside the guest. "
        f"Review the host architecture{vcenter} before making capacity assumptions."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cpu_topology.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add yaspe_utilities.py tests/test_cpu_topology.py
git commit -m "feat: add cpu_topology_text for CPU chart labels and footnotes"
```

---

### Task 4: Footnote rendering in chart functions

**Files:**
- Modify: `yaspe.py` — add `import textwrap` with the stdlib imports at the top; add helpers just above `def _find_peak_60_window` (line ~430); `footnote` kwarg in `simple_chart` (1626), `_create_peak_60_chart` (467), `_create_business_hours_peak_chart` (613), `_create_daily_summary_chart` (740), `_create_heatmap_chart` (786), `_create_5min_avg_chart` (821), `_create_day_overlay_chart` (895), `_create_day_overlay_html` (956), `_create_per_day_bh_peak_charts` (1041), `_maybe_day_overlay_html` (1289), `linked_chart` (1350), `simple_chart_stacked` (1967), `simple_chart_dual_axis_glorefs_cpu` (2294), `linked_chart_dual_axis_glorefs_cpu` (2360). Line numbers are pre-change; search by `def` name.
- Test: `tests/test_cpu_footnote_charts.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_add_png_footnote(fig, footnote: str) -> None`; `_add_plotly_footnote(fig, footnote: str, base_height: int) -> int` (returns the new figure height); `footnote=""` kwarg on all functions listed above. Task 5 passes `footnote=` to `simple_chart`, `simple_chart_stacked`, `linked_chart`, `simple_chart_dual_axis_glorefs_cpu`, `linked_chart_dual_axis_glorefs_cpu`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cpu_footnote_charts.py`:

```python
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaspe

FOOT = "CPU topology (lscpu): test footnote. Review the processor architecture before making capacity assumptions."


def _df(periods=10, freq="1min"):
    times = pd.date_range("2024-01-15 09:00", periods=periods, freq=freq)
    return pd.DataFrame({"datetime_parsed": times, "datetime": times, "metric": np.arange(periods, dtype=float)})


def _capture_png(fn, *args, **kwargs):
    captured = {}

    def fake_savefig(*a, **k):
        import matplotlib.pyplot as plt
        captured["fig_texts"] = [t.get_text() for t in plt.gcf().texts]
        captured["savefig_kwargs"] = k

    with patch("matplotlib.pyplot.savefig", side_effect=fake_savefig), patch("matplotlib.pyplot.close"):
        fn(*args, **kwargs)
    return captured


def test_png_footnote_helper_adds_wrapped_text():
    import matplotlib.pyplot as plt
    fig, _ = plt.subplots()
    yaspe._add_png_footnote(fig, "word " * 100)
    assert len(fig.texts) == 1
    assert "\n" in fig.texts[0].get_text()
    plt.close(fig)


def test_png_footnote_helper_empty_is_noop():
    import matplotlib.pyplot as plt
    fig, _ = plt.subplots()
    yaspe._add_png_footnote(fig, "")
    assert fig.texts == []
    plt.close(fig)


def test_simple_chart_footnote(tmp_path):
    c = _capture_png(yaspe.simple_chart, _df(), "Total CPU", "T", 100, str(tmp_path) + "/", "", footnote=FOOT)
    assert any("test footnote" in t for t in c["fig_texts"])


def test_simple_chart_without_footnote_unchanged(tmp_path):
    c = _capture_png(yaspe.simple_chart, _df(), "Total CPU", "T", 100, str(tmp_path) + "/", "")
    assert not any("footnote" in t for t in c["fig_texts"])


def test_simple_chart_forwards_footnote_to_peak_chart(tmp_path):
    with patch.object(yaspe, "_create_peak_60_chart", return_value=(None, None)) as peak, \
         patch.object(yaspe, "_create_business_hours_peak_chart") as bh:
        _capture_png(yaspe.simple_chart, _df(periods=600), "Total CPU", "T", 100, str(tmp_path) + "/", "",
                     min_max=True, peak_chart=True, business_hours_chart=True, footnote=FOOT)
    assert peak.call_args.kwargs.get("footnote") == FOOT
    assert bh.call_args.kwargs.get("footnote") == FOOT


def test_stacked_chart_footnote_and_tight_bbox(tmp_path):
    times = pd.date_range("2024-01-15 09:00", periods=10, freq="1min")
    df = pd.DataFrame({"datetime_parsed": times, "datetime": times,
                       "sy": np.ones(10), "wa": np.ones(10), "us": np.ones(10)})
    c = _capture_png(yaspe.simple_chart_stacked, df, "sy, wa, us", "T", 100, str(tmp_path) + "/", "", footnote=FOOT)
    assert any("test footnote" in t for t in c["fig_texts"])
    assert c["savefig_kwargs"].get("bbox_inches") == "tight"


def test_plotly_footnote_helper():
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.update_layout(height=650)
    new_height = yaspe._add_plotly_footnote(fig, FOOT, 650)
    assert new_height > 650
    assert fig.layout.height == new_height
    assert any("test footnote" in a.text for a in fig.layout.annotations)
    assert fig.layout.margin.b > 80


def test_plotly_footnote_helper_empty_is_noop():
    import plotly.graph_objects as go
    fig = go.Figure()
    assert yaspe._add_plotly_footnote(fig, "", 650) == 650
    assert len(fig.layout.annotations) == 0


def test_linked_chart_html_footnote(tmp_path):
    captured = {}

    def fake_write_html(self, *a, **k):
        captured["fig"] = self

    with patch("plotly.graph_objects.Figure.write_html", fake_write_html):
        yaspe.linked_chart(_df(), "Total CPU", "T", 100, str(tmp_path) + "/", "", footnote=FOOT)
    fig = captured["fig"]
    assert any("test footnote" in a.text for a in fig.layout.annotations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cpu_footnote_charts.py -v`
Expected: FAIL with `AttributeError: module 'yaspe' has no attribute '_add_png_footnote'`.

- [ ] **Step 3: Add the helpers**

Add `import textwrap` next to `import sys` at the top of `yaspe.py`. Add above `def _find_peak_60_window`:

```python
def _add_png_footnote(fig, footnote):
    if not footnote:
        return
    fig.text(0.5, -0.02, "\n".join(textwrap.wrap(footnote, 180)),
             ha="center", va="top", fontsize=10, color="dimgray")


def _add_plotly_footnote(fig, footnote, base_height):
    if not footnote:
        return base_height
    lines = textwrap.wrap(footnote, 190)
    extra = 16 * len(lines) + 10
    fig.add_annotation(
        text="<br>".join(lines), xref="paper", yref="paper", x=0, y=0,
        xanchor="left", yanchor="top", yshift=-60, align="left", showarrow=False,
        font=dict(size=11, color="dimgray"),
    )
    fig.update_layout(height=base_height + extra, margin=dict(b=70 + extra))
    return base_height + extra
```

The PNG footnote sits below the figure's bottom edge; `bbox_inches="tight"` at save time expands the image to include it, which is why charts saved without it must gain it.

- [ ] **Step 4: Thread `footnote` through the matplotlib charts**

1. `simple_chart`: after `subtitle = kwargs.get("subtitle", "")` add `footnote = kwargs.get("footnote", "")`. Between its main `plt.tight_layout()` and `plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", ...)` add `_add_png_footnote(fig, footnote)`. Add `footnote=footnote` as a keyword argument to each derived-chart call in `simple_chart`: `_create_peak_60_chart(...)`, `_create_business_hours_peak_chart(...)`, `_create_5min_avg_chart(...)`, `_create_daily_summary_chart(...)`, `_create_heatmap_chart(...)`, `_create_day_overlay_chart(...)`, `_create_per_day_bh_peak_charts(...)`. Do **not** add it to `_create_glorefs_peak_chart`.
2. Each of `_create_peak_60_chart`, `_create_business_hours_peak_chart`, `_create_daily_summary_chart`, `_create_heatmap_chart`, `_create_5min_avg_chart`, `_create_day_overlay_chart`: append `footnote=""` as the last parameter of the signature, and add `_add_png_footnote(fig, footnote)` on the line immediately before that function's `plt.savefig(`. (They all already save with `bbox_inches="tight"`.)
3. `_create_per_day_bh_peak_charts`: append `footnote=""` to the signature and pass `footnote=footnote` to its `_create_business_hours_peak_chart(...)` call.
4. `simple_chart_stacked`: add `footnote = kwargs.get("footnote", "")` after the `subtitle` line; immediately before `plt.savefig(` add `_add_png_footnote(fig, footnote)`; change the savefig to
   `plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", format="png", dpi=150, bbox_inches="tight")`.
5. `simple_chart_dual_axis_glorefs_cpu`: add `footnote = kwargs.get("footnote", "")` after the `subtitle` line; immediately before its `plt.savefig(` add `_add_png_footnote(fig, footnote)`; add `bbox_inches="tight",` to that savefig call (after `format="png", dpi=150,`).

- [ ] **Step 5: Thread `footnote` through the Plotly charts**

1. `linked_chart`: after `subtitle = kwargs.get("subtitle", "")` add `footnote = kwargs.get("footnote", "")`.
   - PNG-only branch: after `png_fig.update_layout(...)` add `png_height = _add_plotly_footnote(png_fig, footnote, 500)` and change `scale=2, width=1400, height=500,` in that `write_image` call to `scale=2, width=1400, height=png_height,`.
   - Two-panel branch: after the `fig.update_layout(...)` that sets `height=650`, add `_add_plotly_footnote(fig, footnote, 650)`.
   - The later `if write_png:` branch: same as the PNG-only branch (`png_height = ...`, `height=png_height`).
   - Change the final `_maybe_day_overlay_html(data, column_name, title, max_y, filepath, output_prefix, file_prefix, day_overlay)` to add `footnote=footnote`.
2. `_maybe_day_overlay_html`: append `footnote=""` to the signature; pass `footnote=footnote` to `_create_day_overlay_html(...)`.
3. `_create_day_overlay_html`: append `footnote=""` to the signature; after its `fig.update_layout(...)` (the one with `height=650`) add `_add_plotly_footnote(fig, footnote, 650)`.
4. `linked_chart_dual_axis_glorefs_cpu`: add `footnote = kwargs.get("footnote", "")` after the `subtitle` line; after its `fig.update_layout(...)` add `_add_plotly_footnote(fig, footnote, 650)`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cpu_footnote_charts.py tests/test_chart_subtitle.py -v`
Expected: all PASS.

Run: `python3 -m pytest -q`
Expected: only the 4 pre-existing failures.

- [ ] **Step 7: Commit**

```bash
git add yaspe.py tests/test_cpu_footnote_charts.py
git commit -m "feat: add footnote support below the x axis for PNG and HTML charts"
```

---

### Task 5: Wire labels and footnotes into vmstat, perfmon and Glorefs+CPU charts

**Files:**
- Modify: `yaspe.py` — import; `get_overview_dict` next to `get_chart_title_base`; `chart_vmstat` (~2638), `chart_perfmon` (~2890), `chart_glorefs_cpu` (~2427)
- Test: `tests/test_cpu_footnote_charts.py` (append)

**Interfaces:**
- Consumes: `cpu_topology_text` (Task 3), `footnote` kwarg (Task 4).
- Produces: `get_overview_dict(connection) -> dict[str, str | None]` (first occurrence per field; `{}` if the table is missing).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cpu_footnote_charts.py`:

```python
import sqlite3
from unittest.mock import MagicMock


def _db(overview_rows, with_vmstat=True):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE overview (id INTEGER PRIMARY KEY AUTOINCREMENT, field TEXT NOT NULL, value TEXT)")
    conn.executemany("INSERT INTO overview (field, value) VALUES (?, ?)", overview_rows)
    if with_vmstat:
        times = pd.date_range("2024-01-15 09:00", periods=10, freq="1min")
        df = pd.DataFrame({
            "RunDate": times.strftime("%m/%d/%Y"), "RunTime": times.strftime("%H:%M:%S"),
            "r": np.ones(10), "us": np.full(10, 20.0), "sy": np.full(10, 5.0),
            "wa": np.ones(10), "id": np.full(10, 74.0),
        })
        df.to_sql("vmstat", conn, index=False)
    conn.commit()
    return conn


BARE_ROWS = [
    ("customer", "Acme"), ("operating system", "Linux"), ("processor model", "Intel(R) Xeon(R) Gold 6448H"),
    ("number cpus", "256"), ("lscpu cpus", "256"), ("lscpu sockets", "4"),
    ("lscpu cores per socket", "32"), ("lscpu threads per core", "2"),
    ("cpu host type", "bare metal"), ("cpu topology source", "lscpu"),
]


def test_get_overview_dict_first_occurrence_wins():
    conn = _db([("number cpus", "16"), ("number cpus", "32")], with_vmstat=False)
    assert yaspe.get_overview_dict(conn)["number cpus"] == "16"


def test_get_overview_dict_missing_table():
    conn = sqlite3.connect(":memory:")
    assert yaspe.get_overview_dict(conn) == {}


def _run_vmstat(conn, tmp_path):
    with patch.object(yaspe, "simple_chart") as sc, \
         patch.object(yaspe, "simple_chart_stacked") as st, \
         patch.object(yaspe, "linked_chart") as lc:
        yaspe.chart_vmstat(conn, str(tmp_path) + "/", "", True, False)
    return sc, st, lc


def test_chart_vmstat_bare_metal_labels_and_footnotes(tmp_path):
    sc, st, _ = _run_vmstat(_db(BARE_ROWS), tmp_path)
    stacked_title = st.call_args.args[2]
    assert "256 threads (4 sockets x 32 cores x 2 HT) (Intel(R) Xeon(R) Gold 6448H)" in stacked_title
    assert "bare metal" in st.call_args.kwargs["footnote"]

    calls = {c.args[1]: c for c in sc.call_args_list}
    for col in ("Total CPU", "r", "us", "sy"):
        assert "256 threads (4 sockets x 32 cores x 2 HT)" in calls[col].args[2]
        assert "bare metal" in calls[col].kwargs["footnote"]
    assert calls["wa"].kwargs.get("footnote", "") == ""
    assert "threads" not in calls["wa"].args[2]


def test_chart_vmstat_unknown_topology_label(tmp_path):
    rows = [("customer", "Acme"), ("operating system", "Linux"),
            ("processor model", "Some CPU"), ("number cpus", "8")]
    sc, st, _ = _run_vmstat(_db(rows), tmp_path)
    assert "8 logical CPUs (Some CPU)" in st.call_args.args[2]
    assert st.call_args.kwargs["footnote"].startswith("CPU topology not available in this file. 8 is")


def test_chart_vmstat_html_passes_footnote(tmp_path):
    with patch.object(yaspe, "linked_chart") as lc:
        yaspe.chart_vmstat(_db(BARE_ROWS), str(tmp_path) + "/", "", False, False)
    calls = {c.args[1]: c for c in lc.call_args_list}
    assert "bare metal" in calls["Total CPU"].kwargs["footnote"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cpu_footnote_charts.py -v -k "overview or chart_vmstat"`
Expected: FAIL with `AttributeError: module 'yaspe' has no attribute 'get_overview_dict'`.

- [ ] **Step 3: Implement `get_overview_dict` and the import**

Add near the other local imports at the top of `yaspe.py` (after `import yaspe_combined_overlay`):

```python
from yaspe_utilities import cpu_topology_text
```

Add directly above `def get_chart_title_base(connection):`:

```python
def get_overview_dict(connection):
    try:
        rows = connection.execute("SELECT field, value FROM overview ORDER BY id").fetchall()
    except Error:
        return {}
    overview = {}
    for field, value in rows:
        overview.setdefault(field, value)
    return overview
```

(`Error` is already imported from `sqlite3` at the top of `yaspe.py`.)

- [ ] **Step 4: Wire `chart_vmstat`**

Replace:

```python
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]
    processor = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'processor model';")[2]
```

with:

```python
    overview = get_overview_dict(connection)
    cpu_label, cpu_footnote = cpu_topology_text(overview)
    processor = overview.get("processor model") or ""
```

After the existing AIX block (`processor += f" SMT {aix_cpus}"`), add:

```python
    cpu_title_line = f"\n{cpu_label} ({processor})" if cpu_label else f"\n{processor}"
```

In the stacked chart block, replace `title += f"\n{number_cpus} cores ({processor})"` with `title += cpu_title_line` and add `footnote=cpu_footnote` to the `simple_chart_stacked(...)` call.

In the per-column loop, replace:

```python
            if column_name in ("Total CPU", "r"):
                title = f"{column_name} - {customer}"
                title += f"\n{number_cpus} cores ({processor})"
            else:
                title = f"{column_name} - {customer}"
```

with:

```python
            if column_name in ("Total CPU", "r", "us", "sy"):
                title = f"{column_name} - {customer}{cpu_title_line}"
                column_footnote = cpu_footnote
            else:
                title = f"{column_name} - {customer}"
                column_footnote = ""
```

Add `footnote=column_footnote` to the `simple_chart(...)` call and to both `linked_chart(...)` calls in that loop.

Run `grep -n "number_cpus" yaspe.py` — inside `chart_vmstat` there must be no remaining references.

- [ ] **Step 5: Wire `chart_perfmon`**

Replace:

```python
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]
```

with:

```python
    cpu_label, cpu_footnote = cpu_topology_text(get_overview_dict(connection))
```

Replace:

```python
            if "Total_Processor_Time" in column_name or "Processor_Queue_Length" in column_name:
                title = f"{column_name} - {customer}"
                title += f"\n {number_cpus} cores"
            else:
                title = f"{column_name} - {customer}"
```

with:

```python
            if "Total_Processor_Time" in column_name or "Processor_Queue_Length" in column_name:
                title = f"{column_name} - {customer}"
                if cpu_label:
                    title += f"\n{cpu_label}"
                column_footnote = cpu_footnote
            else:
                title = f"{column_name} - {customer}"
                column_footnote = ""
```

Add `footnote=column_footnote` to the `simple_chart(...)` call and both `linked_chart(...)` calls in that loop.

- [ ] **Step 6: Wire `chart_glorefs_cpu`**

After `title = f"Glorefs and Total CPU - {customer}"` add:

```python
    _, cpu_footnote = cpu_topology_text(get_overview_dict(connection))
```

Add `footnote=cpu_footnote` to the `simple_chart_dual_axis_glorefs_cpu(...)` call and both `linked_chart_dual_axis_glorefs_cpu(...)` calls.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cpu_footnote_charts.py -v`
Expected: all PASS.

Run: `python3 -m pytest -q`
Expected: only the 4 pre-existing failures.

- [ ] **Step 8: Commit**

```bash
git add yaspe.py tests/test_cpu_footnote_charts.py
git commit -m "feat: accurate CPU labels and topology footnotes on CPU charts"
```

---

### Task 6: System review title and run queue label

**Files:**
- Modify: `system_review.py:98-108` and its first `chart_output.chart_vmstat(...)` call plus the two later ones (~lines 125, 157, 191)
- Modify: `chart_output.py:113` and `:136-137`
- Test: `tests/test_cpu_topology.py` (append)

**Interfaces:**
- Consumes: `cpu_topology_text` (Task 3); yaml keys from Task 2.
- Produces: `system_review.yaml_cpu_overview(yaspe_yaml: dict) -> dict` (overview-style dict for `cpu_topology_text`); `chart_output.chart_vmstat` accepts `cpu_label` kwarg.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cpu_topology.py`:

```python
import system_review
from yaspe_utilities import cpu_topology_text as _ctt


def test_yaml_cpu_overview_bare_metal():
    y = {"CPUs": 256, "Processor model": "Intel(R) Xeon(R) Gold 6448H", "CPU host type": "bare metal",
         "Sockets": 4, "Cores per socket": 32, "Threads per core": 2, "CPU topology source": "lscpu"}
    label, _ = _ctt(system_review.yaml_cpu_overview(y))
    assert label == "256 threads (4 sockets x 32 cores x 2 HT)"


def test_yaml_cpu_overview_old_yaml():
    label, _ = _ctt(system_review.yaml_cpu_overview({"CPUs": 16, "Processor model": "X"}))
    assert label == "16 logical CPUs"


def test_run_queue_label_uses_cpu_label():
    import chart_output
    captured = []

    def fake_chart(*args, **kwargs):
        captured.append(kwargs)

    times = pd.date_range("2024-01-15 09:00", periods=5, freq="1min")
    df = pd.DataFrame({"r": [1.0] * 5, "Total CPU": [10.0] * 5}, index=times)
    survey = {"vmstat columns": ["r"]}
    with patch("chart_templates.chart_multi_line", side_effect=fake_chart):
        chart_output.chart_vmstat(df, survey, number_cpus=256,
                                  cpu_label="256 threads (4 sockets x 32 cores x 2 HT)")
    labels = [k.get("extra_horizontal", (0, ""))[1] for k in captured]
    assert "Optimal run queue < 256 threads (4 sockets x 32 cores x 2 HT)" in labels
```

Add `import pandas as pd` and `from unittest.mock import patch` to the top of `tests/test_cpu_topology.py` if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cpu_topology.py -v -k "yaml_cpu_overview or run_queue"`
Expected: FAIL with `AttributeError: module 'system_review' has no attribute 'yaml_cpu_overview'`.

If `test_run_queue_label_uses_cpu_label` fails for a reason other than the label (e.g. `chart_output.chart_vmstat` does not call `chart_templates.chart_multi_line`, or passes `extra_horizontal` positionally), read `chart_output.chart_vmstat` past line 140 and adjust only the patch target / how `captured` reads `extra_horizontal` so the test inspects the real call — do not change the assertion text.

- [ ] **Step 3: Implement `chart_output.py`**

After `number_cpus = kwargs.get("number_cpus", 0)` add:

```python
    cpu_label = kwargs.get("cpu_label", "")
```

Replace:

```python
        if counter == "r" and number_cpus > 0:
            extra_horizontal = (number_cpus, f"Optimal Run Queue less than vCPUs ({number_cpus})")
```

with:

```python
        if counter == "r" and number_cpus > 0:
            label = cpu_label or f"{number_cpus} logical CPUs"
            extra_horizontal = (number_cpus, f"Optimal run queue < {label}")
```

- [ ] **Step 4: Implement `system_review.py`**

Add near the top-level functions (above the function containing line 98):

```python
def yaml_cpu_overview(yaspe_yaml):
    return {
        "number cpus": yaspe_yaml.get("CPUs"),
        "processor model": yaspe_yaml.get("Processor model"),
        "cpu host type": yaspe_yaml.get("CPU host type"),
        "hypervisor vendor": yaspe_yaml.get("Hypervisor vendor"),
        "lscpu sockets": yaspe_yaml.get("Sockets"),
        "lscpu cores per socket": yaspe_yaml.get("Cores per socket"),
        "lscpu threads per core": yaspe_yaml.get("Threads per core"),
        "cpu topology source": yaspe_yaml.get("CPU topology source"),
    }
```

Replace:

```python
    vmstat_title = ""
    number_cpus = 0

    if "yaspe" in site_survey_input:
        number_cpus = site_survey_input["yaspe"]["CPUs"]

        vmstat_title += f"{str(number_cpus)} vCPU"
```

with:

```python
    vmstat_title = ""
    number_cpus = 0
    cpu_label = ""

    if "yaspe" in site_survey_input:
        number_cpus = site_survey_input["yaspe"]["CPUs"]
        cpu_label, _ = yaspe_utilities.cpu_topology_text(yaml_cpu_overview(site_survey_input["yaspe"]))

        vmstat_title += cpu_label
```

(The existing processor-model lines that follow append the model and ` - ` unchanged; the model text already starts with a space, as it did after `vCPU`.)

Add `cpu_label=cpu_label,` to each `chart_output.chart_vmstat(...)` call in this function (the three calls that already pass `number_cpus=number_cpus`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cpu_topology.py -v`
Expected: all PASS.

Run: `python3 -m pytest -q`
Expected: only the 4 pre-existing failures.

- [ ] **Step 6: Commit**

```bash
git add chart_output.py system_review.py tests/test_cpu_topology.py
git commit -m "feat: use CPU topology label in system review titles and run queue line"
```

---

### Task 7: End-to-end check on a real file

**Files:** none modified unless a defect is found.

- [ ] **Step 1: Regenerate charts from the RHEL sample**

```bash
rm -rf /tmp/yaspe_cpu_check && mkdir /tmp/yaspe_cpu_check
cp "test_samples/RHEL/trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html" /tmp/yaspe_cpu_check/
cd /tmp/yaspe_cpu_check && /Users/moldfiel/projects/all_live_projects/yaspe/yaspe.py -i trakprod1svr_MEKKESHLIVETCA_20260430_000000_24hours_5.html -P -o check
```

- [ ] **Step 2: Inspect output**

- `check_overview.txt`: `Platform : VMware`, `CPU topology : 20 sockets x 1 cores x 1 thread per core (as presented by VMware, not host physical cores)`, `NUMA nodes : 2`; everything else identical in shape to `test_samples/RHEL/yaspe_overview.txt`.
- Open the PNG `z_Total CPU.png` and `z_Stacked CPU.png` under the generated `png/` metrics folder (use the Read tool on the image): title second line reads `20 vCPUs (VMware) (Intel(R) Xeon(R) Gold 6132 CPU @ 2.60GHz)`; the grey footnote is fully visible below the x-axis labels and not clipped; no overlap with rotated tick labels.
- Open the HTML `Total CPU.html`: footnote appears under the zoom overview panel, not overlapping the "Drag box here to zoom" axis title.
- A disk or mgstat chart (e.g. `z_Glorefs.png`) has no footnote.

If the footnote overlaps the x-axis title in HTML, increase `yshift` magnitude in `_add_plotly_footnote` (and `margin b` by the same amount); if it clips in PNG, confirm the chart's savefig has `bbox_inches="tight"`. Commit any fix:

```bash
git add yaspe.py
git commit -m "fix: footnote spacing on CPU charts"
```

- [ ] **Step 3: Confirm sync list needs no change**

Run: `git diff main --stat -- '*.py'` (or against the branch base). Expected: only `sp_check.py`, `yaspe_utilities.py`, `yaspe.py`, `chart_output.py`, `system_review.py` and the two new test files — all engine files already in `ENGINE_FILES`, no new module. No `sync_engine.sh` change.

---

## Self-Review Notes

- Spec coverage: parsing (T1), platform (T1), overview/yaml (T2), label + footnote text (T3), footnote rendering on all listed charts incl. derived Total CPU charts and day-overlay HTML (T4), titles on stacked/Total CPU/r/us/sy/perfmon + Glorefs+CPU footnote (T5), run queue + system review (T6), manual check (T7).
- Deliberate spec refinements, reflected in the spec: host classification stored once as `cpu host type`; yaml also carries `CPU host type`, `Hypervisor vendor`, `CPU topology source` so `system_review.py` can build the label; platform fallback lives in `system_check` because `build_log` cannot run on a partial file.
