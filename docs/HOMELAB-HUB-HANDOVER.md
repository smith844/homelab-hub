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
- No Docker socket, network scanner or infrastructure credentials are required by
  the web app. There is no automatic Docker collector or background scan scheduler.
  A separate host-side exporter (`scripts/docker-snapshot.sh`) produces the uploaded
  container snapshot contract; it is not wired into the app or scheduled.
- Reconciliation consumes uploaded JSON. It does not contact Betty or the separate
  scanner, start scans, or execute scanner import endpoints.
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
| Input/identity adapters | `services/discovery_adapters.py`, `discovery_identity.py`, `network_reconciliation.py` |
| SPA/navigation | `frontend/src/App.svelte`, `components/Sidebar.svelte` |
| Management pages | `frontend/src/pages/GroupsPage.svelte`, `ReconciliationPage.svelte` |
| Maps | `pages/MapPage.svelte`, `components/map/NetworkMap.svelte`, `TreeView.svelte`, `TreeNode.svelte` |
| Map logic/icons/theme | `frontend/src/lib/grouping.js`, `mapViews.js`, `groupIcons.js`, `frontend/src/theme.css` |
| Tests | `backend/tests/`, `frontend/tests/`, `frontend/tests/browser/` |
| Docker snapshot exporter | `scripts/docker-snapshot.sh`, `docs/docker-snapshot-exporter.md` |
| Test deployment | `scripts/deploy-betty-test.sh` |

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
`hlh.mapGroupAnchors.<signature>`, `hlh.mapGroupExpanded`, `hlh.theme` and
`hlh.siteName`. `hlh.adminToken` is **sessionStorage only**. Do not clear or change
these keys casually; inventory export does not back up browser layouts.

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
| Docker containers discovered | **92** |
| Matched existing inventory applications | **84** |
| Discovered but unmatched | **8** |
| Unmatched breakdown | Current redesign container (**1**), retained rollback containers (**6**), separate network scanner (**1**) |
| Inventory applications without a discovered container match | **0** |
| Recorded container/image IDs | Not yet recorded in most inventory entries |

Thus 92 = 84 + 8. The eight do not establish eight missing ordinary applications:
review policy for the redesign/scanner themselves and retain the six rollback
containers. **Do not delete backups or automatically add all eight to make counts
look clean.** A first recorded ID is missing metadata being filled, not proof that
a resource was recreated. Reviewed bulk metadata reconciliation is still needed.

Earlier seven unmatched FolderView entries and eleven ungrouped apps were separate
grouping investigation targets; they are not the eight Docker snapshot discrepancies.
Their latest counts were not supplied here, and intentional Ungrouped choices remain
valid. Do not infer they were resolved from the zero unmatched-inventory result.

## Separate Nmap scanner: verified boundary

- Repository: `dpinna13/homelab-hub`.
- Branch: `feature/network-scanner`.
- Observed/source-inspected revision: **`9feebd5`**
  (`9feebd509ae58ad98bc7fc8881100b51e6add357`).
- Betty container/image: `homelab-hub-scanner`, separate from the redesign app.
- Source checkout: `/mnt/cache/appdata/homelab-hub-scanner-source`.

It provides Nmap-based IPv4 discovery, reverse DNS/MAC hints, device/OS
identification, TCP port/service scanning and HTTP header/title/name probing.
It **does not discover Docker identities, container/image IDs, a Docker inventory
export or Proxmox API inventory**. Do not build a second independent network scanner.

Verified routes: POST `/api/scanner/discover`, `/identify`, `/portscan`, `/probe-http`,
`/import/hardware`, `/import/apps`; GET `/api/scanner/interfaces`, `/status/<scan_id>`
(all paths after the first share the `/api/scanner` prefix).

Status responses contain `data` with type/status/progress/results/error/params;
the implementation omits its internal scan timestamps. Jobs are in memory and
completed/failed jobs expire after 600 seconds. Network observations cannot establish
Docker coverage or authoritative container absence. The existing adapter accepts
these saved status responses and compares hosts by IP/MAC and apps by IP+port,
within a selected root host. A missing VM address is not guessed from its host.

The scanner import routes write its own process's database directly, without the
new reconciliation preview/admin safeguards. Do not assume shared databases or
call these to update HomeLab-Hub inventory. Its existing HTTP probing disables
TLS verification; do not copy that behaviour into new integrations. Keep discovery,
transport, comparison and reviewed application of changes separate.

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
| FolderView input | `/boot/config/plugins/folderview.plus/docker.json`, mounted read-only |
| Original installation | **Host port 8000: never modify** |

The test mapping is host **8790** → container-internal 8000. That does not authorize
any operation on the original host-port-8000 installation. Do not deploy automatically:
obtain explicit approval for the actual deployment, even though a script exists.

On Betty, only after approval, use `bash scripts/deploy-betty-test.sh` from the source
checkout. It validates branch/paths/private env permissions and test port, fast-forwards
source, builds a revision-tagged image, takes an **online SQLite backup using Python's
backup API**, checks its integrity, retains the stopped previous container with restart
disabled, starts the new test container and health-checks it. It does not delete older
rollback containers or automatically restore a database on failure.

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
`normalise_snapshot` compatibility). The bulk/exclusions change adds **137 backend
tests** (bulk plans, exclusions, authentication, transaction rollback, freshness and
data preservation) and **56 frontend unit tests**; the production frontend build and
the three Reconciliation Playwright checks passed. Other browser specs were not
rerun. Backend validation used Python 3.12; production Dockerfile uses Python 3.14.
Existing warnings: SQLAlchemy identity-map warning in inventory import; MapPage
chunk >500 kB.

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
4. **Integrate the existing Nmap scanner.** Reuse its verified discovery/probing;
   define authenticated read-only transport and freshness/provenance without
   inventing Docker data or sharing databases implicitly. Do not copy its unsafe
   direct-import or TLS-bypass behaviour.
5. **Improve dashboard summaries/filtering.** Delivered for Reconciliation:
   matched/unmatched/excluded/uncertain/not-seen summaries plus category and search
   filters while detailed sections remain available. Remaining work is persisted
   scan history and integrations into broader dashboard views.

Recommended next tasks: Nmap integration as a separate discovery source, persisted
scan history with explicit freshness/provenance, and reviewed bulk handling of
ambiguous inventory gaps. Use the 92/84/eight/zero baseline for acceptance planning;
do not hard-code these changing counts into application logic.

## Supporting documentation

- [Phase 4 contract and scanner investigation](phase4-reconciliation.md).
- [Phase 3 implementation report](container-group-management-phase3.md) — historical.
- [Phase 3 polish and migration review](container-group-polish-review.md) — historical
  development/validation detail, superseded by this handover for current workflow.

Older reports contain point-in-time test counts, branch states and cloud setup
instructions. They do not override this handover, `AGENTS.md` or current owner approvals.
