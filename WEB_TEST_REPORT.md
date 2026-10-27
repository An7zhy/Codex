# Premium Website & Dashboard — Verification Report

Date: **2026-10-27 (Asia/Shanghai)**. Branch: `feature/premium-web-redesign`.
Stable source backup: Git tag `stable/v3-before-premium-web`, commit `35ba988`.

## Delivered scope

The original marketing site, shared design system, routed application and FastAPI
adapters are implemented. Each page is connected to existing Python functions or
local SQLite. No core V1–V3 algorithm was rewritten for the UI.

| Page | Implementation and verified connection |
| --- | --- |
| `/` | Original SVG hero, responsive marketing sections, working launch, API-computed synthetic preview |
| `/app` | Existing KPI/carrier/status/lane/exception calculations and English report |
| `/app/shipments` | CSV/Excel upload, persisted dataset, server filters, pagination, quality findings and CSV |
| `/app/exceptions` | Existing V2 score, rationale, missing information and priority CSV |
| `/app/decisions` | Existing three-scenario calculations, explicit applied/draft state and server-recomputed case save |
| `/app/decisions/history` | Existing SQLite querying, idempotent save and versioned outcome update |
| `/app/optimization` | Existing V3 hard eligibility, real CP-SAT allocation, common-scenario strategies, what-if comparison and exports |
| `/app/analytics` | Saved V3 Monte Carlo outcomes and original V2 reference-case evaluation |
| `/app/settings` | Validated priority weights/scales stored locally, with live re-analysis after application |

Static prerendering in Next's build output refers to page shells. Business values
are fetched from FastAPI. A missing experiment or stopped API has an empty/error
state, not invented figures.

## Environment

- Linux x86_64, Python **3.12.14**, Node **24.19.0**, npm **11.9.0**.
- Next.js **16.4.3**, React **19.3.1**, TypeScript **5.9.3**,
  Tailwind **4.3.3**, Motion **12.43.0**, Recharts **3.10.1**, Lucide **0.577.0**.
- FastAPI **0.162.0**, Uvicorn **0.54.0**, httpx **0.28.1**,
  python-multipart **0.0.32**; original pandas/OR-Tools/Streamlit versions retained.
- Playwright with system Chromium; production Next server, not only a dev preview.
- Browser audit uses frontend 3100 and API 8000 with temporary SQLite databases.
  Normal launcher defaults to frontend 3000/API 8000.

Python environment details are recorded in
[`docs/premium_validation_environment.json`](docs/premium_validation_environment.json).
Frontend direct and transitive versions are locked in `web/package-lock.json`.
No user history database was used in automated testing.

## Executed commands and results

Commands were run from the repository root unless marked `web/`. The execution
environment uses `.venv/bin/python`; normal installations can use activated `python`.

| Executed check | Result |
| --- | --- |
| Baseline `python -m pytest -q`, before changes | **200 passed in 55.93 s** |
| Install optional Python web dependencies / `requirements-web.txt` pins | Installed |
| `npm install --no-audit --no-fund` in `web/`, writable `/tmp` npm cache | Installed; lockfile generated |
| `python -m pytest -q tests/test_web_api.py` | **25 passed in 5.70 s** |
| Complete `python -m pytest -q` | **225 passed in 85.52 s**, 0 failed, 0 skipped |
| `npm run typecheck` in `web/` | Passed |
| `npm run build` in `web/` | Passed; all application routes generated |
| `python -m compileall -q app.py src backend tests scripts` | Passed |
| `python -m pip check` | No broken requirements |
| `python -m scripts.audit_browser` | Original V1/V2 browser, cold restart, uploads and invalid-input checks passed |
| `python -m scripts.audit_premium_web` | Production browser workflow and actual API cold restart passed |
| `git diff stable/v3-before-premium-web -- src app.py requirements.txt` | Empty: core source, fallback UI and original requirements unchanged |

The final build/typecheck was repeated after UI corrections. Python elapsed time
was measured while other verification work also ran and is not a performance SLA.
The full suite includes the original V3 100/500-order numerical workload checks.
The new browser audit additionally executes a real 100-order solve through the UI.

For reproduction:

```bash
python -m pip install -r requirements-web.txt -r requirements-dev.txt
cd web
npm ci
npm run typecheck
npm run build
cd ..
python -m pytest -q
python -m compileall -q app.py src backend tests scripts
python -m pip check
python -m scripts.audit_browser
python -m scripts.audit_premium_web
```

For bundled Playwright Chromium use `python -m playwright install chromium`.
For a system installation set `BROWSER_EXECUTABLE_PATH`. The browser audit refuses
to take over occupied test ports; stop your own old process before running it.
`scripts.start_web.WebServers` is the tested cross-platform lifecycle manager used
by the public launcher and audit.

## Numerical and persistence assertions

The API tests assert values, not merely successful HTTP responses:

- Demo: 158 retained shipments, 91 verified delivered, 43/90 on-time deliveries,
  30 overdue In Transit, USD 539,830.75 valid shipping cost and four cost anomalies.
- In Transit filters give no completed-delivery on-time denominator. CSV and
  report exports use the full filtered selection independently of page size.
- Financial weight 20→100 changes SYN-0027 from 78.6667 to 88.1481; V1 KPIs stay equal.
- SYN-0027 wait 96h gives 72h scenario lateness; wait 48h/cost 450 gives 24h lateness.
  Cost-only 450→900 retains 24h. No cost-to-speed relation is invented.
- CSV and Excel uploads survive a fresh store instance. Missing columns/corrupt
  files fail visibly; header-only files and individual invalid dates/costs/IDs
  remain supported without crashing the app.
- Repeated case saves reuse one case; actual values start unknown. Status/outcome
  updates persist, stale versions return 409 and similar-case matching uses existing
  deterministic route/mode/type rules.
- Default 12-order CP-SAT output has a feasible complete allocation; each candidate
  check and simulation detail comes from V3. Zero budget has no reported fake spend
  or benefit; explicit unassignment reports 12 unassigned; empty demand has N/A rates.
- Negative/out-of-range values, boolean numeric substitutions, unknown fields,
  invalid dates and pagination parameters are rejected.

## Real production-browser workflow

[`docs/premium_browser_evidence.json`](docs/premium_browser_evidence.json) records
the completed checks. The browser types values and clicks buttons rather than
directly mutating React state.

- Homepage launch, all seven sidebar menu URLs and the separate history route.
- Dashboard/report calculations, filters, CSV export, pagination, quality and empty state.
- Applied financial-weight change and an unchanged V1 on-time KPI.
- Decision comparison; draft 900 displayed over an applied 450 estimate does not
  change what Save records. Repeated saves keep one record.
- Actual cost 470, actual delay 20 and Resolved status survive page reload.
- Default V3 solve, hard-deadline rejection, zero-budget infeasibility, explicit
  unassignment and real 100-order allocation; CSV/JSON match the displayed run.
- Latest Monte Carlo results and V2 reference evaluation are displayed in Analytics.
- Real file-input CSV and Excel uploads, persisted selected dataset and malformed-file error.
- Desktop 1440px and mobile 393px, accessible drawer navigation, reduced motion,
  keyboard skip link, no document-level horizontal overflow, no JavaScript page errors.
- Delayed real workspace response shows a skeleton; an injected API 503 produces
  an actionable error instead of fabricated or stale KPIs.
- A dataset remembered from a removed/changed local database shows a recoverable
  error and can be explicitly reset to the synthetic demo.

The 100-order browser run returned Lowest Cost **OPTIMAL**, Fastest Delivery
**FEASIBLE**, Optimized Allocation **OPTIMAL**. FEASIBLE is presented as an
unproved incumbent, never a proven fastest or optimal solution.

The audit terminates the API process and starts a new PID, then compares saved
cases, uploaded datasets, settings and latest optimization run. All matched. This
is an actual process restart, separate from React page reload or a new DB object.

## Visual review and fixes

- Original SVG torus/route geometry, locally bundled Manrope, independent brand
  mark and marketing copy; no reference-site assets or fake customer endorsements.
- First hero copy was initially transparent during entrance. It now stays visible
  on the first frame; only a small positional entrance and restrained lens motion remain.
- Recharts initial growth animations were disabled so data geometry is immediately readable.
- Form hints originally became part of implicit input names. Labels now have
  stable IDs and hints use `aria-describedby`; the actual browser workflow verifies them.
- Added an explicit demo reset when browser storage points to a missing dataset
  after changing project folders/databases, avoiding an ambiguous dataset selector.
- An initial JSX table closing-tag error was caught by the real production build,
  corrected, and followed by successful TypeScript/build runs.
- Primary button white text on blue was adjusted from approximately 3.30:1 to
  **5.10:1**, hover 4.92:1. Main muted text on panel is approximately8.65:1.
  These are limited color checks, not a claim of complete WCAG certification.
- Browser harness selectors were corrected for the visible V3 navigation suffix
  and Next's separate route-announcer alert. Assertions still cover the actual
  page, navigation and error UI. Mobile screenshots explicitly wait for app KPIs,
  rather than mistaking the landing preview's identical number for loaded app data.

## Actual screenshots

Captured from the running production application with synthetic data:

- [Homepage desktop](docs/images/premium/landing-desktop.png)
- [Overview desktop](docs/images/premium/overview-desktop.png)
- [Persisted handling history](docs/images/premium/history-desktop.png)
- [Optimization results](docs/images/premium/optimization-desktop.png)
- [Analytics](docs/images/premium/analytics-desktop.png)
- [Homepage mobile](docs/images/premium/landing-mobile.png)
- [Overview mobile](docs/images/premium/overview-mobile.png)

## Not Tested and known limits

| Scope | Status / limitation |
| --- | --- |
| Windows batch execution, native browser opening, D-drive/Unicode paths | **Not Tested**; Windows instructions and launcher source supplied |
| Full Windows/Python 3.14 or macOS matrix, Firefox/Safari | **Not Tested**; executed platform is Linux/Python 3.12/Chromium |
| Formal WCAG or assistive-technology certification | **Not Tested**; individual focus, label, contrast, mobile and reduced-motion checks performed |
| Public multi-user/production hosting | **Not Tested**; no authentication/tenancy, local trusted workspace only |
| Premium API 100,000-row/20MB sustained load and production concurrency | **Not Tested**; original ingestion limits retained, not a load guarantee |
| V3 planning beyond 500 orders in the premium UI | Not exposed; original V3 implementation remains available separately |
| Arbitrary uploaded V3 candidates/capacities | Not implemented; planning uses separately labeled synthetic inputs |
| Actual carrier quotes/availability, calibrated probabilities or economic value | **Not Validated**; no live API or real-world effectiveness claim |
| Settings shared with Streamlit's live session | Separate by design; case history is shared, web settings persist independently |
| What-if predecessor after page reload | Latest run persists; previous/current comparison is session-local, complete JSON runs remain in SQLite |
| Native Excel opening of exports | **Not Tested**; existing CSV escaping and Python parse checks retained |

The reference website returned an HTTP proxy 403 in this environment. The design
uses the user's brief as direction; no downloaded reference assets were used.
No mature vendor superiority, verified forecasting or commercial readiness is claimed.

## Conclusion

The delivered premium website and connected local platform pass the executed
core, API, production-build, browser and persistence checks. They are suitable for
a reproducible portfolio demo and controlled iteration while preserving Streamlit.
Windows desktop execution and real freight-forwarder decision effectiveness still
need their own validation and are not inferred from these passing checks.
