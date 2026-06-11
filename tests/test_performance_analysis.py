# tests/test_performance_analysis.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from performance_analysis import IRIS_PERIODS, METRIC_THRESHOLDS, Finding, ChartRequest

def test_iris_periods_count():
    assert len(IRIS_PERIODS) == 9

def test_iris_periods_structure():
    period = IRIS_PERIODS[0]
    assert "name" in period
    assert "start" in period
    assert "end" in period

def test_metric_thresholds_vmstat_keys():
    assert "wa" in METRIC_THRESHOLDS
    assert "r" in METRIC_THRESHOLDS
    assert "us_sy" in METRIC_THRESHOLDS
    assert "si" in METRIC_THRESHOLDS
    assert "so" in METRIC_THRESHOLDS
    assert "b" in METRIC_THRESHOLDS
    assert "sy_pct" in METRIC_THRESHOLDS

def test_metric_thresholds_mgstat_keys():
    assert "Glorefs" in METRIC_THRESHOLDS
    assert "PhyRds" in METRIC_THRESHOLDS
    assert "WDQsz" in METRIC_THRESHOLDS
    assert "Rdratio" in METRIC_THRESHOLDS

def test_finding_dataclass():
    f = Finding(
        metric="wa",
        severity="Yellow",
        observation="wa averaged 12%",
        when="09:00–09:22",
        corroborating=[],
        hypotheses=["hypothesis: storage latency"],
        next_step="Monitor",
        chart_request=None,
    )
    assert f.severity == "Yellow"
    assert f.chart_request is None

def test_chart_request_dataclass():
    import pandas as pd
    cr = ChartRequest(
        metric="wa",
        title="I/O Wait",
        df=pd.DataFrame({"datetime_parsed": [], "metric": []}),
        warn_level=10.0,
        alert_level=20.0,
        shading_spans=[],
        twin_metric=None,
        twin_df=None,
        output_dir="/tmp",
        filename="wa_finding",
    )
    assert cr.warn_level == 10.0
