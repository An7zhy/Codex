# V2 executed validation

V2 extends the retained V1 dashboard into a lightweight, explainable exception
decision copilot. All results below are current-instance checks on Linux with
Python 3.12.14, not proof of operational effectiveness or a production deployment.

## Baseline and automated tests

- Before implementation: the original V1 suite completed with **49 passed**.
- Final combined suite: **103 passed**, no skipped tests or test warnings.
- `python -m compileall -q app.py src tests`: passed.
- `python -m pip check`: no broken requirements.
- SQLite is provided by Python; no new runtime package or remote service is required.

Business coverage includes all V1 cases plus hand-calculated priority components,
weights/scales/threshold errors, valid custom settings in the UI, disabled weights,
missing/invalid context, high value with missing financial exposure, deadline
fallback, active/completed/unidentified disposition, and immutable source data.
Displayed score precision and level thresholds are tested together.

Scenario tests verify changed cost/time inputs, deadline effects, unknown deadlines,
unavailable actions and rejected negative/non-finite assumptions. History tests
reopen a real temporary SQLite file, preserve unknown actuals as NULL, update actuals
and statuses, reject stale concurrent writes, exercise parameterized queries, and
check exact directional-route/mode/exception similarity. Streamlit tests exercise
scenario editing, saving, updating, displaying a past analogue, evaluation, invalid
settings and an unavailable database while preserving the V1 dashboard.

A regression test also caught V1's cutoff resolution: a seconds-resolution
Timestamp could display nanoseconds without retaining them in its value. The
cutoff now parses the inclusive UTC end-of-day at true nanosecond resolution. A
delivery in the last fractional second is explicitly tested. V1 demo KPIs remain
158 retained shipments, 91 verified delivered, 47.8% on time, 30 overdue and 4
high-cost flags.

## Reproducible comparisons

Executed `python -m src.evaluation`; output is captured in
[`synthetic_evaluation.json`](synthetic_evaluation.json).

- Nine hand-authored synthetic cases; V1 detects eight exception rows.
- Four cases have independently written ordinal references, giving six comparable
  pairs. Under default settings all six agree, with no tied pairs.
- All nine disposition references match under the default configuration.
- All five component rules have a valid and a missing/invalid fixture example.
- A deliberately value-heavy stress profile changes the leading ranked case.
- Three action-assumption sets produce different incremental costs and delays.

References live in `data/evaluation/reference_cases.json`. They are not calculated
from the score formula. Agreement here is a tiny, synthetic consistency check,
**not prediction accuracy**, an expert assessment or a validated ranking policy.
Rule-example coverage is not a code-coverage percentage.

## Real browser and persisted outcomes

Started a separate Streamlit service using an isolated SQLite file under `/tmp`.
The server and browser command shared the same `LOGISTICS_DB_PATH`; no real cases
or the default application history database were written by browser acceptance.

Executed the retained `tests/browser_smoke.py` against V2:

- Seven original metrics and four rendered Plotly charts.
- Actual CSV and Excel uploads, original KPI/quality/exception views.
- Downloaded and checked processed CSV, exceptions CSV and the English report.
- Filtered report, no-match filter, rejected missing columns, header-only input.
- Mobile-width layout without page-wide overflow.

Executed `tests/browser_copilot.py` with Playwright 1.62.0 and system Chromium:

- Visible priority queue, explanations and missing-information lane.
- Editable scenario cost and explicit saved human action.
- Updated resolution status, actual incremental cost and actual delay.
- Browser reload preserved the saved actuals; a separate backend query confirmed
  the case was Resolved with synthetic estimate USD 123, entered actual USD 150,
  and entered actual delay 12 hours.
- Ran the comparison UI and downloaded/parsed its real evaluation JSON.
- No Streamlit exception element or JavaScript page error in the successful run.

The update UI now acknowledges a committed write before refresh. Browser tests
wait for that acknowledgment rather than relying on a changed dropdown label.
A fresh test service was used after module edits so acceptance exercised current
source rather than an older imported module.

Screenshots from the running app:
[priority](images/v2-priority-queue.png),
[Decision Center](images/v2-decision-center.png),
[case history](images/v2-case-history.png).

## Verified versus simulated

Verified: program execution, deterministic calculations, UI controls/downloads,
SQLite persistence/updates, data-validation paths and synthetic evaluation outputs.

Simulated/unvalidated: all demo shipment context, financial exposure assumptions,
downstream counts, action availability, intervention costs and remaining durations.
There was no live carrier API, booking, validated arrival forecast, causal impact
estimate, real-world accuracy study or commercial software benchmark. Windows,
macOS, Python 3.14 and restoration into a new cloud task were not tested here.
