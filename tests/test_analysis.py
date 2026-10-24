import math

import pandas as pd
import pytest

from src.analysis import analyze_shipments, calculate_kpis, carrier_performance
from src.schema import REQUIRED_COLUMNS

AS_OF = "2026-10-01"


def test_known_operating_snapshot(make_rows):
    data = make_rows({}, {"actual_delivery": "2026-10-01T12:00:00Z"},
                     {"status": "In Transit", "actual_delivery": ""},
                     {"status": "In Transit", "actual_delivery": "", "planned_delivery": "2026-10-05"})
    result = analyze_shipments(data, AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["total_shipments"] == 4
    assert k["delivered_shipments"] == 2
    assert k["eligible_deliveries"] == 2
    assert k["on_time_delivery_rate"] == 0.5
    assert k["average_delay_hours"] == 24
    assert k["overdue_shipments"] == 1
    assert k["total_shipping_cost"] == 400
    assert not (result.shipments["is_delayed"] & result.shipments["is_overdue"]).any()


def test_no_delays_and_early_delivery_are_valid(make_rows):
    result = analyze_shipments(make_rows({}, {"actual_delivery": "2026-09-29"}), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["on_time_delivery_rate"] == 1
    assert k["average_delay_hours"] == 0
    assert k["delayed_shipments"] == 0
    assert result.issues.empty


def test_all_shipments_in_transit_have_no_completed_rate(make_rows):
    result = analyze_shipments(make_rows(*[{"status": "In Transit", "actual_delivery": ""}] * 3), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["delivered_shipments"] == 0
    assert k["overdue_shipments"] == 3
    assert k["on_time_delivery_rate"] is None
    assert k["average_delay_hours"] is None
    assert result.shipments["delay_hours"].isna().all()
    assert result.issues.empty


@pytest.mark.parametrize("invalid", ["nonsense", "01/02/2026", "2026-02-30", "45678", "1999-12-31", "2269-01-01"])
def test_bad_planned_dates_are_reviewable_not_fatal(make_rows, invalid):
    result = analyze_shipments(make_rows({"planned_delivery": invalid}, {}), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["total_shipments"] == 2
    assert k["delivered_shipments"] == 2
    assert k["eligible_deliveries"] == 1
    assert result.issues.iloc[0]["field"] == "planned_delivery"
    assert result.shipments.iloc[0]["planned_delivery_raw"] == invalid


@pytest.mark.parametrize("actual", ["", None, "not-a-date"])
def test_delivered_without_valid_actual_is_unverified(make_rows, actual):
    result = analyze_shipments(make_rows({"actual_delivery": actual}), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["total_shipments"] == 1
    assert k["delivered_shipments"] == 0
    assert k["on_time_delivery_rate"] is None
    assert k["overdue_shipments"] == 0
    assert len(result.issues) == 1


def test_duplicates_are_auditable_and_never_double_counted(make_rows):
    result = analyze_shipments(make_rows({"shipment_id": "SAME", "shipping_cost": 100},
                                        {"shipment_id": "SAME", "shipping_cost": 900}), AS_OF)
    k = calculate_kpis(result.shipments)
    assert len(result.shipments) == 2
    assert k["total_shipments"] == 1
    assert k["total_shipping_cost"] == 100
    assert k["excluded_rows"] == 1
    assert set(result.issues["code"]) == {"duplicate_id", "duplicate_id_retained"}


def test_missing_id_does_not_remove_the_raw_record(make_rows):
    result = analyze_shipments(make_rows({"shipment_id": "  "}), AS_OF)
    assert calculate_kpis(result.shipments)["total_shipments"] == 0
    assert len(result.shipments) == 1
    assert result.shipments.iloc[0]["is_exception"]


def test_empty_table_has_defined_kpis():
    result = analyze_shipments(pd.DataFrame(columns=REQUIRED_COLUMNS), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["total_shipments"] == 0
    assert k["total_shipping_cost"] == 0
    assert k["on_time_delivery_rate"] is None
    assert k["average_delay_hours"] is None
    assert carrier_performance(result.shipments).empty


def test_small_cost_groups_are_not_classified(make_rows):
    result = analyze_shipments(make_rows({}, {}, {"shipping_cost": 1_000_000}), AS_OF)
    assert not result.shipments["is_cost_anomaly"].any()
    assert result.shipments["cost_assessment"].eq("Insufficient data").all()
    assert result.shipments["cost_threshold"].isna().all()


def test_cost_outlier_is_compared_only_to_its_route_and_mode(make_rows):
    records = [{} for _ in range(7)] + [{"shipping_cost": 1000},
               {"transport_mode": "Air", "shipping_cost": 10000},
               {"origin": "Rotterdam, Netherlands", "destination": "Shanghai, China", "shipping_cost": 10000}]
    result = analyze_shipments(make_rows(*records), AS_OF)
    assert calculate_kpis(result.shipments)["cost_anomalies"] == 1
    assert result.shipments.iloc[7]["is_cost_anomaly"]
    assert result.shipments.iloc[7]["cost_group_size"] == 8
    assert result.shipments.iloc[7]["cost_threshold"] == 150
    assert result.shipments.iloc[8:]["cost_assessment"].eq("Insufficient data").all()
    # Reaggregating a filtered view preserves the original comparison group.
    assert calculate_kpis(result.shipments.iloc[[7]])["cost_anomalies"] == 1


def test_cost_threshold_is_strict_and_case_insensitive(make_rows):
    records = [{} for _ in range(7)] + [{"shipping_cost": 150, "origin": "shanghai, china", "transport_mode": "ocean"}]
    result = analyze_shipments(make_rows(*records), AS_OF)
    assert not result.shipments["is_cost_anomaly"].any()
    assert result.shipments.iloc[7]["cost_group_size"] == 8


@pytest.mark.parametrize("cost", [None, "", -1, "oops", "inf", float("inf"), "1,2", "NaN"])
def test_invalid_costs_are_excluded_not_silently_zeroed(make_rows, cost):
    result = analyze_shipments(make_rows({"shipping_cost": cost}, {}), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["total_shipping_cost"] == 100
    assert k["cost_eligible_shipments"] == 1
    assert k["total_shipments"] == 2
    assert "cost" in result.issues.iloc[0]["code"]


def test_zero_and_well_formed_thousands_costs_are_valid(make_rows):
    result = analyze_shipments(make_rows({"shipping_cost": 0}, {"shipping_cost": "1,200.50"}), AS_OF)
    assert calculate_kpis(result.shipments)["total_shipping_cost"] == 1200.5
    assert result.issues.empty


def test_delivery_before_shipping_is_rejected(make_rows):
    result = analyze_shipments(make_rows({"actual_delivery": "2026-08-31"}), AS_OF)
    assert calculate_kpis(result.shipments)["delivered_shipments"] == 0
    assert "delivery_before_shipping" in set(result.issues["code"])


def test_invalid_optional_shipping_date_prevents_unverifiable_time_metrics(make_rows):
    result = analyze_shipments(make_rows({"shipped_at": "bad-date"}), AS_OF)
    assert calculate_kpis(result.shipments)["delivered_shipments"] == 0
    assert "invalid_shipped_at" in set(result.issues["code"])


def test_missing_plan_does_not_remove_verified_delivery(make_rows):
    result = analyze_shipments(make_rows({"planned_delivery": ""}), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["delivered_shipments"] == 1
    assert k["eligible_deliveries"] == 0
    assert k["on_time_delivery_rate"] is None


def test_future_actual_and_status_conflicts_are_not_completed_delays(make_rows):
    result = analyze_shipments(make_rows({"actual_delivery": "2026-10-02"},
                                        {"status": "In Transit"}), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["delivered_shipments"] == 0
    assert k["delayed_shipments"] == 0
    assert k["overdue_shipments"] == 0
    assert set(result.issues["code"]) == {"actual_after_cutoff", "status_date_conflict"}


def test_cutoff_includes_the_entire_day_and_respects_offsets(make_rows):
    result = analyze_shipments(make_rows(
        {"planned_delivery": "2026-10-01T23:00:00Z", "actual_delivery": "2026-10-01T23:59:59Z"},
        {"planned_delivery": "2026-09-30T23:00:00+02:00", "actual_delivery": "2026-09-30T21:00:00Z"},
    ), AS_OF)
    k = calculate_kpis(result.shipments)
    assert k["delivered_shipments"] == 2
    assert k["on_time_delivery_rate"] == 0.5
    assert math.isclose(k["average_delay_hours"], 3599 / 3600)


def test_carrier_rates_use_eligible_deliveries_not_all_shipments(make_rows):
    result = analyze_shipments(make_rows({}, {"status": "In Transit", "actual_delivery": ""},
                                        {"carrier": "Other", "actual_delivery": ""}), AS_OF)
    carrier = carrier_performance(result.shipments).set_index("carrier")
    assert carrier.loc["Fictional Carrier", "on_time_rate_pct"] == 100
    assert carrier.loc["Fictional Carrier", "eligible_deliveries"] == 1
    assert pd.isna(carrier.loc["Other", "on_time_rate_pct"])


def test_analysis_does_not_mutate_input(make_rows):
    data = make_rows({"transport_mode": "ocean"})
    before = data.copy(deep=True)
    analyze_shipments(data, AS_OF)
    pd.testing.assert_frame_equal(data, before)


def test_last_fractional_second_is_inside_the_inclusive_cutoff(make_rows):
    result = analyze_shipments(make_rows({"actual_delivery": "2026-10-01T23:59:59.999999998Z"}), AS_OF)
    assert result.cutoff.value == pd.Timestamp("2026-10-01T23:59:59.999999999Z").value
    assert calculate_kpis(result.shipments)["delivered_shipments"] == 1
