import os
import sys

import pytest
import pandas as pd
from unittest.mock import patch

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


# --- Final review fixes ---

def test_singular_core_and_socket_wording():
    ov = {"lscpu cpus": "20", "lscpu sockets": "20", "lscpu cores per socket": "1",
          "lscpu threads per core": "1", "cpu host type": "virtual", "hypervisor vendor": "VMware",
          "cpu topology source": "lscpu"}
    _, foot = cpu_topology_text(ov)
    assert "20 vCPUs presented as 20 sockets × 1 core × 1 thread —" in foot

    ov = dict(OV_BARE, **{"lscpu sockets": "1", "lscpu cores per socket": "8", "lscpu cpus": "16"})
    label, foot = cpu_topology_text(ov)
    assert label == "16 threads (1 socket x 8 cores x 2 HT)"
    assert "1 socket × 8 physical cores × 2 threads" in foot

    d = dict(VM, **{"lscpu sockets": 20, "lscpu cores per socket": 1})
    assert sp_check.cpu_topology_log_lines(d).startswith(
        "CPU topology     : 20 sockets x 1 core x 1 thread per core")


def test_vmstat_cpu_title_spacing():
    y = {"CPUs": 18, "Processor model": "AMD EPYC 7502P 32-Core Processor", "CPU host type": "virtual",
         "Hypervisor vendor": "VMware", "Sockets": 18, "Cores per socket": 1, "Threads per core": 1}
    assert system_review.vmstat_cpu_title(y) == "18 vCPUs (VMware) AMD EPYC 7502P 32-Core Processor - "
    y = {"CPUs": 16, "Processor model": "Intel(R) Xeon(R) Gold 6132 CPU @ 2.60GHz"}
    assert system_review.vmstat_cpu_title(y) == "16 logical CPUs Gold 6132 CPU @ 2.60GHz - "


def test_hypervisor_vendor_sets_platform_without_topology(tmp_path):
    body = "lscpu:\nCPU(s):              4\nSocket(s):           -\nHypervisor vendor:   KVM\n"
    d = _check(tmp_path, body)
    assert "cpu host type" not in d
    assert d["platform"] == "KVM"
