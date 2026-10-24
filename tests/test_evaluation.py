import json

import pandas as pd

from src.analysis import analyze_shipments, calculate_kpis
from src.decision_demo import with_demo_context
from src.demo import DEMO_AS_OF, generate_demo_data
from src.evaluation import load_reference_cases, ranking_agreement, run_evaluation


def test_enrichment_preserves_all_v1_kpis():
    raw = generate_demo_data()
    base = analyze_shipments(raw, DEMO_AS_OF)
    enriched = analyze_shipments(with_demo_context(raw), DEMO_AS_OF)
    assert calculate_kpis(base.shipments) == calculate_kpis(enriched.shipments)
    pd.testing.assert_frame_equal(base.issues, enriched.issues)
    assert "shipment_value" not in raw


def test_reference_comparison_coverage_and_sensitivity():
    result = run_evaluation()
    assert result.summary["case_count"] == 9
    assert result.summary["reference_ranked_cases"] == 4
    assert result.summary["comparable_pairs"] == 6
    assert result.summary["concordant_pairs"] == 6
    assert result.summary["disposition_matches"] == 9
    assert len(result.summary["component_rules_with_valid_examples"]) == 5
    assert len(result.summary["component_rules_with_missing_or_invalid_examples"]) == 5
    table = result.weight_sensitivity
    default = table.loc[table["profile"].eq("Current weights")].sort_values("observed_rank").iloc[0]
    value = table.loc[table["profile"].eq("Value emphasis (stress test)")].sort_values("observed_rank").iloc[0]
    assert default["case_name"] == "urgent_low_value"
    assert value["case_name"] == "valuable_with_slack"
    actions = result.action_sensitivity
    expedited = actions.loc[actions["action"].eq("Request expedited handling")]
    assert expedited["estimated_additional_cost_usd"].nunique() == 3
    assert expedited["estimated_delay_hours"].nunique() == 3
    payload = json.loads(result.json_bytes())
    assert "not expert-validated" in payload["summary"]["reference_source"]


def test_zero_pairs_is_not_reported_as_perfect_agreement():
    result = ranking_agreement(pd.DataFrame({"reference_rank": [1], "priority_score": [50]}))
    assert result["comparable_pairs"] == 0
    assert result["pairwise_concordance"] is None


def test_ties_and_reversed_ranking_are_counted():
    result = ranking_agreement(pd.DataFrame({"reference_rank": [1, 2, 3], "priority_score": [10, 10, 20]}))
    assert result["tied_pairs"] == 1
    assert result["discordant_pairs"] == 2
    assert result["pairwise_concordance"] == 1 / 6


def test_reference_labels_exist_in_authored_fixture():
    raw, metadata = load_reference_cases()
    assert raw["reference_rationale"].str.len().gt(20).all()
    assert raw["reference_rank"].notna().sum() == 4
    assert "never computed" in metadata["reference_source"]
