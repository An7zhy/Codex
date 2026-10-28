# Uploaded transportation planning contract (Sprint 2)

Schema: `uploaded-planning-v1`. Upload **one XLSX containing exactly four named
sheets**, or **four UTF-8 comma-separated CSVs** with the same headers. This
planning import is separate from the V1/V2 nine-column shipment analysis file.
Do not infer missing quotes/capacity from V1 shipping costs or demo carriers.

Download templates from authenticated Optimization → Uploaded Data Mode.
Templates contain 2 or 100 explicitly synthetic shipments; the 0-row API variant
has headers only. The XLSX header comments and downloadable field/rules JSON also
describe the contract. Preserve `synthetic_test` while using example data.

## Tables and fields

Column order and header case/outer whitespace may vary. Extra/duplicate/missing
columns are errors, not silently ignored information. IDs/location/source strings
must be nonblank and trimmed. IDs are at most150 characters. References may be
up to1000 characters; source_label up to200. XLSX expansion and compression limits match the original importer (64MiB total expanded,1000 parts, high-ratio guard); extra formatted/data rows beyond table limits are rejected rather than truncated. Trim the workbook or use CSV. Numbers use a decimal point without
commas, currency symbols, signs or exponents. NaN/Infinity/negative values fail.

### `shipments` — at most500 rows

| Field | Definition |
| --- | --- |
| shipment_id | Unique order ID; duplicate snapshots are rejected in this planning contract |
| origin / destination | Exact directional location labels; no inferred aliases/geocoding |
| weight / weight_unit | Per-order demand, 0.001–1,000,000; unit must be `kg` |
| volume / volume_unit | Per-order demand, 0.001–100,000; unit must be `m3` |
| delivery_deadline | Full ISO timestamp with seconds and `Z`/explicit offset, at/after planning_start and no more than87,600 hours later |

### `transport_options` — at most5000 rows

| Field | Definition |
| --- | --- |
| shipment_id / service_id | References to shipments and shared capacity; pair must be unique |
| quoted_cost / currency | Fixed **total per-shipment** quoted cost, 0–1,000,000,000; `USD` only. Agree included fees yourself; no app-invented surcharges |
| expected_transit_hours / time_unit | User-provided expected elapsed time, 1/60–87,600 hours; literal `h` only |
| quote_status / quote_reference | `estimate` or `user_verified`; nonblank quote/assumption source reference |
| time_status / time_reference | Same statuses, with a nonblank expected-time source reference |

Every option using one service_id **must agree on its expected duration**. The
existing V3 Service has one duration per shared service. If a real resource pool
has order-specific time functions, this MVP cannot represent it: do not create
fictitious separate capacities merely to bypass the check.

Options with route/deadline/individual-capacity violations remain visible in the
preview as excluded candidates; they cannot be selected by the solver. Unknown
references, conflicting durations, bad prices/units or duplicates are import
errors requiring correction before confirmation. Orders with no candidates are
explicitly warned; strict assignment is infeasible, soft mode may leave them out.

### `capacity` — at most100 rows

| Field | Definition |
| --- | --- |
| service_id | Unique shared capacity-pool ID; declare it once, not per order |
| origin / destination | Exact directional service route |
| transport_mode | `Air`, `Sea`, `Road` or `Rail` |
| weight_capacity / weight_unit | Total shared weight capacity, 0–1,000,000,000; `kg` |
| volume_capacity / volume_unit | Total shared volume capacity, 0–100,000,000; `m3` |
| shipment_capacity | Whole shipment slots, 0–1,000,000 |
| capacity_status / capacity_reference | `estimate` or `user_verified`, with nonblank source/assumption reference |

Zero capacity is valid input and may make the model infeasible. Unreferenced
capacity rows remain in the source audit but are omitted from the solver, with a
warning. Utilization describes modeled pools, not the entire declared transport
network. Each run is a planning alternative: it does not book, reserve or decrement capacity in another run. Do not assume independently split batches are jointly feasible. Capacity is static for this single planning batch; no replenishment,
departures, schedules, booking confirmation or cross-service resource coupling.

### `constraints` — exactly one row

| Field | Definition |
| --- | --- |
| planning_start | Common readiness/dispatch instant for **all** orders, full ISO with explicit zone |
| budget / currency | Hard batch budget, 0–1,000,000,000,000; `USD` only |
| allow_unassigned | CSV literal `true`/`false`; native Excel Boolean also supported. false requires every order, true explicitly permits partial fulfillment |
| unassigned_penalty / penalty_currency | Virtual objective penalty per unassigned order, 0–1,000,000; `USD`, not an invoice or verified financial loss |
| cost_weight / time_weight | Each0–100; sum must be positive. Preferences cannot override hard constraints; the original combined objective normalizes cost by1000USD and time by336h |
| time_limit_seconds | Per-strategy search limit0.1–10; shared worker wall budget remains45 seconds |
| source_label | Human-readable input-source description retained with results |
| data_kind | `synthetic_test` or `user_provided`; app does not independently certify either declaration |

## Time, currency and evidence policy

- USD, kg, m3, h are explicit. EUR/CNY/lb/litre/day inputs fail; no silent FX,
  weight or volume conversion. Missing numeric inputs fail rather than becoming0.
- `2026-10-03T00:00:00Z` and `2026-10-03T02:00:00+02:00` are the same deadline.
  Date-only, locale dates, native timezone-less Excel dates and naive timestamps
  fail. Use ISO strings; convert an agreed local/end-of-day SLA explicitly first.
- Existing conservative rounding is retained: demand up to grams/litres, cost up
  to cents and time up to minutes; resources/budget/deadlines down. Expected-time
  hard eligibility is not a guarantee of actual arrival under uncertainty.
- `user_verified` means the **uploader says it checked the referenced source**.
  The application does not access carrier APIs or inspect the external evidence.
  Counts, references, source files/hashes and actor/confirmation appear in the
  import record, allocation CSV and result JSON. They are not historical outcomes.
- Uploaded Mode deliberately runs no Monte Carlo and accepts no risk weight or
  historical distribution in this schema. Unknown reliability remains **Not
  estimated**, not 0% late or100% on time. Internal zero std is only a deterministic
  solver placeholder and is removed from public input/result tables.
- Synthetic Mode retains the original distribution assumptions and fixed-seed
  Monte Carlo. Its latest run and draft are kept separate from Uploaded Mode.

## Confirmed import workflow and exports

1. Select files; preview reads and validates them under the existing authenticated
   body/rate boundaries. Parsed field errors are saved as an `invalid` audit record.
   The UI displays the total and first200 error details explicitly; correct the
   source and re-preview. Invalid inputs cannot be confirmed or solved.
2. A valid `previewed` record retains source filenames, byte counts, SHA-256,
   schema, canonical tables, normalized model, uploader and timestamps. Preview
   counts individual eligibility only, not proof of shared batch feasibility.
3. Review and acknowledge the **exact** preview. The server verifies its digest;
   confirmation freezes the record with confirmed_by/confirmed_at. Repeated same
   confirmation reuses it. No endpoint accepts client edits of frozen model data.
4. Solve by import_id using the original V3 solver, all three strategies and the
   same hard constraints. The original independent allocation audit still runs.
   OPTIMAL / FEASIBLE / INFEASIBLE / UNKNOWN / MODEL_INVALID retain their meanings.
5. Download complete allocation/strategy/candidate CSV and source/result JSON.
   Failed allocation CSV has valid headers and zero assignments, not invented
   rows; its filename and HTTP metadata identify the source import. JSON and
   strategy CSV retain diagnostics and full source/assumption context.

The Uploaded result schema is `logistics-insight-uploaded-run-1`. It is **not** a
synthetic CLI Monte Carlo replay file. Re-import its `input_tables` through CSV/
XLSX to re-solve with the pinned implementation; references, OR-Tools version and
model constraints are retained. Timing/solver incumbents can vary by host.

Admin deletion removes an import and linked runs. A source deleted during a solve
cannot be resurrected by saving the result (409). Retention includes planning
imports and linked runs; stopped two-database backup/restore includes the new
table automatically. Preview/invalid records count toward the100-import/256MiB
shared quota. Old backups are governed separately by the operating policy.

## Independent arithmetic fixture

The two-order template has6kg/1m3 demand per order. ECO has one shared6kg/1m3
slot and24h duration; FAST has two slots/12kg/2m3 and12h duration. Deadlines are48h
and24h after the common start. Budget200USD; default cost/time weights100/0.

| Allocation | Cost | Expected total transport hours | Feasible |
| --- | --- | --- | --- |
| Order1 ECO + Order2 FAST | 40+80=120 | 24+12=36 | Yes |
| Order1 FAST + Order2 ECO | 100+50=150 | 12+24=36 | Yes |
| Both FAST | 100+80=180 | 12+12=24 | Yes |
| Both ECO | 40+50=90 | 24+24=48 | No, shared capacity exceeded |

Lowest Cost/combined cost-only must return120; Fastest180. The100-order fixture
has50 ECO slots: assign those to odd orders saving60 each rather than30 on even
orders, so minimum50×40+50×80=6000; all-FAST is9000. These expected results were
derived independently of the scoring formula; both fixtures are synthetic and
do not demonstrate commercial savings.

## API and access

| Endpoint | Minimum role / purpose |
| --- | --- |
| GET `/api/planning/contract`, `/templates/{kind}?count=0/2/100` | viewer; protected field guide, Excel or table CSV |
| POST `/api/planning/imports/preview` | operator; multipart `workbook`, or four parts named as the tables; no other fields |
| GET `/api/planning/imports`, `/{import_id}`, `/{import_id}/export/{kind}` | viewer; own organization instance records and exports |
| POST `/api/planning/imports/{import_id}/confirm` | operator; `{confirmation, acknowledged:true}` |
| POST `/api/planning/runs` | operator; `{import_id}` only |
| DELETE `/api/planning/imports/{import_id}` | admin; source and linked run deletion |

The Sprint1 session, role, instance identity, Origin, upload limit, rate budgets,
SQLite quotas, shared solver lease and process timeout apply unchanged. Uploaded
requests do not accept a client tenant/role or client model as authorization.

## Boundaries still requiring pilot acceptance

Real-input support describes an executable data path, **not validation on real
company data**. This sprint's numerical and browser evidence uses labeled
synthetic fixtures. Obtain consented freight samples and human business review
before operational use. Static single-period services, no quote expiry/calendar/
multi-leg schedules, no distribution calibration and no automatic booking remain
limitations. Remote TLS/ACL/OS CPU-RAM/soak acceptance remains separate from these
local functional tests. See SPRINT_2_REPORT.md for actual executed results.
