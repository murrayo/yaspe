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
    assert rq.legend_labels[0] == "Physical cores 128 (above = HT doubling-up): 10.0% of samples above"
    assert rq.legend_labels[1] == ("Threads 256 (above = tasks waiting for any CPU): 2.0% of samples above, "
                                   "peak 300 at 29-Aug 12:38")
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
    assert rq.legend_labels[0] == "Physical cores 128 (off scale, peak 63 = 49%)"
    assert rq.thresholds[0] == (None, "Physical cores 128 (off scale, peak 63 = 49%)")


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
    assert rq.thresholds[1] == (None, "Threads 256 (off scale, peak 130 = 51%)")


def test_insight_zero_peak():
    rq = run_queue_insight(_rq_df([0.0] * 10), BARE_HT)
    assert rq.y_max == 0.0
    assert rq.drawn == [False, False]
    assert rq.legend_labels[0] == "Physical cores 128 (off scale, peak 0 = 0%)"


def test_fmt_pct():
    assert _fmt_pct(0.0) == "0.0%"
    assert _fmt_pct(0.025) == "<0.1%"
    assert _fmt_pct(6.25) == "6.2%"


def test_insight_tiny_percentage():
    df = _rq_df([100.0] * 3999 + [300.0])
    rq = run_queue_insight(df, BARE_HT)
    assert "<0.1% of samples above" in rq.legend_labels[1]


def test_insight_string_r_values():
    rq = run_queue_insight(_rq_df(["10", "200", "x"]), BARE_HT)
    assert rq.peak == 200.0
    assert rq.pct_above == [50.0, 0.0]


def test_insight_non_numeric_r_is_empty():
    rq = run_queue_insight(_rq_df(["x"] * 5), BARE_HT)
    assert rq.lines == [] and rq.thresholds == [] and rq.verdict == ""
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
    assert rq.per_core_label == "r ÷ 128 physical cores"
    assert rq.per_core_y_max == 3.0 * 1.05
    assert rq.per_core_thresholds == [(1.0, "1.0 = r equals 128 physical cores (saturated)"),
                                      (2.0, "2 = all 256 threads busy")]


def test_insight_per_core_line_two_off_scale():
    rq = run_queue_insight(_rq_df([64.0] * 10), BARE_HT)
    assert rq.per_core_y_max == 1.05
    assert rq.per_core_thresholds[1] == (None, "2 = all 256 threads busy (off scale)")


def test_insight_per_core_vmware():
    rq = run_queue_insight(_rq_df([10.0] * 10), VMW)
    assert rq.per_core_label == "r ÷ 38 vCPUs"
    assert rq.per_core_thresholds == [(1.0, "1.0 = r equals 38 vCPUs (saturated)")]
