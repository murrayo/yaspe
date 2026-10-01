import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe_utilities import run_queue_lines, run_queue_insight, _fmt_pct

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
    return [(ln.value, ln.kind, ln.noun) for ln in lines]


def test_lines_bare_metal_ht():
    lines = run_queue_lines(BARE_HT)
    assert _summary(lines) == [(128, "cores", "physical cores"), (256, "threads", "threads")]
    assert lines[0].meaning == "every core is busy and Hyper-Threading is sharing cores between tasks"
    assert lines[0].unit == "core"
    assert lines[1].meaning == "tasks are queuing for CPU"
    assert lines[1].unit == "thread"


def test_lines_bare_metal_no_ht():
    lines = run_queue_lines(BARE_NOHT)
    assert _summary(lines) == [(64, "cores", "physical cores")]
    assert lines[0].meaning == "tasks are queuing for CPU"


def test_lines_kvm_with_threads():
    lines = run_queue_lines(KVM)
    assert _summary(lines) == [(8, "presented_cores", "presented cores"), (16, "vcpus", "vCPUs")]
    assert lines[0].meaning == "every core is busy and Hyper-Threading is sharing cores between tasks"
    assert lines[1].unit == "vCPU"


def test_lines_any_vm_with_threads_gets_two_lines():
    # Azure (vendor Microsoft) and vendor-less VMs present 2 threads per core too
    assert _summary(run_queue_lines(dict(KVM, **{"hypervisor vendor": "Microsoft"}))) == [
        (8, "presented_cores", "presented cores"), (16, "vcpus", "vCPUs")]
    no_vendor = {k: v for k, v in KVM.items() if k != "hypervisor vendor"}
    assert [ln.value for ln in run_queue_lines(no_vendor)] == [8, 16]


def test_lines_kvm_one_thread_per_core():
    assert _summary(run_queue_lines(KVM1)) == [(4, "vcpus", "vCPUs")]


def test_lines_vmware():
    lines = run_queue_lines(VMW)
    assert _summary(lines) == [(38, "vcpus", "vCPUs")]
    assert lines[0].unit == "vCPU"


def test_lines_unknown_uses_logical_count():
    lines = run_queue_lines(UNKNOWN)
    assert _summary(lines) == [(32, "logical", "logical CPUs")]
    assert lines[0].unit == "CPU"


def test_lines_no_cpu_count():
    assert run_queue_lines({}) == []
    assert run_queue_lines(None) == []
    assert run_queue_lines({"number cpus": "0"}) == []


def test_lines_int_values_from_sp_dict():
    sp = {"cpu host type": "bare metal", "lscpu sockets": 4, "lscpu cores per socket": 32,
          "lscpu threads per core": 2, "lscpu cpus": 256}
    assert [ln.value for ln in run_queue_lines(sp)] == [128, 256]


def _rq_df(r, **cols):
    times = pd.date_range("2025-08-29 11:00", periods=len(r), freq="1min")
    data = {"datetime_parsed": times, "r": r}
    data.update(cols)
    return pd.DataFrame(data)


def test_insight_pct_above_and_peak():
    df = _rq_df([10.0] * 90 + [200.0] * 8 + [300.0] * 2)
    rq = run_queue_insight(df, BARE_HT)
    assert rq.pct_above == [10.0, 2.0]
    assert rq.peak == 300.0
    assert rq.peak_time == "29-Aug 12:38"
    assert rq.legend_labels[0] == "128 physical cores: above 10.0% of the time"
    assert rq.legend_labels[1] == "256 threads: above 2.0% of the time"
    assert rq.drawn == [True, True]
    assert rq.thresholds == [(128, rq.legend_labels[0]), (256, rq.legend_labels[1])]


def test_insight_peak_time_with_duplicate_index():
    df = _rq_df([1.0, 5.0, 2.0])
    df.index = [0, 0, 1]
    rq = run_queue_insight(df, UNKNOWN)
    assert rq.peak_time == "29-Aug 11:01"


def test_insight_off_scale_at_exactly_half():
    rq = run_queue_insight(_rq_df([64.0] * 10), BARE_HT)
    assert rq.drawn == [True, False]
    assert rq.y_max == 128 * 1.05


def test_insight_off_scale_just_below_half():
    rq = run_queue_insight(_rq_df([63.0] * 10), BARE_HT)
    assert rq.drawn == [False, False]
    assert rq.y_max == 63.0
    assert rq.legend_labels[0] == "128 physical cores: never exceeded (peak 63)"
    assert rq.thresholds[0] == (None, "128 physical cores: never exceeded (peak 63)")


def test_insight_off_scale_just_above_half():
    rq = run_queue_insight(_rq_df([65.0] * 10), BARE_HT)
    assert rq.drawn[0] is True


def test_insight_line_two_drawn_when_it_fits():
    rq = run_queue_insight(_rq_df([250.0] * 10), BARE_HT)
    assert rq.drawn == [True, True]
    assert rq.y_max == 250 * 1.05


def test_insight_line_two_off_scale():
    rq = run_queue_insight(_rq_df([130.0] * 10), BARE_HT)
    assert rq.drawn == [True, False]
    assert rq.thresholds[1] == (None, "256 threads: never exceeded (peak 130)")


def test_insight_zero_peak():
    rq = run_queue_insight(_rq_df([0.0] * 10), BARE_HT)
    assert rq.y_max == 0.0
    assert rq.drawn == [False, False]
    assert rq.legend_labels[0] == "128 physical cores: never exceeded (peak 0)"


def test_fmt_pct():
    assert _fmt_pct(0.0) == "0.0%"
    assert _fmt_pct(0.025) == "<0.1%"
    assert _fmt_pct(6.25) == "6.2%"


def test_insight_tiny_percentage():
    df = _rq_df([100.0] * 3999 + [300.0])
    rq = run_queue_insight(df, BARE_HT)
    assert rq.legend_labels[1] == "256 threads: above <0.1% of the time"


def test_insight_string_r_values():
    rq = run_queue_insight(_rq_df(["10", "200", "x"]), BARE_HT)
    assert rq.peak == 200.0
    assert rq.pct_above == [50.0, 0.0]


def test_insight_non_numeric_r_is_empty():
    rq = run_queue_insight(_rq_df(["x"] * 5), BARE_HT)
    assert rq.lines == [] and rq.thresholds == [] and rq.verdict == "" and rq.footnote == ""
    assert rq.y_max is None and rq.per_core_divisor is None


def test_insight_missing_r_column_is_empty():
    df = pd.DataFrame({"datetime_parsed": pd.date_range("2025-08-29", periods=3, freq="1min"), "us": [1, 2, 3]})
    assert run_queue_insight(df, BARE_HT).thresholds == []


def test_insight_no_cpu_count_is_empty():
    rq = run_queue_insight(_rq_df([10.0] * 5), {})
    assert rq.lines == [] and rq.per_core_divisor is None


def test_insight_per_core_bare_metal_ht():
    rq = run_queue_insight(_rq_df([64.0] * 9 + [384.0]), BARE_HT)
    assert rq.per_core_divisor == 128
    assert rq.per_core_label == "runnable tasks per core"
    assert rq.per_core_y_max == 3.0 * 1.05
    assert rq.per_core_thresholds == [(1.0, "1.0 = one task per core (128 physical cores)"),
                                      (2.0, "2.0 = one task per thread (256 threads)")]


def test_insight_per_core_line_two_off_scale():
    rq = run_queue_insight(_rq_df([64.0] * 10), BARE_HT)
    assert rq.per_core_y_max == 1.05
    assert rq.per_core_thresholds[1] == (None, "2.0 = one task per thread (256 threads, not reached)")


def test_insight_per_core_vmware():
    rq = run_queue_insight(_rq_df([10.0] * 10), VMW)
    assert rq.per_core_label == "runnable tasks per vCPU"
    assert rq.per_core_thresholds == [(1.0, "1.0 = one task per vCPU (38 vCPUs)")]


def _queued(n_queued, r_queued, n_total=100, r_idle=10.0, **cols_queued_idle):
    """r_idle for the first n_total - n_queued samples, r_queued for the rest; extra cols given as (queued, idle)."""
    n_idle = n_total - n_queued
    cols = {k: [v[1]] * n_idle + [v[0]] * n_queued for k, v in cols_queued_idle.items()}
    return _rq_df([r_idle] * n_idle + [r_queued] * n_queued, **cols)


def test_verdict_never_exceeded():
    rq = run_queue_insight(_rq_df([10.0] * 100, **{"Total CPU": [50.0] * 100}), BARE_HT)
    assert rq.verdict == "Here r never went above 128 (peak 10 at 29-Aug 11:00), so there was no CPU queuing."


def test_verdict_rarely_exceeded():
    rq = run_queue_insight(_rq_df([10.0] * 999 + [181.0], **{"Total CPU": [50.0] * 1000}), BARE_HT)
    assert rq.verdict == ("Here r was above 128 for 0.1% of the time (peak 181 at 30-Aug 03:39), "
                          "so CPU queuing was not a problem.")


def test_verdict_without_peak_time():
    df = pd.DataFrame({"r": [10.0] * 100})
    rq = run_queue_insight(df, BARE_HT)
    assert rq.verdict == "Here r never went above 128 (peak 10), so there was no CPU queuing."


def test_explain_bare_metal_ht():
    rq = run_queue_insight(_rq_df([10.0] * 5), BARE_HT)
    assert rq.explain == ("r counts tasks running or waiting for a CPU. "
                          "This server has 128 physical cores (256 threads with Hyper-Threading). "
                          "r above 128 means every core is busy and Hyper-Threading is sharing cores between tasks; "
                          "above 256 means tasks are queuing for CPU.")
    assert rq.footnote == f"{rq.explain} {rq.verdict}"


def test_explain_bare_metal_no_ht():
    rq = run_queue_insight(_rq_df([10.0] * 5), BARE_NOHT)
    assert rq.explain == ("r counts tasks running or waiting for a CPU. This server has 64 physical cores. "
                          "r above 64 means tasks are queuing for CPU.")


def test_explain_kvm_ht():
    rq = run_queue_insight(_rq_df([1.0] * 5), KVM)
    assert rq.explain == ("r counts tasks running or waiting for a CPU. "
                          "This VM has 8 presented cores (16 vCPUs with Hyper-Threading). "
                          "r above 8 means every core is busy and Hyper-Threading is sharing cores between tasks; "
                          "above 16 means tasks are queuing for CPU.")


def test_explain_vmware():
    rq = run_queue_insight(_rq_df([1.0] * 5), VMW)
    assert rq.explain == ("r counts tasks running or waiting for a CPU. This VM has 38 vCPUs. "
                          "r above 38 means tasks are queuing for CPU.")


def test_explain_unknown_topology():
    rq = run_queue_insight(_rq_df([1.0] * 5), UNKNOWN)
    assert rq.explain == ("r counts tasks running or waiting for a CPU. IRIS reports 32 logical CPUs. "
                          "r above 32 means tasks are queuing for CPU.")


def test_verdict_cpu_bound():
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (95.0, 20.0)}), BARE_HT)
    assert rq.verdict == ("Here r was above 128 for 10.0% of the time (peak 200 at 29-Aug 12:30). "
                          "The CPU was about 95% busy at those times: the server was short of CPU.")


def test_verdict_high_r_low_cpu():
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (45.0, 20.0)}), BARE_HT)
    assert rq.verdict == ("Here r was above 128 for 10.0% of the time (peak 200 at 29-Aug 12:30). "
                          "The CPU was only about 45% busy then, so this points to short bursts or tasks "
                          "waiting on each other (locks), not a CPU shortage.")


MIDDLE = ("The CPU was about 56% busy then: every core was in use and Hyper-Threading was absorbing "
          "the extra load. That is normal use of the hardware, but headroom was limited.")


def test_verdict_ht_middle_band():
    # Between the HT point (50% for 2 threads per core) and 80%: all cores busy, HT absorbing load
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (56.0, 20.0)}), BARE_HT)
    assert rq.verdict == f"Here r was above 128 for 10.0% of the time (peak 200 at 29-Aug 12:30). {MIDDLE}"


def test_verdict_ht_middle_band_lower_edge():
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (50.0, 20.0)}), BARE_HT)
    assert "every core was in use" in rq.verdict
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (49.0, 20.0)}), BARE_HT)
    assert "not a CPU shortage" in rq.verdict


def test_verdict_ht_middle_band_four_threads_per_core():
    bare4 = dict(BARE_HT, **{"lscpu threads per core": "4", "lscpu cpus": "512"})
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (30.0, 10.0)}), bare4)
    assert "every core was in use" in rq.verdict


def test_verdict_no_middle_band_without_ht():
    rq = run_queue_insight(_queued(10, 100.0, **{"Total CPU": (56.0, 20.0)}), BARE_NOHT)
    assert "not a CPU shortage" in rq.verdict
    assert "Hyper-Threading" not in rq.verdict


def test_verdict_kvm_middle_band_with_steal():
    rq = run_queue_insight(_queued(10, 12.0, r_idle=2.0, **{"Total CPU": (56.0, 20.0), "st": (12.0, 0.0)}), KVM)
    assert MIDDLE in rq.verdict
    assert rq.verdict.endswith("Steal was about 12% at those times: the host is short of CPU, "
                               "so adding vCPUs alone won't help.")


def test_verdict_kvm_middle_band_low_steal_does_not_ask_for_vcpus():
    rq = run_queue_insight(_queued(10, 12.0, r_idle=2.0, **{"Total CPU": (56.0, 20.0), "st": (1.0, 0.0)}), KVM)
    assert rq.verdict.endswith(MIDDLE)


def test_verdict_us_sy_fallback():
    rq = run_queue_insight(_queued(10, 200.0, us=(80.0, 10.0), sy=(15.0, 5.0)), BARE_HT)
    assert rq.verdict.endswith(" The CPU was about 95% busy at those times: the server was short of CPU.")


def test_verdict_without_cpu_columns():
    rq = run_queue_insight(_queued(10, 200.0), BARE_HT)
    assert rq.verdict == "Here r was above 128 for 10.0% of the time (peak 200 at 29-Aug 12:30)."


def test_verdict_both_lines_exceeded():
    # Both reference lines are quoted directly; no derived "between the lines" percentage
    df = _rq_df([10.0] * 90 + [200.0] * 8 + [300.0] * 2, **{"Total CPU": [20.0] * 90 + [95.0] * 10})
    rq = run_queue_insight(df, BARE_HT)
    assert rq.verdict == ("Here r was above 128 for 10.0% of the time and above 256 for 2.0% "
                          "(peak 300 at 29-Aug 12:38). "
                          "The CPU was about 95% busy at those times: the server was short of CPU.")


def test_verdict_second_line_not_exceeded_is_not_mentioned():
    rq = run_queue_insight(_queued(10, 200.0, **{"Total CPU": (95.0, 20.0)}), BARE_HT)
    assert "and above 256" not in rq.verdict


def test_verdict_single_line_topology():
    rq = run_queue_insight(_queued(10, 100.0, **{"Total CPU": (95.0, 20.0)}), BARE_NOHT)
    assert rq.verdict.startswith("Here r was above 64 for 10.0% of the time (peak 100 at 29-Aug 12:30). ")
    assert "and above" not in rq.verdict


def test_verdict_kvm_steal_high():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0), "st": (12.0, 0.0)}), KVM)
    assert rq.verdict.endswith(" Steal was about 12% at those times: the host is short of CPU, "
                               "so adding vCPUs alone won't help.")


def test_verdict_kvm_steal_low_cpu_bound():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0), "st": (1.0, 0.0)}), KVM)
    assert rq.verdict.endswith(" Steal was low, so this VM needs more vCPUs.")


def test_verdict_kvm_steal_low_not_cpu_bound():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (40.0, 20.0), "st": (1.0, 0.0)}), KVM)
    assert "Steal" not in rq.verdict


def test_verdict_kvm_without_st_column():
    rq = run_queue_insight(_queued(10, 20.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), KVM)
    assert "Steal" not in rq.verdict


def test_verdict_vmware_rdy():
    rq = run_queue_insight(_queued(10, 50.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), VMW)
    assert rq.verdict.endswith("VMware hides steal from inside the VM; check CPU Ready (%RDY) in vCenter "
                               "for these times.")


def test_verdict_unknown_topology():
    rq = run_queue_insight(_queued(10, 50.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), UNKNOWN)
    assert rq.verdict == ("Here r was above 32 for 10.0% of the time (peak 50 at 29-Aug 12:30). "
                          "The CPU was about 95% busy at those times: the server was short of CPU.")


def test_verdict_vendor_without_topology_is_unknown():
    overview = {"number cpus": "32", "cpu host type": "virtual", "hypervisor vendor": "VMware"}
    rq = run_queue_insight(_queued(10, 50.0, r_idle=2.0, **{"Total CPU": (95.0, 20.0)}), overview)
    assert "%RDY" not in rq.verdict
