# Phase 1 validation

The following checks were actually executed in the current Linux cloud workspace
with Python 3.12.14. This is current-instance evidence, not a claim that the app has
been published, pushed to GitHub, or tested on Windows/macOS.

## Dependency and Python checks

- Installed `requirements.txt` into a project-local `.venv`.
- Installed `requirements-dev.txt` for the optional browser checks.
- `python -m pip check`: **No broken requirements found**.
- `python -m compileall -q app.py src tests`: **passed**.
- Imported `app` and every `src` module: **passed**.
- Reran the complete cloud install script on the existing environment: **passed**.

## Standard tests

`python -m pytest -q`: **49 passed**, with no test warnings in the final run.

The suite covers hand-calculated KPI denominators, no delayed shipments, all
shipments in transit, malformed/ambiguous/out-of-range dates, missing actual
delivery, duplicate/missing IDs, empty tables/files, insufficient cost samples,
outlier thresholds, directional groups, chronology and status conflicts,
zero/negative/non-finite costs, UTC offsets, early deliveries, input immutability,
CSV and Excel ingestion, report figures, CSV formula escaping, and Streamlit
filter/empty-state behavior.

## Running app and real-browser acceptance

Started the actual service with:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

The internal `/_stcore/health` request returned **200 / ok**. Playwright 1.62.0
with the environment's system Chromium then executed:

```bash
BROWSER_EXECUTABLE_PATH=/usr/bin/chromium .venv/bin/python tests/browser_smoke.py
```

All acceptance checks passed:

- Default demo: seven metric values and four rendered Plotly charts.
- Actual CSV and Excel file selection/upload through the browser.
- Calculated KPIs, exception view and 19 findings on 17 data quality rows.
- Downloaded processed CSV (160 rows), nonempty exceptions CSV, and the English
  Markdown report for **both** upload formats; checked their actual contents.
- Filtered report containing only the selected shipment.
- No-match filter, rejected missing-column upload, and valid header-only upload.
- Mobile viewport 390 × 844 without page-wide horizontal overflow.
- No Streamlit exception elements or JavaScript page errors during the successful run.

During testing, sequential downloads exposed unnecessary Streamlit reruns. All
download buttons now use `on_click="ignore"`; the complete browser flow was rerun
successfully after that fix. Mixed-type original values are converted to display
text in the quality table to avoid Arrow serialization fallback.

Screenshots: [desktop](images/demo-desktop.png), [mobile](images/demo-mobile.png).
Browser downloads and additional artifacts remain under ignored `artifacts/browser/`.

## Synthetic-data cross-check

At the inclusive UTC reference date **2026-10-01**, both file formats yielded:

| Measure | Result |
| --- | ---: |
| Input rows | 160 |
| Retained unique identified shipments | 158 |
| Verified delivered / eligible completed deliveries | 91 / 90 |
| On-time / delayed completed deliveries | 43 / 47 |
| On-time rate | 47.8% |
| Mean positive completed delay | 36.5 hours |
| Overdue in transit | 30 |
| Valid cost records | 155 |
| Total cost | USD 539,830.75 |
| High-cost flags | 4 |

The actual report is in [sample_report.md](sample_report.md). Data and findings are
fictional. No real carrier API, external LLM, real-world accuracy study, remote CI
run, or validation in a restored/new cloud task was performed.
