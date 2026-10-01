import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe_utilities import run_queue_lines

BARE_HT = {"cpu host type": "bare metal", "lscpu sockets": "4", "lscpu cores per socket": "32",
           "lscpu threads per core": "2", "lscpu cpus": "256"}
BARE_NOHT = {"cpu host type": "bare metal", "lscpu sockets": "2", "lscpu cores per socket": "32",
             "lscpu threads per core": "1", "lscpu cpus": "64"}
KVM = {"cpu host type": "virtual", "hypervisor vendor": "KVM", "lscpu sockets": "1",
       "lscpu cores per socket": "8", "lscpu threads per core": "2", "lscpu cpus": "16"}
KVM1 = {"cpu host type": "virtual", "hypervisor vendor": "KVM", "lscpu sockets": "1",
        "lscpu cores per socket": "4", "lscpu threads per core": "1", "lscpu cpus": "4"}
VMW = {"cpu host type": "virtual", "hypervisor vendor": "VMware", "lscpu sockets": "2",
       "lscpu cores per socket": "19", "lscpu threads per core": "1", "lscpu cpus": "38"}
UNKNOWN = {"number cpus": "32"}


def _summary(lines):
    return [(ln.value, ln.kind, ln.label) for ln in lines]


def test_lines_bare_metal_ht():
    lines = run_queue_lines(BARE_HT)
    assert _summary(lines) == [(128, "cores", "Physical cores 128"), (256, "threads", "Threads 256")]
    assert lines[0].meaning == "HT doubling-up"
    assert lines[0].noun == "physical cores"
    assert lines[1].meaning == "tasks waiting for any CPU"


def test_lines_bare_metal_no_ht():
    lines = run_queue_lines(BARE_NOHT)
    assert _summary(lines) == [(64, "cores", "Physical cores 64")]
    assert lines[0].meaning == "tasks waiting for a core"


def test_lines_kvm_with_threads():
    lines = run_queue_lines(KVM)
    assert _summary(lines) == [(8, "presented_cores", "Presented cores 8"), (16, "vcpus", "vCPUs 16")]
    assert lines[0].meaning == "sharing hyperthread pairs"


def test_lines_kvm_one_thread_per_core():
    assert _summary(run_queue_lines(KVM1)) == [(4, "vcpus", "vCPUs 4")]


def test_lines_vmware():
    lines = run_queue_lines(VMW)
    assert _summary(lines) == [(38, "vcpus", "vCPUs 38")]
    assert lines[0].noun == "vCPUs"


def test_lines_unknown_uses_logical_count():
    lines = run_queue_lines(UNKNOWN)
    assert _summary(lines) == [(32, "logical", "Logical CPUs 32")]
    assert lines[0].noun == "logical CPUs"


def test_lines_no_cpu_count():
    assert run_queue_lines({}) == []
    assert run_queue_lines(None) == []
    assert run_queue_lines({"number cpus": "0"}) == []


def test_lines_int_values_from_sp_dict():
    sp = {"cpu host type": "bare metal", "lscpu sockets": 4, "lscpu cores per socket": 32,
          "lscpu threads per core": 2, "lscpu cpus": 256}
    assert [ln.value for ln in run_queue_lines(sp)] == [128, 256]
