# Single-organization pilot operations — Sprint 1

This is an invited, **single organization per independently deployed instance**.
It is not shared multi-tenant SaaS. Each organization's process, writable directory,
database pair, cookie hostname and backup access must be separate. Never point two
organizations at the same database pair or expose the Streamlit fallback remotely.
All members within one organization intentionally share its shipments, settings,
case history and experiments. Client tenant/role headers grant no permissions.

## First run and accounts

Install `requirements-web.txt` for the API runtime; it no longer installs Streamlit,
Pillow, pytest or browser automation. Install `requirements-dev.txt` to test both
interfaces. Upgrade the installer with `python -m pip install --upgrade pip==26.2.2`.
Use a fresh web-only venv for deployment. If reusing an older V1/V2 venv, install
the updated `requirements.txt` too, to upgrade existing fallback dependencies;
the Windows launcher detects that case. Installing only web requirements does
not uninstall or patch unrelated old packages already in a reused environment.

```bash
python -m scripts.manage_access setup
# Alternatively, explicit offline provisioning:
python -m scripts.manage_access init --organization "Your organization"
python -m scripts.manage_access user alice --role admin
python -m scripts.manage_access user bob --role operator
python -m scripts.manage_access user carol --role viewer
python -m scripts.manage_access disable carol
```

Passwords are entered via hidden terminal prompts, at least 12 characters, with
no default credentials, public signup, password-in-command arguments or stored
plaintext. Accounts use salted scrypt hashes (N=32768, r=8, p=1); random opaque
sessions are stored only as SHA-256 hashes, last eight hours and survive restart.
Logout, disabling or resetting an account invalidates its sessions. Reset/role
changes use the offline `user` command and revoke existing sessions. Password
recovery requires the trusted instance administrator; no email reset/MFA/SSO.

| Role | Allowed |
| --- | --- |
| viewer | Organization reads, exports, hypothetical decision comparison |
| operator | Viewer plus uploads, case save/update, synthetic optimization |
| admin | Operator plus scoring settings and deletion |

Every sensitive API (including direct port 8000 access, uploads, exports and
history) checks the database session and role before processing the body. The
Next page shell contains no business data. Login/logout use HttpOnly,
SameSite=Strict cookies scoped to `/api`; unsafe requests require an exact
allowlisted Origin and reject cross-site fetch metadata. CLI API clients must
log in, retain the cookie and supply the configured Origin on writes. Cross-origin
credentialed CORS is not enabled; public API documentation is disabled.

## Local versus remote pilot configuration

Local defaults allow `http://127.0.0.1:3000` and `http://localhost:3000`; the launcher
also handles its explicit `--port` value. HTTP cookies are allowed only for local
development configuration. Remote operators must set these environment variables
in the service manager **before** starting the app:

```text
LOGISTICS_PILOT_MODE=1
LOGISTICS_COOKIE_SECURE=1
LOGISTICS_ALLOWED_ORIGINS=https://pilot.your-domain.example
LOGISTICS_WEB_DB_PATH=/private/org-a/workspace.sqlite3
LOGISTICS_DB_PATH=/private/org-a/history.sqlite3
```

Pilot mode rejects API operation with insecure cookie/HTTP-origin configuration;
Streamlit displays a stop message before accessing shipment/history data. The
normal local fallback remains `python -m streamlit run app.py`, loopback-bound.
Use a separate local demo copy for that fallback during a pilot.

Deploy one API instance behind a trusted HTTPS reverse proxy, keep port 8000
and the Next origin private, restrict hosts at that ingress, disable request-body
logging, set a 20 MiB total body cap and connection/header/time limits there too.
Set TLS/security headers at the proxy, use private OS accounts/volumes, restrict
directory ACLs and encrypt volumes/backups as appropriate. POSIX-created access
DBs/backups use mode 0600 and new private directories use 0700; existing parent
directories and Windows ACLs must be checked by the operator. These deployment
controls and real public HTTPS **have not been verified in this Linux test run**.

Two databases are server-bound to the same generated instance identity; mixing
a history DB from another instance returns 503. Do not clone one organization
into another and keep its accounts/sessions. An authorized restoration retains
the same organization identity and revokes all restored sessions.

## Import contract and decisions

The file must follow the existing canonical schema; this is not universal column
mapping. Preview and confirm the exact file/date before import. The preview
discloses samples, issues, duplicate source rows and date precision counts.

- ISO dates/timestamps only. Naive values mean UTC; explicit offsets convert to
  UTC. A date-only deadline means **00:00 UTC**, not end of day. Convert local
  time/EOD promises explicitly before upload, with the data owner's agreement.
- One snapshot per shipment. Duplicates keep the first occurrence and exclude
  subsequent rows, including conflicts; do not upload an event stream as snapshots.
- USD-only costs. No currency metadata means the importer confirms prior USD
  conversion. Any supplied currency/cost_currency/shipping_currency column must
  be USD on that row; blank/non-USD rows are excluded from cost KPIs, thresholds
  and reports with a quality finding. No exchange rates or conversions are inferred.
- Numbers follow US convention: `1,234` means 1234. Weight/volume/unit aliases
  are not automatically converted. Remove unnecessary personal/customer columns
  before upload; extra columns remain authorized organization data.
- V2 needs its documented evidence fields. Missing evidence stays insufficient
  information, not guessed risk. Case outcomes do not rewrite shipment snapshots.
- Compare first, then save an available applied action. Changed scoring/data
  context returns 409 until recomparison. The saved score/context and actor are
  recorded; this is not a complete immutable business audit ledger.
- V3 remains a separate synthetic planning sandbox with assumed distributions,
  not optimization of uploaded customer orders or a validated carrier prediction.

## Runtime and storage budgets

| Boundary | Enforced behavior |
| --- | --- |
| Entire ASGI request | 20 MiB for dataset routes, 256 KiB otherwise; Content-Length and received chunks checked before multipart parsing; 20 s body receive budget |
| Multipart/files | One file part; 20 MiB total includes overhead, so selected file must be smaller; 100,000 rows, 128 columns |
| XLSX | Before openpyxl: at most 1000 parts and 64 MiB declared expansion; high compression ratio rejected; defusedxml installed |
| API/session rate | 180 protected requests/min/account; upload and preview together 10/min/account |
| Login | 30/min/instance and 5/5min/account-name, including unknown users |
| Solver | One shared SQLite lease/instance, 6 submissions/min/instance; orders×scenarios ≤1,000,000; at most 500 orders, 10,000 scenarios and 10 s search/strategy |
| Worker wall time | Separate process, killed and waited on at 45 s; no run saved on timeout; concurrent request 429, timeout 504 |
| Workspace JSON | At most 1000 datasets, 200 runs and 256 MiB combined raw/run JSON; atomic quota checks, 507 on exhaustion |
| History/log retention | New web cases capped at 10,000; idempotent retries reuse existing cases; access metadata latest 10,000 events and at most 90 days |

These are bounded MVP controls, not an OS sandbox or a measured production SLA.
XLSX/analysis still runs within the API's resource envelope, without an enforced
parser process CPU/RAM limit. Enforce container/OS limits and validate peak memory
and concurrency on the intended host before remote use. A worker abnormal crash
may leave a lease until its 120 s expiry. Client cancellation is not server
cancellation. Rates/quota policy are intentionally simple, not a distributed queue.

Exception and active-decision queues use server pages and ID search; a 500-row
workspace summary is only a preview. Case queries have offset/limit and the UI
offers history pages. History CSV exports **all** organization cases, not 1000.

## Deletion, retention, backup and restore

An admin can select an uploaded dataset in Settings, type DELETE, and remove it
and its linked web case snapshots. Demo data cannot be deleted. Run deletion is
also available via authenticated `DELETE /api/optimization/runs/{run_id}`.
CLI retention deletes expired datasets (and linked cases), runs and old cases,
then VACUUMs both DBs. Unlinked original Streamlit cases follow the case retention
period. A deleted active dataset becomes unavailable; other browsers must choose
a valid dataset. Logical deletion does not erase separate backups or guarantee
forensic removal from storage hardware.

**Stop both interfaces and all writers before offline maintenance.** The CLI
requires acknowledgment and rejects active default API/Streamlit ports 8000/8501.
This check cannot discover every custom port/host or external writer; operators
must verify all services are stopped. Do not copy only active WAL main files.

```bash
# From repository root, after Ctrl+C in the launcher and Streamlit terminals:
python -m scripts.maintain_data --offline-confirmed backup backups/pilot-2026-10-28
python -m scripts.maintain_data --offline-confirmed restore backups/pilot-2026-10-28 restored/rehearsal
python -m scripts.maintain_data --offline-confirmed retain --dataset-days 30 --run-days 30 --case-days 180
```

Backups use native SQLite backup for both stopped databases, a shared instance
identity, per-file SHA-256, integrity and table counts. Restore checks these and
creates a **new directory**, never overwriting the current pair. Set BOTH database
environment paths to the restored files to rehearse startup; log in afresh and
verify KPIs/cases/settings/run. If rejected, preserve the originals and investigate.
The manifest/hash detects corruption, not malicious tampering by an attacker
with backup write access. Treat backups as confidential, including account hashes.

Before the first pilot, agree retention with the data owner. Suggested initial
policy: source/run 30 days, cases 180 days, backup copies 14 days; operator reviews
and runs maintenance daily, takes an offline backup at least daily and before
upgrades, and stores a private off-host copy. This is a **manual operating policy**,
not a scheduler shipped in the application. RPO≤24h is only an operator target,
not demonstrated service performance. Measure restoration time on the pilot host,
assign an owner and rehearse before admitting real data. Do not delete the only
known-good recovery copy without the agreed retention/recovery plan.

## Acceptance boundary

Run `python -m pytest -q`, `npm run typecheck`/`npm run build` in web/, and
`python -m scripts.verify_hardening` (dev dependencies and Chromium required).
Use temporary DBs, never production files. Old scripts.audit_readiness describes
the pre-hardening audit and deliberately assumed anonymous writes; use the new
verification command for this branch. See the updated audit for actual results.

Before remote pilot: verify TLS/ingress, ACLs/backups/restore, account separation,
the intended Windows/Linux environment and a consented customer sample with a
human reviewer. Synthetic numerical tests do not establish commercial benefit.


## Sprint 2 additions

`planning_imports` is in the same protected workspace DB and bound organization
instance. Preview/invalid/confirmed records share the existing256MiB JSON budget
and have a100-record cap. The same20MiB full-body/10 upload requests per minute
applies to planning preview; four CSV file parts or one XLSX are permitted.
New row budgets are500 orders,100 services,5000 options and1 constraints row.
Both uploaded and synthetic solves share the same instance-wide lease,6/min rate
and45-second child-process wall cap. No risk simulations are added to user inputs.

Admin deletion removes a planning import and linked runs. A deleted source cannot
be saved back by an in-flight solve. Offline retention expires imports using the
dataset-day policy and removes linked runs. Native snapshot/restore includes the
new table automatically; no extra database or user-owned cloud storage is added.
An instance with no exception cases yet is now a valid retention input.

Per-account/per-instance tab draft storage is not an authorization mechanism.
Logout clears drafts; selection/filter settings contain IDs/filters in scoped
localStorage. Review local workstation access and avoid unnecessary sensitive
notes. See PLANNING_INPUT_CONTRACT.md and SPRINT_2_REPORT.md for verified scope.
