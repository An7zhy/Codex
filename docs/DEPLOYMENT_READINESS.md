# Deployment preparation — Sprint 2.5

This is a deployment kit, not public production acceptance. Use a separate hostname,
process set, writable filesystem, accounts and backups for each organization.
Never put real data into the synthetic demo image or make the full application's
operator/admin credentials public. No services are deployed publicly by these tests.

## Two separate operating modes

| Mode | Server policy | Source and persistence |
| --- | --- | --- |
| `business` (local default) | Existing authenticated viewer/operator/admin application; settings updates additionally require a durable version | Original V1/V2 snapshots and both V3 Synthetic Demo / Uploaded Data planning modes; SQLite history and settings remain persistent |
| `demo` | Anonymous, fixed synthetic viewer; explicit GET allowlist; every POST/PUT/PATCH/DELETE including login, uploads, comparison, solving and history writes returns403 before body parsing | New offline-generated sealed database pair, no accounts/sessions; exact canonical V1 source checked; files opened immutable read-only; one precomputed synthetic V3 experiment; no runtime database writes |

Demo mode is **not** `data_kind=synthetic_test` on an arbitrary upload. The server
requires `LOGISTICS_DEMO_ROOT`, rejects conflicting business database paths, checks
instance purpose, DB pair identity, size, hashes, canonical built-in source, zero
users/sessions/uploads, expected seed run and absence of live WAL files. Invalid,
modified, mixed or unsealed seeds return503. Liveness remains available.
The sealed manifest is an integrity/provisioning boundary in a read-only trusted
image, not a signature against a host administrator who can replace the application.

`python -m scripts.prepare_demo /absolute/new-demo-v1` creates a **new** directory;
existing paths are never overwritten and there is no `--force`. The directory must
be readable by the service UID and mounted read-only. To rebuild, create another
versioned directory/image, validate it and switch the demo instance while stopped.
Never initialize from a customer DB copy. Demo has no account creation/reset path;
visitors do not receive a business session or a shared privileged password.

## Local container demo

Requires Docker Engine/Desktop with Compose v2 and Linux containers. From repo root:

```bash
docker compose -f deploy/compose.demo.yml config --quiet
docker compose -f deploy/compose.demo.yml build
docker compose -f deploy/compose.demo.yml up -d
docker compose -f deploy/compose.demo.yml logs -f monitor
# Stop when finished:
docker compose -f deploy/compose.demo.yml down
```

Only `127.0.0.1:8443` is published. API8000, Next3000 and proxy health8080 have no
host port binding. The data plane network is Docker `internal`; only the TLS proxy
also joins the ingress network. Image EXPOSE metadata is not a published port.
No host business directory or Docker socket is mounted. Default URL is
`https://localhost:8443`; Caddy uses a **local CA**, not a publicly trusted certificate.
Trust only this temporary demo CA deliberately; do not disable verification in
real clients. The verifier obtains its public CA certificate with container exec
and checks chain and hostname. The browser check's local certificate exception
does not establish public certificate trust. Local CA state is tmpfs and changes
when the demo proxy is recreated; no production TLS state is reused.

Normal image builds fetch requirements/lockfile dependencies. In environments
where the Docker build network has no DNS, dependencies can be fetched on the
trusted build host, then installed offline. Cache directories are Git-ignored and
must not contain `.npmrc`, credentials or customer data:

```bash
python -m pip download --only-binary=:all: --dest deploy/build-deps/python pip==26.2.2 -r requirements-web.txt
cd web
npm ci --cache ../deploy/build-deps/npm-cache --no-audit --no-fund
cd ..
# POSIX shell; PowerShell uses $env:OFFLINE_DEPS="1" before the next command.
OFFLINE_DEPS=1 docker compose -f deploy/compose.demo.yml build
```

Base images are digest-pinned; npm uses its lockfile. Python top-level requirements
are pinned, but transitive wheel resolution is not a permanent supply-chain lock.
Retain the wheel checksums and image IDs from the accepted build; rescan future
builds and do not equate a successful image build with an OS-image CVE audit.

## Enforced budgets

| Boundary | Configuration / effect |
| --- | --- |
| API demo | 1 CPU,1GiB RAM,96PIDs; one Uvicorn worker,16 concurrent connections,backlog64,5s keepalive; root read-only,all capabilities dropped,no-new-privileges |
| API business container | 2CPU,1536MiB RAM,128PIDs; same connection/process policy; existing single solver lease,6/minute,45s child-process kill/wait |
| Frontend | 1CPU,768MiB RAM,128PIDs; Node heap512MiB,32MiB tmp and32MiB Next cache,read-only root |
| Proxy / monitor | 0.5CPU/256MiB/64PIDs and0.25CPU/128MiB/32PIDs; bounded tmpfs,read-only roots; container JSON logs10MiB×2 demo or×3 pilot per service |
| Demo queries | Global120 protected GETs/minute and2 API operations in flight,1024-byte query,empty GET body;429/413 feedback. One worker is required for this in-memory budget; health is liveness-only |
| Demo data | At most8MiB sealed DB pair; no uploads/online solving/DB writes; API tmpfs32MiB; rebuild instead of accumulating records |
| Business imports/storage | Existing whole-body20MiB,receive20s,100k V1 rows/128cols,XLSX64MiB declared expansion; planning500 orders/100services/5000options; JSON256MiB/1000datasets/200runs/100imports,10000cases |
| Settings metadata | CAS update and actor/time/version/diff in one SQLite transaction;10000 change records then explicit507. No silent history deletion; archive offline under the agreed policy |
| Business physical storage | Deployment preflight **requires** a dedicated filesystem at most1GiB with8MiB free reserve, and both DBs on it. It rejects an ordinary large host bind directory. This is independent of JSON quotas. API tmpfs128MiB is separate and bounded |

Container limits bound the process group, not each individual parser invocation.
Large authenticated input can still degrade/restart the business API within that
envelope. No per-upload isolated parser worker or production performance SLA is
claimed. Do not start remote pilots until representative peak/concurrent inputs
have been tested on the intended host. The demo avoids that parser exposure by
rejecting all uploads/POSTs. A three-second solver may return UNKNOWN under load;
that state remains truthful and is never converted into a feasible/optimal claim.

## Protected pilot: manual prerequisites

1. Choose an organization-specific host, private OS directories and encrypted
   storage/backups as appropriate. Provision a **new persistent bounded filesystem**,
   owned by UID/GID10001 with0700 directory permissions. Linux host administrator
   example: review `deploy/prepare-pilot-storage.sh` before invoking it with new
   image/mount paths. It creates a512MiB ext4 image with nodev/nosuid/noexec; it does
   not configure encryption, persistent mounts, off-host backups or Windows ACLs.
   Never format an existing device or point this script at a business directory.
2. Copy `deploy/pilot.env.example` to a private, ignored env file and set exact
   HTTPS origin, hostname, TLS contact, bounded data root and a separate private
   TLS state directory. TLS directory must be writable only by UID10001/ops.
3. Validate/build the pilot Compose file with `--env-file <private file>` and
   `-f deploy/compose.pilot.yml`. Use a distinct `-p org-a` project name consistently
   for each organization; the file's default name represents one pilot only.
   Before starting it, provision invited accounts
   offline with `docker compose ... run --rm --no-deps api python -m scripts.manage_access setup`.
   Passwords are entered via hidden prompt, never in Compose/env/command arguments.
4. Start privately. Default host binding is still127.0.0.1:8443. Actual DNS,
   publicly reachable ACME/TLS-ALPN challenge routing, external ingress/Host allowlist,
   firewall/ACL and certificate trust require explicit operator work and separate
   acceptance. `Caddyfile.pilot` is an ACME example; do not run it against fictitious
   domains or claim a local CA test validated a public certificate.
5. Test anonymous denial, viewer403, exact Origin, DB instance isolation, config
   conflict409, all intended input sizes and restored login on that target.
   Do not expose the local Streamlit fallback. Keep its separate local demo copy.

The bounded tmpfs pilot rehearsal is **disposable** and does not prove durable
disk storage or production filesystem ACLs. Production must use a persistent
bounded filesystem, not tmpfs. Do not bypass the storage preflight to make an
unbounded bind directory appear ready.

## Monitoring and recovery

`/api/health` is liveness; `/api/ready` validates DB binding and deployment storage
(or the sealed demo). Container API health uses readiness; web health checks its
page shell; proxy health8080 checks its own process only. The monitor polls API
readiness, the web shell and internal proxy health every15s. Three failed polls
emit JSON `ALERT` to local container logs; recovery emits `RECOVERY`. Failed
checks are local notifications, **not delivered email/paging**. Assign an operator
and route these bounded logs to your chosen alerting system before a real pilot.
Container `unless-stopped` restarts crashed processes; Docker alone does **not**
restart a running-but-unhealthy process. Operators must investigate unhealthy
states, disk reserve and data errors rather than repeatedly masking them.

For demo failure, stop/rebuild/recreate the sealed image; no customer data needs
recovery. For business operations, follow `PILOT_OPERATIONS.md` and:

1. Assign retention and backup ownership/RPO/RTO before data admission. Stop API,
   Next, Streamlit, workers and every custom writer; default-port checks do not
   establish global quiescence across containers. `docker compose ... stop` must
   finish before running maintenance in a separate one-off container.
2. Take native backup with `scripts.maintain_data --offline-confirmed backup` to
   a private separately mounted backup directory, not the active data filesystem.
   Keep off-host copies under the agreed policy. It captures both DBs, identities,
   checksums and table counts including settings versions/change metadata.
3. Restore to a **new** directory on a new bounded persistent filesystem using
   `... restore <backup> <new-directory>`. Checksums/integrity/identity are checked;
   old sessions are revoked. Switch BOTH DB paths/mount only after fresh-login
   checks of KPIs, cases, settings version and planning source/results.
4. Run `... retain --dataset-days 30 --run-days 30 --case-days 180` offline only
   under the data owner's policy. Plan VACUUM temporary space before disk reserve
   is exhausted. Dataset/linked-case and planning/linked-run deletions are admin
   APIs in the full application; demo mutations remain forbidden.
5. Logical deletion does not delete backup copies or guarantee forensic erasure.
   Expire copies under the agreed policy. Keep configuration-change metadata until
   archived under that policy; the10000-record guard returns507 rather than silently
   discarding evidence. Do not confuse a local restoration rehearsal with a verified
   production backup schedule/off-host RPO/RTO.

## Settings API contract

`GET /api/settings` returns `priority`, durable `version` and capabilities.
`PUT /api/settings/priority` requires the full priority configuration **plus**
`expected_version` (strict positive integer). A stale version returns409, never an
automatic retry/overwrite. Successful response is `{priority, version}`. An admin
can page `GET /api/settings/priority/history`; viewer/operator access is denied.
The UI keeps a draft's original base version across route changes/refresh, shows
conflicts and offers **Reload latest settings**, explicitly discarding that draft.
Even changing values back invalidates old Decision Center comparison tokens because
the durable version participates in the fingerprint. Saved cases retain that version.

## Revalidation and remaining acceptance

Run full pytest, frontend typecheck/build, `python -m scripts.verify_sprint_2_5`,
then `python -m scripts.verify_deployment` after building images. The latter uses
localhost only, synthetic containers, a deliberate32MiB disposable OOM test,
bounded tmpfs and failure/recovery polls, and cleans its containers/networks.
It is not a penetration test or an infinite-load benchmark. Use a separate trusted
machine/organization project if other work already uses the default demo project
or8443; the verifier refuses an already occupied demo project before cleanup.
Do not stop containers you did not create.

Still requires manual verification: public TLS/DNS/ingress, real host/backup ACLs,
persistent bounded volumes, target peak/soak load, external alert delivery,
scheduled/off-host backups and RPO/RTO, Windows native installation, authorized
business samples/SLA/quote/capacity validity. Uploaded optimization is deterministic;
no real late-probability or commercial-benefit claim follows from synthetic tests.
