"""Reproducible V1/V2 comparisons against independently authored synthetic references."""

import argparse
from dataclasses import dataclass, replace
import itertools
import json
from pathlib import Path

import pandas as pd

from src.analysis import analyze_shipments
from src.decisions import ActionAssumption, compare_actions, default_assumptions
from src.priority import COMPONENTS, PriorityConfig, delivery_deadline, prioritize_shipments

REFERENCE_FILE = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "reference_cases.json"


@dataclass
class EvaluationResult:
    summary: dict
    comparison: pd.DataFrame
    weight_sensitivity: pd.DataFrame
    action_sensitivity: pd.DataFrame

    def json_bytes(self) -> bytes:
        result = {"summary": self.summary}
        for name in ("comparison", "weight_sensitivity", "action_sensitivity"):
            result[name] = json.loads(getattr(self, name).to_json(orient="records"))
        return json.dumps(result, indent=2, allow_nan=False).encode("utf-8")


def load_reference_cases(path: Path = REFERENCE_FILE) -> tuple[pd.DataFrame, dict]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame([{**metadata["base_shipment"], **case} for case in metadata["cases"]]), metadata


def ranking_agreement(comparison: pd.DataFrame) -> dict:
    ranked = comparison.dropna(subset=["reference_rank", "priority_score"])
    concordant = discordant = tied = 0
    for (_, first), (_, second) in itertools.combinations(ranked.iterrows(), 2):
        reference = second["reference_rank"] - first["reference_rank"]
        if reference == 0:
            continue
        predicted = first["priority_score"] - second["priority_score"]
        if predicted == 0:
            tied += 1
        elif predicted * reference > 0:
            concordant += 1
        else:
            discordant += 1
    pairs = concordant + discordant + tied
    return {"comparable_pairs": pairs, "concordant_pairs": concordant, "discordant_pairs": discordant,
            "tied_pairs": tied, "pairwise_concordance": (concordant + 0.5 * tied) / pairs if pairs else None,
            "reference_ranked_cases": int(comparison["reference_rank"].notna().sum()),
            "scored_reference_cases": len(ranked)}


def run_evaluation(config: PriorityConfig | None = None) -> EvaluationResult:
    config = config or PriorityConfig.load()
    raw, metadata = load_reference_cases()
    baseline = analyze_shipments(raw, metadata["as_of"])
    ranked = prioritize_shipments(baseline.shipments, baseline.cutoff, config)
    comparison = ranked[["case_name", "shipment_id", "is_exception", "exception_types", "reference_rank",
                         "reference_disposition", "priority_score", "priority_level", "coverage_percent",
                         "missing_information", "reference_rationale"]].copy()
    comparison["observed_disposition"] = comparison["priority_level"].replace({"High": "Scored", "Medium": "Scored", "Low": "Scored"})
    comparison["reference_disposition_matches"] = comparison["observed_disposition"].eq(comparison["reference_disposition"])
    known_components, missing_components = set(), set()
    for details in ranked["priority_details_json"]:
        parsed = json.loads(details)
        for component, value in parsed.get("components", {}).items():
            (missing_components if value is None else known_components).add(component)
    sensitivity = []
    profiles = {
        "Current weights": config,
        "Urgency emphasis": replace(config, weights=dict(zip(COMPONENTS, (70, 10, 10, 5, 5)))),
        "Financial emphasis": replace(config, weights=dict(zip(COMPONENTS, (10, 10, 70, 5, 5)))),
        "Value emphasis (stress test)": replace(config, weights=dict(zip(COMPONENTS, (5, 5, 5, 80, 5)))),
    }
    for profile, settings in profiles.items():
        table = prioritize_shipments(baseline.shipments, baseline.cutoff, settings)
        table["observed_rank"] = table["priority_score"].rank(ascending=False, method="min")
        for row in table.to_dict("records"):
            sensitivity.append({"profile": profile, "case_name": row["case_name"], "priority_score": row["priority_score"],
                                "observed_rank": row["observed_rank"], "priority_level": row["priority_level"],
                                "weights_json": json.dumps(settings.weights)})
    actions = []
    # Assumption sensitivity uses one explicitly named fictional case, not an inferred ETA.
    case = baseline.shipments.loc[baseline.shipments["case_name"].eq("next_shift")].iloc[0]
    deadline, _ = delivery_deadline(case)
    for wait_hours, expedite_cost, expedite_hours in ((96, 250, 48), (120, 500, 72), (72, 400, 8)):
        options = default_assumptions()
        options[0] = ActionAssumption(options[0].action, 0.0, float(wait_hours))
        options[1] = ActionAssumption(options[1].action, float(expedite_cost), float(expedite_hours))
        table = compare_actions(baseline.cutoff, deadline, options)
        table["scenario"] = f"wait={wait_hours}h, expedited={expedite_hours}h/${expedite_cost}"
        table["case_name"] = "next_shift"
        actions.extend(table.to_dict("records"))
    summary = {
        "reference_source": metadata["reference_source"], "analysis_date": metadata["as_of"],
        "case_count": len(raw), "v1_exception_rows": int(comparison["is_exception"].sum()),
        **ranking_agreement(comparison),
        "disposition_matches": int(comparison["reference_disposition_matches"].sum()),
        "disposition_cases": len(comparison),
        "component_rules_with_valid_examples": sorted(known_components),
        "component_rules_with_missing_or_invalid_examples": sorted(missing_components),
        "rule_coverage_definition": "Presence of valid and missing/invalid fixture examples per component, not code coverage or predictive accuracy.",
        "warning": "Synthetic ordinal consistency only. No real-world prediction accuracy, carrier capability or validated loss estimate is established.",
        "config": config.to_dict(),
    }
    return EvaluationResult(summary, comparison, pd.DataFrame(sensitivity), pd.DataFrame(actions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="artifacts/evaluation")
    args = parser.parse_args()
    result = run_evaluation()
    target = Path(args.output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "evaluation.json").write_bytes(result.json_bytes())
    for name in ("comparison", "weight_sensitivity", "action_sensitivity"):
        getattr(result, name).to_csv(target / (name + ".csv"), index=False)
    print(json.dumps(result.summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
