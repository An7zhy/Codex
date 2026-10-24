import pytest

from scripts.audit_benchmark import check_kpis, make_workload
from src.analysis import analyze_shipments, calculate_kpis
from src.demo import DEMO_AS_OF
from src.ingestion import load_shipments
from src.priority import prioritize_shipments


@pytest.mark.parametrize("size", [100, 500, 5000])
def test_requested_workload_sizes_match_independent_expected_counts(size):
    raw = make_workload(size)
    loaded = load_shipments(raw.to_csv(index=False).encode(), "synthetic_audit.csv")
    result = analyze_shipments(loaded, DEMO_AS_OF)
    check_kpis(calculate_kpis(result.shipments), size)
    assert result.issues.empty
    priorities = prioritize_shipments(result.shipments, result.cutoff)
    assert priorities["priority_score"].notna().sum() == size // 4
    assert priorities["priority_level"].eq("Insufficient information").sum() == 0
