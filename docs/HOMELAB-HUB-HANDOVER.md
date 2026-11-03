# HomeLab-Hub — development handover

Updated 2 November 2026 for OpenCode / DeepSeek Flash, Codex and other maintainers.

- Repository: `smith844/homelab-hub`, originally forked from `RaidOwl/homelab-hub`.
- Integration branch: `feature/homelab-redesign`.
- Functional baseline reviewed: `e1e595bdba82e5161abb8a1136380e389a3bd633`
  (Phase 4 reconciliation). This documentation commit follows that baseline.
- Phases 1–3, Phase 3 polish and the first Phase 4 slice are committed on the
  development branch. The owner's verified Betty findings are recorded below.
- Read [AGENTS.md](../AGENTS.md) first. Current code, Git history and the owner's
  latest instructions take precedence over historical phase reports.

No application functionality or deployment is part of this handover. It contains
configuration **locations and variable names**, not credential values.

## Current application and architecture

HomeLab-Hub is a Flask application serving a compiled Svelte SPA with SQLite.
It records hardware, VMs/runtimes, applications, storage/shares, networks, other
devices and documents. The Graph, Grouped and Tree presentations share inventory.
Container Groups manages imported/manual grouping; Reconciliation compares saved
observations with inventory and offers reviewed container changes.

- Production Dockerfile: Node 24 frontend build; Python 3.14 Alpine runtime.
  Backend: Flask 3, SQLAlchemy 2, Flask-SQLAlchemy, Alembic, Gunicorn.
- Frontend: Svelte 4, Vite 5, Cytoscape + dagre, Pico CSS, ByteMD, hash routing.
- Gunicorn uses **one worker**. Preserve that assumption unless SQLite writes and
  reconciliation preview-signing behaviour are deliberately redesigned.
- SQLite image default: `/data/homelab-hub.db`; `DATABASE_URL` is configurable.
- `backend/docker-entrypoint.sh` runs `alembic upgrade head` before serving.
  `create_app()` also calls `db.create_all()`; this does not replace migrations
  when upgrading existing tables.
- No Docker socket is required by the web app. It does not run nmap or Docker
  collection. A separate host-side exporter (`scripts/docker-snapshot.sh`) produces
  uploaded container snapshots, and a separate token-authenticated scanner
  (`scanner/`) performs approved Nmap scans. Optional read-only UniFi Network
  Integration evidence is fetched through `services/unifi.py` with server-side
  `X-API-KEY` authentication and an in-memory cache. Neither collector is scheduled
  by the web app, and neither shares a database.
- Reconciliation consumes uploaded Docker JSON and read-only network observations.
  The web app proxies scan start/status to the separate scanner; it never calls the
  upstream scanner's direct inventory-import endpoints.
- Group and reconciliation writes require the shared admin token. Legacy inventory,
  import, document and map write APIs remain largely unauthenticated; the app is
  intended for a trusted LAN and is not hardened for public exposure.

### Important files

| Area | Entry points |
|------|--------------|
| App/config/models | `backend/app/__init__.py`, `config.py`, `models/` |
| Group API/import | `routes/container_groups.py`, `services/folderview_import.py` |
| Identity/resolution | `services/group_identity.py`, `group_resolution.py`, `group_customisations.py` |
| Group backups | `services/group_backup.py`, `routes/inventory.py` |
| Reconciliation | `routes/reconciliation.py`, `services/reconciliation.py` |
| Reconciliation exclusions | `models/reconciliation.py`, migration `011_reconciliation_exclusions` |
| Network discovery | `routes/network_discovery.py`, `services/network_discovery.py`, `pages/NetworkDiscoveryPage.svelte`, `lib/networkScan.js` |
| Network-wide matching | `services/network_wide_reconciliation.py` (read-only host/service evidence) |
| UniFi enrichment | `services/unifi.py` (official read-only Integration API + cache), `docs/unifi-integration.md` |
| Network scanner service | `scanner/hlh_scanner/` (target validation, Nmap XML, jobs, HTTP API) |
| Input/identity adapters | `services/discovery_adapters.py`, `discovery_identity.py`, `network_reconciliation.py` |
| SPA/navigation | `frontend/src/App.svelte`, `components/Sidebar.svelte`, `lib/sidebarTools.js` |
| Management pages | `frontend/src/pages/GroupsPage.svelte`, `ReconciliationPage.svelte` |
| Maps | `pages/MapPage.svelte`, `components/map/NetworkMap.svelte`, `TreeView.svelte`, `TreeNode.svelte` |
| Map logic/icons/theme | `frontend/src/lib/grouping.js`, `mapViews.js`, `groupIcons.js`, `frontend/src/theme.css` |
| Tests | `backend/tests/`, `frontend/tests/`, `frontend/tests/browser/` |
| Docker snapshot exporter | `scripts/docker-snapshot.sh`, `docs/docker-snapshot-exporter.md` |
| Test deployment | `scripts/deploy-betty-test.sh` |
| Test scanner deployment | `scripts/deploy-betty-test-scanner.sh`, `docs/scanner-betty-test-deployment.md` |

Backend paths in this table are relative to `backend/app/` unless shown otherwise.

## Database and migrations

Inventory models include `Hardware`, `VM`, `AppService`, `Storage`, `Share`,
`Network`/`NetworkMember`, `Misc`, `Document`, and legacy map/layout relationships.
An application belongs to hardware or a VM, not both. The current SPA's layout
coordinates and manual anchors live in browser storage, not inventory exports.

Migration chain, in order:

`001` → `002` → `003` → `004` → `005` → `006` → `007` →
`add89462ccd0` → `008_add_mac_address` → `009_container_groups` →
`010_group_customisations` → **`011_reconciliation_exclusions`**.

- `009` creates groups, imported assignments and manual overrides. Downgrading it
  drops grouping data.
- `010` adds only nullable **`container_groups.customisations_json TEXT`**:
  no default, backfill, index, foreign key or new table. Existing rows receive NULL;
  existing group IDs, assignments, overrides and active/archive values are retained.
- `010` explicitly inspects whether the column exists, skipping only the existing
  column case. Unexpected inspection/SQL errors propagate. Regression tests cover
  a populated Phase 3 upgrade, existing-column preservation and read-only DDL failure.
- Its downgrade drops the ownership-tracking column and loses those flags.
- `011` adds only the **`reconciliation_exclusions`** table (host/name uniqueness,
  host index, nullable label/reason, timestamps). It does not alter inventory,
  grouping or Docker. Downgrading it drops stored exclusion policy rows only.
- Reviewed reconciliation identity and observation metadata still needs **no schema
  migration**: it uses a reserved `hlh-discovery:v1` JSON comment in application
  notes.

**Back up the database before migrations. Approval is required before applying
migrations to live data.** Old images predating 010 cannot start normally against
a revision-010 database: their startup Alembic command does not recognise 010.
The same applies across 011: a pre-011 image does not recognise the new revision,
even though the migration is additive. Rollback across either boundary requires
**both the previous image and its matching pre-migration database backup**, not an
image-only switch or a falsified version stamp. See the deployment section for the
shared-volume consequence.

## Identity, grouping and backups: invariants to preserve

- Logical container identity is **normalized root hardware host + Docker name**,
  case-insensitive and whitespace-normalized. Docker container/image IDs are
  observations, not permanent identity. Never group Betty and Blackbox by their
  identically named `Docker` VM/runtime parent.
- `group_identity.py` resolves the Docker name in this precedence:
  reviewed reconciliation metadata; a structured Docker configuration notes block
  containing `Container: <name>`; explicit `Docker container: <name>` description;
  finally the application display name. Ordinary notes alone do not imply Docker.
- A manual group override wins over an imported assignment. An override with
  `group_id = NULL` means **explicitly Ungrouped**. Inactive groups produce no
  effective membership but retain their assignments for restoration.
- The FolderView importer owns imported assignments and never edits manual
  overrides. A reviewed reconciliation manual match may move an override from
  the old logical name to the selected new name, preserving the choice. Conflicting
  overrides or ambiguous identities block the action.
- `metadata_json` retains raw FolderView source metadata; `customisations_json`
  tracks locally owned icon/order/active choices. Colour stays locally owned.
  Legacy rows conservatively preserve ordering/inactive state and infer icon edits
  from the saved source snapshot. An old automatically archived group can therefore
  require explicit restoration. There is no UI to relinquish local ownership yet.
- Reconciliation retains existing app IDs, names, parent, icon, user notes and
  imported memberships. Missing ID observations do not clear last-known metadata.
  Preserve its reserved notes marker when editing notes or extending an importer.
- Inventory JSON export/import includes group natural keys and ownership flags;
  existing application notes carry reconciliation metadata through backup/restore.
  JSON import is an existing destructive replacement operation, not a safe merge.
  Imported group keys include host/external ID; manual keys currently use only the
  normalized name, so same-named manual groups on different hosts can collide in
  JSON export. Prefer a consistent SQLite backup for operational rollback.
- Renaming a hardware host changes its identity scope. Duplicate container names
  on a host are ambiguous; block automatic resolution rather than guessing.

## Phase 3 and map polish: delivered

Container Groups (`#/groups`) provides host filtering, manual creation/editing,
archive/restore, guarded deletion, per-app assignment, explicit Ungrouped, revert,
unmatched membership reporting, and protected FolderView preview/apply.
Imported names remain owned by FolderView. The importer reads its file only;
nothing writes back to `/boot` or schedules synchronisation.

`POST /api/container-groups/sync` accepts `host_key` and `dry_run`; the report now
contains named group changes, field-level before/after values, source metadata
changes and preserved local choices. Timestamp/source-only changes are explained
rather than represented only by a counter.

Group images use validated image URLs/raster data and fallbacks. ViewBox-only
SVGs (the actual FolderView shield and AI assets) need explicit image dimensions
before Cytoscape's source-rectangle draw; `groupIcons.js` prepares isolated image
resources without injecting SVG into the page. Artwork, animation and viewBox are
retained. Cards remain **220 × 92**, with a 24px centred icon at 10px top clearance,
name/count text below, and consistent expanded/collapsed styling. Do not restore
`background-fit:contain` on these cards: it enlarges icons to the card footprint.

Graph and Grouped positions are separate. Group IDs, anchors and edge/expansion
logic survived the polish changes. Theme tokens and button alignment cover both
light and dark modes. Playwright covers real canvas output, wrapping, anchors,
expansion, Graph/Tree controls, and exact SVG fixtures at 75%, 100% and 200% zoom.

Browser-local keys include `hlh.mapViews`, `hlh.mapCurrent`,
`hlh.mapLayout.<signature>`, `hlh.mapLayoutGrouped.<signature>`,
`hlh.mapGroupAnchors.<signature>`, `hlh.mapGroupExpanded`, `hlh.sidebarToolsOpen`,
`hlh.theme` and `hlh.siteName`. `hlh.adminToken` is **sessionStorage only**. Do not
clear or change these keys casually; inventory export does not back up browser layouts.

The sidebar keeps Network discovery and Reconciliation in a separated, collapsible
**Tools** group. Its expanded/collapsed preference is remembered in
`hlh.sidebarToolsOpen`; a Tools page always expands it on activation, without
overwriting the saved preference. All other navigation groups and the running-scan
indicator remain outside the Tools group.

## Phase 4: delivered slice and verified Betty findings

Reconciliation (`#/reconciliation`) compares host-scoped observations against
inventory and imported grouping. Reads/previews are read-only; `/api/reconciliation/apply`
requires admin authentication and a signed, reviewed preview. Previews expire after
ten minutes or server restart and reject concurrent inventory/grouping changes.
SQLite state checks and writes are serialized. Nothing automatically deletes apps.

It distinguishes stable identity matches, additions, changed runtime/image metadata,
unknown versus confirmed-absent recorded Docker identities, duplicate identities,
FolderView-without-inventory and intentionally or otherwise ungrouped apps.
Single-resource matching, metadata updates and additions remain available. Reviewed
**bulk metadata updates** now preview all confidently matched containers and apply
only container ID, image ID, image reference and observation time in one transaction;
they never create or delete applications or touch names, notes, parents, grouping or
map data. Host-scoped **exclusions** persist in `reconciliation_exclusions`, move
selected unmatched containers out of ordinary warnings into a separate visible list,
and never infer from name prefixes or alter Docker/inventory. Dashboard summaries and
filters separate matched, unmatched, excluded, uncertain and not-seen resources.
There is still no automatic background reconciliation, reviewed bulk *addition* or
scan history.

A container snapshot must explicitly declare successful complete `all_containers`
coverage, include stopped containers, contain an explicit array, and have a valid
completion time within 24 hours before absence can be inferred. Failed, partial,
running-only, missing, future-dated or outdated scans do not prove absence. Newer
recorded observations prevent older snapshots from regressing metadata or asserting
current absence. These are uploaded declarations, not independent live probes.

### Owner-verified Docker comparison on Betty

Reported by the owner for this handover; recorded 2 November 2026. These are
point-in-time **Betty** observations, not repository fixture totals, Nmap results,
or a new live inspection by the handover agent.

| Finding | Count / interpretation |
|---------|------------------------|
| Docker containers discovered | **93** |
| Represented by application inventory records | **86** |
| Explicitly excluded historical deployment containers | **7** |
| Unmatched ordinary containers | **0** |
| Inventory applications without a discovered container match | **0** |
| Recorded container/image IDs | Not yet recorded in most inventory entries |

Thus 93 = 86 + 7. The seven excluded containers are explicit host-scoped policy
decisions, not deletion and not proof that the containers are gone. **Do not delete
backups or automatically add containers to make counts look clean.** A first recorded
ID is missing metadata being filled, not proof that a resource was recreated.

Earlier seven unmatched FolderView entries and eleven ungrouped apps were separate
grouping investigation targets; they are not the current Docker snapshot
discrepancies.
Their latest counts were not supplied here, and intentional Ungrouped choices remain
valid. Do not infer they were resolved from the zero unmatched-inventory result.

## Nmap network discovery: upstream boundary and Phase 5 integration

Upstream source: `dpinna13/homelab-hub`, branch `feature/network-scanner`, commit
**`9feebd509ae58ad98bc7fc8881100b51e6add357`**. Its verified routes are POST
`/api/scanner/discover`, `/identify`, `/portscan`, `/probe-http`,
`/import/hardware`, `/import/apps` and GET `/api/scanner/interfaces`,
`/status/<scan_id>` (all paths after the first share the `/api/scanner` prefix).
It provides Nmap IPv4 discovery, reverse DNS/MAC hints, device/OS identification,
TCP port/service scanning and HTTP probing. It **does not discover Docker
identities, container/image IDs or Docker inventory**, and its jobs are in memory
(completed/failed expire after 600 seconds).

The Phase 5 integration adapts the sound parts into `scanner/hlh_scanner/` and does
not copy unsafe behaviour:

- Reuses the host-discovery flags (`-sn -PR -PE -PS… -PA80`), MAC/vendor parsing,
  unprivileged `-sT` service scanning and threaded job lifecycle.
- Replaces `python-nmap`/`requests` with argument-safe `subprocess` + Nmap XML, and
  adds explicit UTC start/completion timestamps, partial-scan status and bounded
  retention.
- Uses explicit approved private IPv4 ranges, max 1024 target addresses, max 256
  ports, bounded scan duration and concurrency. Targets are never derived from VLAN
  numbers or interfaces.
- Prohibits OS fingerprinting/aggressive probes, NSE scripts, HTTP probing and
  scanner-side database imports. No Docker socket is used.
- Exposes `POST /api/scanner/scan` and `GET /api/scanner/scan/<id>` behind a shared
  `X-Scanner-Token`. The web app proxies them through admin-authenticated
  `/api/network-discovery/scan`; it validates targets independently and never
  forwards raw nmap flags.
- Scan status is `completed`, `partial` or `failed`. Partial/failed results remain
  visible for review but never imply device absence. The existing network adapter
  classifies observations as matched/unmatched/duplicate/unverified only; network
  ports are not Docker identities.
- The active scan is stored per browser tab in `sessionStorage` and restored after SPA
  navigation or refresh by re-reading scanner status; polling resumes without a new
  scan submission. Duplicate starts are disabled while active and a compact sidebar
  indicator shows the running target. Scanner `404` (job expired/restarted) clears the
  running state with an explicit notice, while `503`/TLS failures keep the saved scan
  and offer manual retry. Completed results are re-fetched and re-matched for review
  while the scanner retains them. No scan is ever restarted automatically and scanner
  concurrency is unchanged.
- The Network discovery page uses a dedicated read-only **network-wide matcher**
  (`services/network_wide_reconciliation.py`) across hardware, VMs, other devices,
  application endpoints and network memberships. It separates host-level device
  matches from service-level IP+port matches, labels matched/plausible/shared/
  ambiguous/unmatched/unverified evidence, and supports expandable candidate details.
  It never adds inventory, edits records or changes map layouts. See
  [network-discovery.md](network-discovery.md) for exact execution, configuration,
  API and matching rules.
- **Optional UniFi enrichment** uses the official local Network Integration API
  (`X-API-KEY`, `GET /proxy/network/integration/v1/...`: info, sites, adopted
  devices, connected clients), HTTPS verification with an optional CA file, bounded
  pagination and a process-local cache. It is refresh-only by explicit admin action,
  never writes to the controller or inventory, and treats offline/historical or
  UniFi-only records as separate evidence rather than Nmap presence/absence. Optional
  `HLH_UNIFI_CERT_PIN_SHA256` pins the leaf certificate when a self-signed controller
  certificate cannot be used as a CA; a mismatch never falls back to insecure TLS.
  See [unifi-integration.md](unifi-integration.md). Live controller verification remains
  outstanding; the repository tests use mocked UniFi responses and no credentials.


The upstream direct-import endpoints still must not be called or trusted: they write
that process's database without HomeLab-Hub's preview/admin safeguards, and its HTTP
probe disables TLS verification. Keep discovery, transport, comparison and reviewed
application separate.

## Betty test deployment and rollback

| Item | Location/value |
|------|----------------|
| Test address | `192.168.1.80:8790` |
| Source | `/mnt/cache/appdata/homelab-hub-redesign-source` |
| Persistent data | `/mnt/cache/appdata/homelab-hub-redesign-data` |
| Test database | Data directory's `homelab-hub.db`, mounted at `/data/homelab-hub.db` |
| Deployment script | `scripts/deploy-betty-test.sh` |
| Active test container | `homelab-hub-redesign` |
| Private env location | `/mnt/cache/appdata/homelab-hub-redesign-config/phase3.env` (never commit contents) |
| Scanner test env | `/mnt/cache/appdata/homelab-hub-redesign-config/scanner-test.env` (mode 600, shared token/ranges) |
| Scanner deployment | `scripts/deploy-betty-test-scanner.sh` (test scanner only) |
| Test scanner | `homelab-hub-nmap-test` on private bridge `homelab-hub-nmap-test-net`; no published port |
| Existing scanner | `homelab-hub-scanner` — never replace or modify |
| FolderView input | `/boot/config/plugins/folderview.plus/docker.json`, mounted read-only |
| Original installation | **Host port 8000: never modify** |

The test web container joins `homelab-hub-nmap-test-net` and reaches the scanner by
Docker DNS at `http://homelab-hub-nmap-test:8791`. The scanner publishes no host port,
receives only `NET_RAW` (all other capabilities dropped), uses a read-only root
filesystem and has no Docker socket. The scanner has outbound NAT access to approved
private targets. MAC/vendor discovery may be unavailable over a bridge; this is the
deliberate minimum-privilege first test. See
[scanner-betty-test-deployment.md](scanner-betty-test-deployment.md) for the exact
token-generation, deployment, verification and first-scan sequence.

The test mapping is host **8790** → container-internal 8000. That does not authorize
any operation on the original host-port-8000 installation. Do not deploy automatically:
obtain explicit approval for the actual deployment, even though a script exists.

On Betty, only after approval, use `bash scripts/deploy-betty-test.sh` from the source
checkout. It validates branch/paths/private env permissions and test port, ensures the
private scanner bridge, optionally verifies the running test scanner and shared env,
fast-forwards source, builds a revision-tagged image, takes an **online SQLite backup
using Python's backup API**, checks its integrity, retains the stopped previous
container with restart disabled, starts the new test container on the private bridge
and health-checks both the application and web-to-scanner connectivity. It does not
delete older rollback containers, publish scanner port 8791 or automatically restore
a database on failure. A missing `scanner-test.env` keeps the prior behavior with
network discovery disabled.

The separate idempotent `scripts/deploy-betty-test-scanner.sh` builds and replaces
only `homelab-hub-nmap-test`, verifies health and refuses published ports. It does not
touch `homelab-hub-scanner`, the port-8000 installation, databases or Docker networks
other than the dedicated test bridge.

Backups are retained in the data directory with names such as
`homelab-hub-before-<revision>-<UTC timestamp>.db`. Previous containers reference the
same persistent volume: retaining an old container does **not** freeze the database.
Do not restart it blindly after a migration. On failure preserve logs, image identity,
backup identity and current data; request approval for the appropriate recovery.
Restoring an older database is destructive and requires explicit approval. Across
migration 010, restore the matching pre-migration backup **and** previous image.
Older pre-Phase-4 code also ignores reconciliation notes markers: equal schema
revision alone does not establish identity/override rollback compatibility.
Never downgrade/stamp the database merely to silence Alembic. Confirm restoration
and health deliberately; the script does not perform this recovery automatically.

The repository compose file is an upstream template using host port 8000; it is not
the Betty redesign deployment procedure. Do not run it there as a shortcut.

## Development workflow and local checks

These instructions work in OpenCode/DeepSeek, Codex or a normal terminal. No
published Codex environment, cloud plugin or `/workspace` path is required.
Use the existing checkout, inspect `git status`, and preserve any local work.

For ordinary successful changes: investigate → implement → proportionate checks →
review diff/credentials → **commit and push directly to `feature/homelab-redesign`** →
verify its remote SHA. No routine feature branch, PR or approval pause is needed.
Request approval for destructive actions, force pushes, live migrations, production
changes, deployments and irreversible operations. Never commit secrets.

Install from the checkout root using a local Python virtual environment and the
existing dependency files; activate it using the command appropriate to your OS:

```sh
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd frontend
npm ci
npm run build
```

Run checks in their stated directories with the virtual environment active:

```sh
# checkout root
python -m pytest -q backend/tests
python -m pytest -q scanner/tests
# frontend/
npm test
npm run build
npm run test:browser
```

Browser tests require Chromium. Install Playwright's browser with
`npx playwright install chromium`, or set `CHROMIUM_PATH` to an existing executable.
Tests manage a local Vite server on port 3000; stop only a development process you
started if that port is occupied. Linux screenshot baselines need a consistent
browser/platform when updated. Inspect screenshot changes, not just CSS properties.

For local startup, set `DATABASE_URL` to a fresh development database, never Betty's
file. Back up an existing database before any migration. From `backend/`, use
`alembic upgrade head` only against that chosen local database, then
`python -m flask --app wsgi run --host 127.0.0.1 --port 5001`. From `frontend/`,
`npm run dev` uses port 3000 and proxies to 5001. The production-style Flask server
needs `frontend/dist/` copied into ignored `backend/static/` after building.
Do not request live infrastructure secrets for ordinary unit/browser tests.

Last full recorded functional validation at `e1e595b` (not rerun for the docs-only
handover): **106 backend tests, 50 frontend tests, 10 Chromium checks**, production
frontend build and isolated local API/SPA smoke checks passed. The Docker exporter
change was validated with **120 backend tests** (14 exporter tests, including real
`normalise_snapshot` compatibility). Bulk/exclusions added **137 backend tests**, and
the Phase 5 network-discovery slice, including persistent scan tracking and the
collapsible sidebar Tools group, brings the totals to **196 backend tests, 22 scanner
tests and 71 frontend unit tests**; the production frontend build and all **9 Network
discovery/persistence/sidebar Playwright checks** passed. A focused browser run of
all 12 Network discovery, Reconciliation and sidebar checks also passed. The last
full browser run (before this sidebar slice) passed **16 of 18** checks: the two
FolderView SVG snapshot checks have no `-win32` baselines in this checkout, so they
cannot be compared on this Windows host and are unrelated to discovery. Backend
validation used Python 3.12; production Dockerfile uses Python 3.14. Existing
warnings: SQLAlchemy identity-map warning in inventory import; MapPage chunk >500 kB.

## Next development priorities

1. **Automated read-only Docker snapshot collection.** The host-side exporter is
   delivered as `scripts/docker-snapshot.sh` (see
   [its documentation](docker-snapshot-exporter.md)): it emits the complete v1
   contract from `docker ps --all` plus `docker inspect`, includes stopped/rollback
   containers and real completion times, whitelists metadata, and writes explicit
   failed evidence on errors. Remaining work is optional scheduling and reviewed
   transport/orchestration; the exporter is not deployed or scheduled, and the web
   app still has no Docker socket. Preserve physical-host/VM provenance for
   Betty/Unraid and Blackbox/Proxmox. Developing a collector is not deployment approval.
2. **Reviewed bulk reconciliation of discovered metadata.** Delivered: the reviewed
   bulk preview/apply updates only container ID, image ID, image reference and
   observation timestamp for confidently matched containers, preserves custom
   fields/notes markers/overrides and rolls back as one transaction. Remaining work
   is reviewed bulk handling of genuinely ambiguous additions/absences, not silent
   import or automatic deletion.
3. **Persistent exclusions for deployment backup containers.** Delivered: explicit
   host-scoped exclusions with visible reasons and separate display, stored in
   `reconciliation_exclusions` and managed with admin-authenticated add/remove.
   The six rollback containers can now be excluded as operational policy; decisions
   about the active redesign container and scanner remain explicit and are not
   inferred from names.
4. **Integrate the existing Nmap scanner and UniFi evidence.** Delivered as a
   separate token-authenticated scanner service with approved-target validation,
   bounded host/TCP discovery, status timestamps and read-only network-wide matching,
   plus optional official UniFi Network Integration evidence. The matcher searches
   the full inventory, separates host/service evidence and keeps UniFi current/
   historical records distinct from Nmap observations. Remaining work is live UniFi
   validation, persisted scan history, reviewed inventory/map actions, optional HTTP
   probing with verified TLS, supervised scheduling and possible UniFi client-history
   enrichment. Do not copy upstream direct imports, OS fingerprinting or TLS bypass.
5. **Improve dashboard summaries/filtering.** Delivered for Reconciliation:
   matched/unmatched/excluded/uncertain/not-seen summaries plus category and search
   filters while detailed sections remain available. Remaining work is persisted
   scan history and integrations into broader dashboard views.

Recommended next tasks: supervised scanner deployment on the Betty test instance,
persisted scan history/freshness, reviewed inventory/map actions from network
results, and optional verified-TLS HTTP probing. Use the 93/86/seven/zero baseline
for acceptance planning; do not hard-code these changing counts into application
logic.

## Supporting documentation

- [Phase 4 contract and scanner investigation](phase4-reconciliation.md).
- [Network discovery architecture, configuration and APIs](network-discovery.md).
- [UniFi read-only enrichment and supervised setup](unifi-integration.md).
- [Supervised Betty scanner test deployment](scanner-betty-test-deployment.md).
- [Phase 3 implementation report](container-group-management-phase3.md) — historical.
- [Phase 3 polish and migration review](container-group-polish-review.md) — historical
  development/validation detail, superseded by this handover for current workflow.

Older reports contain point-in-time test counts, branch states and cloud setup
instructions. They do not override this handover, `AGENTS.md` or current owner approvals.
