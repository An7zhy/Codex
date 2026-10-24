# Logistics Insight AI — Operations Report

**Data source:** Synthetic Demo Data — fictional orders and carriers  
**Analysis date:** 2026-10-01 (inclusive UTC day)  
**Scope:** All records

## Executive Summary

This selection contains **158 unique identified shipments** from 160 source rows. There are 91 verified delivered shipments, 47 completed late deliveries and 30 overdue in-transit shipments.
On-time delivery is **47.8%**, based on 90 deliveries with valid time comparisons. 4 high-cost shipments were identified.
No root cause is inferred from order-level dates, status or cost alone.

## Operational KPIs

| KPI | Value |
| --- | ---: |
| Total Shipments | 158 |
| Delivered Shipments | 91 |
| On-Time Delivery Rate | 47.8% |
| Average Delay Hours (late deliveries only) | 36.5 h |
| Overdue Shipments | 30 |
| Total Shipping Cost (USD) | 539,830.75 |
| Cost Anomalies | 4 |

Cost totals use 155 valid costs. Missing or invalid costs are not zero-cost shipments. 2 shipments have insufficient comparable cost data.

### Metric definitions

- **Total Shipments:** Unique, nonblank shipment IDs; keep the first occurrence. Other field errors remain reviewable.
- **Delivered Shipments:** Retained shipments reported Delivered with a valid actual delivery at or before the analysis cutoff and valid actual chronology.
- **On-Time Delivery Rate:** On-time deliveries / delivered shipments with a valid planned date and valid planned chronology. Incomplete shipments are excluded.
- **Average Delay Hours:** Mean positive delay among eligible delayed deliveries only. Zero when eligible deliveries exist but none is late; N/A when none is eligible.
- **Overdue Shipments:** Retained In Transit shipments with a valid planned date before the cutoff and no reported actual delivery; counted separately from completed delays.
- **Total Shipping Cost:** Sum of finite, nonnegative costs on retained shipments, across all statuses. All costs must use USD; missing or invalid costs are excluded.
- **Cost Anomalies:** High-cost retained shipments in a mode + directional origin/destination group with at least 8 valid comparable costs; thresholds use the complete uploaded dataset before filtering.

## Key Exceptions

Rows may have more than one exception. Completed delays and overdue in-transit shipments are separate.

91 source rows have an exception or a data quality issue. First 15 rows are shown; download the exceptions CSV for the complete list.

| Source row | Shipment | Exceptions | Delay hours |
| ---: | --- | --- | ---: |
| 2 | SYN-0001 | Data quality | 0.0 |
| 3 | SYN-0002 | Data quality | N/A |
| 4 | SYN-0003 | Data quality | N/A |
| 5 | SYN-0004 | Data quality | N/A |
| 6 | SYN-0005 | Delayed delivery; Data quality | 24.0 |
| 7 | SYN-0006 | Delayed delivery; Data quality | 72.0 |
| 8 | SYN-0007 | Data quality | N/A |
| 9 | (missing ID) | Data quality | N/A |
| 10 | SYN-0009 | Data quality | N/A |
| 12 | SYN-0011 | Delayed delivery; Data quality | 24.0 |
| 13 | SYN-0012 | Delayed delivery; Data quality | 72.0 |
| 14 | SYN-0013 | Data quality | N/A |
| 15 | SYN-0014 | Data quality | N/A |
| 17 | SYN-0016 | Delayed delivery; Data quality | 12.0 |
| 18 | SYN-0017 | Data quality | N/A |

## Carrier Performance

Rates use each carrier's eligible completed deliveries; N/A means there is no valid denominator.

| Carrier | Shipments | Verified delivered | Eligible deliveries | On-time rate |
| --- | ---: | ---: | ---: | ---: |
| Demo Air One | 40 | 24 | 24 | 33.3% |
| Demo Air Two | 40 | 23 | 23 | 65.2% |
| Demo Ocean One | 38 | 21 | 21 | 28.6% |
| Demo Ocean Two | 39 | 23 | 22 | 63.6% |
| Unknown | 1 | 0 | 0 | N/A |

## Data Quality Issues

17 source rows have 19 quality findings. 2 rows are excluded from shipment KPIs because their IDs are missing or repeated.

| Finding | Count |
| --- | ---: |
| status\_date\_conflict | 2 |
| invalid\_cost | 2 |
| missing\_shipment\_id | 1 |
| duplicate\_id | 1 |
| duplicate\_id\_retained | 1 |
| missing\_carrier | 1 |
| unsupported\_status | 1 |
| missing\_origin | 1 |
| missing\_transport\_mode | 1 |
| implausible\_planned\_delivery | 1 |
| invalid\_planned\_delivery | 1 |
| invalid\_actual\_delivery | 1 |
| missing\_actual\_delivery | 1 |
| plan\_before\_shipping | 1 |
| delivery\_before\_shipping | 1 |
| actual\_after\_cutoff | 1 |
| missing\_cost | 1 |

## Recommended Next Actions

1. Review the data quality queue, resolve repeated or missing IDs, and correct invalid dates and costs before relying on affected metrics.
2. Prioritize overdue in-transit shipments for a manual status check with the carrier; obtain current milestones and a revised ETA.
3. Review completed late deliveries by route and carrier. Request milestone evidence before assigning a root cause.
4. Check high-cost records against invoices, shipment weight, service level and surcharges before treating them as billing errors.
5. Collect more comparable costs for groups marked Insufficient data; do not interpret them as normal or anomalous yet.

## Method and Limitations

- High cost is strictly above median + max(3.5 × 1.4826 × MAD, 0.5 × median), with at least 8 valid costs per mode and directional route. Thresholds are fixed on the full input before UI filters.
- All costs are assumed USD. The MVP does not normalize weight, currency, service level or seasonality. The cost rule is a screening heuristic, not proof of overcharging.
- ISO dates without offsets are UTC. Date-only deliveries occur at 00:00 UTC; the selected analysis day ends at 23:59:59.999999999 UTC.
- Statuses describe the uploaded snapshot. Changing the analysis date does not reconstruct historical status or historical cost.
- Without optional shipped_at, chronology checks are limited to valid dates since 2000-01-01 and the analysis cutoff. Early delivery relative to the plan is valid.
- This report is generated by deterministic Python rules. Synthetic Demo Data is fictional and cannot establish real-world accuracy.
