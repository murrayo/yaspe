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
