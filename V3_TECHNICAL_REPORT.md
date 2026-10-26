# V3 Transportation Optimization — Technical and Verification Report

Date: 2026-10-26 (Asia/Shanghai). Development branch: `feature/v3-optimization`.
Baseline: V2 commit `7f50305`. This is a synthetic engineering prototype, not a
carrier network, live booking service or validated forecasting product.

## 1. Scope and integration

V1/V2 remain the default workspace, with their existing upload contract, KPIs,
exception rules, priorities, interventions, reports and SQLite history unchanged.
The only integration in `app.py` is a workspace selector and a conditional import
of the V3 presentation module. V3 does not write to SQLite or modify V1/V2 data.

V3 implements:

- Per-order hard eligibility and three local recommendations.
- OR-Tools CP-SAT multi-order allocation to shared services.
- Constrained cost/time baselines and a weighted cost/time/risk allocation.
- Seeded common-random-number transit simulation.
- Four Streamlit views with explicitly submitted what-if inputs.
- CSV exports and full-input JSON replay through a command-line script.

Business modules are `src/transport/models.py`, `demo.py`, `engine.py`,
`simulation.py` and `experiments.py`; `ui.py` only presents and commits inputs.

## 2. Synthetic data and input contract

`generate_planning_demo(count, seed=42)` creates orders on three fictional lanes:
Shanghai–Rotterdam, Shenzhen–Los Angeles and Singapore–Hamburg. Each lane has three
fictional services: priority air, regular air and economy sea. These labels imply
no relationship with any real carrier.

Orders contain unique IDs, exact directional origin/destination labels, weight
(kg), volume (m³) and an elapsed-hours delivery deadline. Services contain unique
IDs, mode, mean/std transit hours, total weight/volume capacity and shipment slots.
Candidates reference one order and one service with a fixed USD shipping cost.

The demo invents weights of 50–300 kg, volumes of 0.2–2 m³, deadlines of 48/96/384 h
and mean/std pairs of 24/6, 48/12 and 336/48 h. Each service starts with approximately
75% of its lane's demand capacity (at least one largest shipment fits). Prices
are invented fixed-plus-weight teaching formulas. None of these values is a
geographical transit benchmark, market quote or carrier commitment.

All orders are ready at a common hypothetical dispatch time **hour 0**. Expected
transport time and deadline are relative to that origin, not today's wall clock.
The UI's deadline shift changes every order's relative deadline, bounded below
at zero. Capacity factors change resource availability; slots round down.

Missing required values, non-finite/negative costs or capacities, nonpositive
shipment dimensions, invalid IDs, duplicate IDs/pairs and dangling references
raise actionable validation errors. A missing std is not interpreted as zero;
an explicitly supplied zero std represents a deterministic teaching assumption.
No missing logistics information is filled with a claimed real-world estimate.

`data/optimization/synthetic_demo_experiment.json` contains all 12-order inputs,
constraints, preferences, seeds and measured outputs. Its companion CSV is a
strategy summary. The generators never change V1 files or user history.

## 3. Hard eligibility before preferences

A candidate is removed before optimization if:

1. Its service's exact directional route differs from the order's route.
2. The individual shipment exceeds service weight or volume capacity.
3. The service has no shipment slots.
4. Expected arrival exceeds that order's hard deadline.
5. Its individual cost exceeds the entire available budget.

Rejected candidates have no balanced score and retain explicit reasons. The
remaining global model enforces shared resources and the aggregate budget.
Passing an individual check does not reserve capacity or establish global feasibility.

The deadline rule is `expected transit <= deadline`. Random realized transit can
still be late; this model has **no chance constraint, guaranteed ETA or guaranteed
on-time service**. Reliability is an optimization preference among hard-eligible
options, not permission to violate deadlines.

## 4. Mathematical model

Let `I` be orders, `S` shared services and `E` hard-eligible order/service pairs.
Parameters `c[i,s]`, `t[s]`, `p[i,s]`, `w[i]`, `v[i]`, `W[s]`, `V[s]`, `N[s]`
and `B` denote cost, expected time, assumed late probability, order dimensions,
shared capacities, shipment slots and total shipping budget.

Variables:

```text
x[i,s] ∈ {0,1}                 choose a candidate in E
u[i]   ∈ {0,1}                 unassigned, only in the optional soft mode
```

Strict mode requires every order to have exactly one selected eligible option:

```text
sum_s x[i,s] = 1                                      for each order i
```

Optional penalized mode instead uses:

```text
sum_s x[i,s] + u[i] = 1                               for each order i
```

Thus no order can receive multiple services. In both modes:

```text
sum_i w[i] × x[i,s] <= W[s]                           for every service s
sum_i v[i] × x[i,s] <= V[s]                           for every service s
sum_i x[i,s]        <= N[s]                           for every service s
sum_(i,s) c[i,s] × x[i,s] <= B                        total shipping budget
```

There is no shipment splitting. Different orders consume the same service's
resources. An independent output audit recomputes resource usage, route/deadline
eligibility, one-assignment rules and budget from the original source objects.
An audit failure raises an error instead of presenting a recommendation.

### Objectives and preference units

Weights are nonnegative, normalized to sum to one; all-zero weights are invalid.
Default cost/time/risk weights are **30/30/40**. Fixed normalization scales avoid
changing the meaning of a score when another candidate enters the dataset:

```text
q[i,s] = a × c[i,s]/1000 + b × t[s]/336 + r × p[i,s]
a + b + r = 1
```

Lower scores are preferred. The strategy objectives are:

```text
A Lowest Cost:          minimize sum c[i,s] × x[i,s] + P × sum u[i]
B Fastest Delivery:     minimize sum 10 × t[s] × x[i,s] + P × sum u[i]
C Optimized Allocation: minimize sum 1000 × q[i,s] × x[i,s] + P × sum u[i]
```

All coefficients are converted to integer cents/virtual cents. `P` is an explicit
virtual-USD unassignment penalty, default USD 100,000 per order. B's assumed
USD 10/hour converts time into units compatible with that penalty; with strict
fulfillment it is simply a positive scaling of total expected transit time.
With soft fulfillment, B trades time against the declared penalty, so it does
not mean "fastest regardless of unassigned orders".

Penalties are not invoices, cargo loss, customer damages or invented contractual
charges. The shipping budget constrains shipping spend, not virtual penalties.
Raw objective values from different strategies are not comparable business costs.
A small penalty can deliberately leave a feasible but expensive order unassigned.

### Integer precision and solver states

Costs/demands/expected times round **up** to cents, grams, liters and minutes.
Budget/capacities/deadlines round **down** to the same units. This conservative
conversion can reject borderline inputs but cannot authorize fractional
overspending/overbooking. Balanced objective coefficients round to nearest
virtual cents. Optimality is for this integer model, not an unrounded continuous
or real-world problem.

CP-SAT uses one search worker and fixed solver seed 42. The default search limit
is 5 seconds per strategy; wall time also includes model construction and output
processing. Status handling is explicit:

| Status | Product interpretation |
| --- | --- |
| OPTIMAL | A feasible assignment with proven minimum integer objective |
| FEASIBLE | A valid incumbent; optimality has not been proved |
| INFEASIBLE | No assignment satisfies this model and these constraints |
| UNKNOWN | Neither a returned solution nor an infeasibility proof; not "infeasible" |
| MODEL_INVALID | No recommendation; model validation also raises an actionable error |

Failed solves have no reported spend, utilization or on-time benefit. Orders are
unresolved, not an accepted partial plan. Candidate rejections and necessary
individual cost bounds aid diagnosis; the app does not claim an exact minimal
conflicting constraint set for every shared-resource infeasibility.

## 5. Uncertainty and Monte Carlo methodology

Service transit `T` follows an **assumed lognormal distribution** with supplied
arithmetic mean `m` and standard deviation `s`:

```text
sigma² = ln(1 + (s/m)²)
mu = ln(m) - sigma²/2
T = exp(mu + sigma × Z), Z ~ Normal(0,1)
p_late = Pr(T > order deadline)
```

Zero std gives deterministic transit. The analytic tail is used in the objective;
Monte Carlo independently samples the assumed distribution for evaluation. It is
not a learned forecast and no historical calibration has been performed.

Default simulation seed is **2026**, with **2000 scenarios**. A stable hash of the
service ID selects each service-specific random stream, making generation
independent of service-list ordering. Every strategy uses the **same** scenario
bank, identified by a SHA-256 fingerprint. In a scenario, orders sharing a service
share its transit draw (a deliberately simplified common disruption). Different
services have independent draws. This correlation assumption is explicit and
does not represent measured network behavior.

The UI separately labels expected hours, one scenario's simulated transit hours,
mean/p95 simulated hours and estimated late probability. Simulated transit is
never stored as an actual historical delivery. Shipping prices are fixed; random
customs charges, penalties, exchange rates and lost-sales costs are not modeled.

## 6. Strategy comparison and metric definitions

All three strategies share orders, hard-eligible candidates, capacities, budget,
deadline rules, unassignment mode and random scenarios. A and B are constrained
optimization baselines, rather than invalid independently selected cheap/fast
services. Local recommendations in the Decision Center are labeled local only.

| Reported metric | Definition |
| --- | --- |
| Total shipping cost | Sum of selected option prices; excludes virtual penalties |
| Expected on-time rate, all orders | Selected options meeting expected deadline / all requested orders |
| Simulated on-time rate, all orders | Mean simulated on-time count / all requested orders; unassigned count as not on time |
| Simulated rate, assigned only | Mean simulated on-time count / assigned orders, separately labeled |
| Simulated late probability, assigned | Mean late fraction among assigned orders |
| Mean simulated delay | Positive lateness hours summed across assigned orders/scenarios, divided by assigned count and scenario count |
| p95 total delay | 95th percentile of each scenario's summed shipment lateness |
| Utilization | Sum of used weight/volume/slots divided by total listed service capacity; also shown per service |
| Unassigned orders | Accepted unassignment only when a feasible soft-mode plan exists |
| Allocation time | Candidate checks, model construction, solver and output processing |
| Experiment time | Shared scenarios, all three allocations and simulations; excludes UI, file I/O and data generation |

Empty denominators yield N/A. Zero all-order on-time delivery for a nonempty
all-unassigned plan is valid; an empty demand set has no on-time rate. The reported
Monte Carlo standard error uses variability across independent scenarios,
preserving the within-service common shocks; it is not forecast confidence.

Costs from failed or differently fulfilled plans are not presented as savings.
The comparison explicitly warns unless all three strategies fully fulfill the
same demand. The What-if view identifies changed demand/deadlines or random draws
and shows previous/current runs without making a controlled improvement claim.
Identical recommendations under changed weights can be valid, and multiplying
all weights by the same factor changes no normalized preference.

## 7. Actual measurements

Environment: Linux 6.18.55 x86_64/glibc 2.41; Python **3.12.14**; OR-Tools
**9.15.6755**; NumPy 2.5.4; pandas 2.3.3; Streamlit 1.50.0; Plotly 6.3.1;
pytest 8.4.2. Dependencies were installed from `requirements.txt`; `pip check`
reported no broken requirements. This is a shared cloud environment, not an
isolated or controlled performance lab. Regression work also ran during the
measurement window; these results are local observations, not latency guarantees.

### Default 12-order demonstrator

All three strategies returned OPTIMAL and assigned all 12 orders:

| Strategy | Shipping cost USD | Simulated all-order on-time rate |
| --- | ---: | ---: |
| Lowest Cost | 11,060.00 | 80.72% |
| Fastest Delivery | 25,351.00 | 96.15% |
| Optimized Allocation | 13,013.50 | 89.53% |

These are synthetic trade-offs under the stated assumptions, not financial
benefit estimates or measured carrier performance. "Optimized" does not mean
lowest cost and highest on-time rate simultaneously.

### Required 100/500-order workloads

Three repetitions at each size used data seed 42, simulation seed 2026, 2000
scenarios and a 5-second solver limit per strategy. Every returned allocation
passed the independent feasibility audit and assigned every order.

| Orders | Strategy | Status in all 3 runs | Cost USD | Simulated on-time | Median allocation time |
| ---: | --- | --- | ---: | ---: | ---: |
| 100 | Lowest Cost | OPTIMAL | 92,116.00 | 80.12% | 0.032 s |
| 100 | Fastest Delivery | FEASIBLE | 206,206.00 | 94.98% | 5.065 s |
| 100 | Optimized Allocation | OPTIMAL | 116,592.50 | 87.68% | 0.045 s |
| 500 | Lowest Cost | OPTIMAL | 459,522.00 | 80.69% | 0.103 s |
| 500 | Fastest Delivery | FEASIBLE | 1,048,535.00 | 94.52% | 5.100 s |
| 500 | Optimized Allocation | OPTIMAL | 591,355.00 | 88.04% | 0.153 s |

Total experiment medians were **5.288 s** (100 orders, range 5.146–5.452 s)
and **5.499 s** (500 orders, range 5.486–5.556 s). Time spent trying to prove the
Fastest Delivery objective dominates these runs. Those solutions are feasible
baselines, **not proven globally fastest allocations**. Larger or altered instances
can return different states under the same time limit.

Aggregate weight utilization was about 44.44% for both sizes; volume about
44.44%; slots 43.86% (100) and 44.21% (500). Identical totals across strategies
are expected because every strategy assigns the same demand into the same total
resource pool. Per-service bottlenecks still differ. These are not measured
vehicle-load or commercial efficiency improvements.

Raw evidence: [v3_benchmark.json](docs/v3_benchmark.json),
[v3_case_evidence.json](docs/v3_case_evidence.json),
[v3_browser_evidence.json](docs/v3_browser_evidence.json).

## 8. Executed verification and commands

Before changes: **135 passed in 29.24 s**. Final full suite: **200 passed in
46.73 s**, **0 failures, 0 skips, no warnings**. The added 65 tests exercise
hand-calculated outcomes, normalized/extreme weights, each shared capacity,
individual and aggregate budget checks, deadline boundaries, missing/invalid
inputs, duplicate references, empty demand, no candidates, penalty trade-offs,
conservative rounding, distribution moments/tails, common draws, replay and UI.

Small constrained assignments are additionally compared with exhaustive
enumeration. OPTIMAL/INFEASIBLE are obtained naturally; UNKNOWN is obtained with
an actual tiny solve limit. FEASIBLE is observed in the real 100/500-order
benchmarks. Controlled status injection covers FEASIBLE/UNKNOWN/MODEL_INVALID
branches and FEASIBLE/UNKNOWN UI wording; it does not pretend a malformed model
was discovered in normal operation.

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m compileall -q app.py src tests scripts
python -m pip check
python -m scripts.v3_experiment --benchmark --output docs/v3_benchmark.json
python -m scripts.v3_experiment --orders 12 --case standard --output data/optimization/synthetic_demo_experiment.json
python -m scripts.audit_browser
```

Commands above were executed using `.venv/bin/python`. Six script cases were
also executed: standard/empty/allow-unassigned → OPTIMAL; capacity shortage,
zero budget and no eligible service → INFEASIBLE, as expected.

The optional browser environment had Playwright and system Chromium installed.
The following actual isolated-server command passed (POSIX shell):

```bash
LOGISTICS_DB_PATH=/tmp/logistics-v3-browser-test.sqlite3 \
BROWSER_EXECUTABLE_PATH=/usr/bin/chromium \
.venv/bin/python .agents/skills/webapp-testing/scripts/with_server.py \
  --server '.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8513 --server.headless true --browser.gatherUsageStats false' \
  --port 8513 -- .venv/bin/python tests/browser_transport.py
```

That helper comes from the locally installed development skill, not a runtime
dependency. Portable alternative: launch Streamlit on 8513 in one terminal with
an isolated `LOGISTICS_DB_PATH`, then run `python tests/browser_transport.py` in
another, setting `BROWSER_EXECUTABLE_PATH` only for system Chromium. Use
`requirements-dev.txt` and `python -m playwright install chromium` otherwise.

Real Chromium checks passed for workspace navigation, all four views, applied vs
draft weights, changed allocations with unchanged random draws, retained shipment
selection, CSV/JSON downloads, budget/capacity/deadline infeasibility, explicit
unassignment, invalid all-zero weights and return to V1 without JavaScript errors.
The first browser attempts exposed harness issues: a 5-second navigation wait
expired while the page was running, and a selector targeted Streamlit's hidden
native checkbox instead of its visible label. The harness was corrected, and the
complete flow then passed; no assertion was removed to conceal an app failure.

The existing V1/V2 browser audit also passed: original smoke/case-history/parameter
regressions, actual backend cold restart preserving temporary history, real
100/500/5000-row CSV uploads and invalid input messages. Only temporary SQLite
paths were used; existing user databases were not modified.

## 9. Remaining limitations and Not Tested

- **Not Tested:** Windows/macOS and the full Python 3.14 dependency/UI matrix.
  Python 3.12 remains the recommended environment. Native desktop file dialogs,
  translated browsers and Excel require the existing manual checks.
- **Not Tested:** V3 5000-order optimization, production concurrency, soak tests
  or larger networks. The V1/V2 5000-row upload regression is a separate test.
- **Not Validated:** real carrier transit distributions, availability, tariffs,
  disruption correlation, contractual loss or economic value of recommendations.
- UI planning inputs are generated synthetic cases; arbitrary V3 CSV/Excel
  planning import and a V3 database schema are not implemented. Typed Python
  inputs and saved-input JSON CLI replay are supported.
- No actual booking, live routing, multiple legs, shipment splitting, dispatch
  schedules or uncertain costs. Capacity is static over one planning horizon.
- Default large-instance Fastest Delivery results are FEASIBLE within 5 seconds;
  no proof of fastest possible allocation is claimed.
- The weighted score is one explicit preference rule, not a learned policy,
  validated risk model or complete multiobjective Pareto frontier.
- Seeds make simulated draws reproducible with the recorded versions. Solver
  incumbents and timings can differ under time limits and changing hardware.

## 10. Stability conclusion

The implemented V3 scope passes the executed core, UI and browser checks while
retaining V1/V2 regression behavior. It is suitable for a reproducible portfolio
demonstration and further controlled development. It is not validated for freight
forwarder production decisions and makes no comparison or superiority claim
against project44, FourKites or other commercial products.
