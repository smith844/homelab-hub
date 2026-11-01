# HomeLab-Hub — project handover

- **Repository:** `smith844/homelab-hub` (fork of `RaidOwl/homelab-hub`)
- **Working branch:** `feature/homelab-redesign`
- **Last committed revision at time of writing:** `1992ca2 Preserve grouped map positions and add expanded workspace`
- **Status:** Phases 1–2 deployed and validated on Betty. Phase 3 (container group management) is implemented and tested but **uncommitted** on the working branch.
- **Document purpose:** give a new developer or AI coding session enough context to continue without re-discovering the architecture.

> This document contains no credentials. Secrets such as `HLH_ADMIN_TOKEN` are configured
> only on the deployment host.

---

## 1. What HomeLab-Hub is

HomeLab-Hub is a self-hosted inventory and visualisation application for a home lab. It tracks
physical hosts, VMs, applications/containers, storage and shares, networks, miscellaneous
devices and markdown documentation. Its main visual feature is an interactive network map with
three presentations:

1. **Graph** — the full relationship graph with a force/dagre layout and per-view saved
   positions.
2. **Grouped** — Docker containers arranged into collapsible category cards, grouped per host,
   with imported FolderView Plus categories plus manual HomeLab-Hub groups.
3. **Tree** — a collapsible hierarchy view.

It runs as a single Flask application serving a compiled Svelte SPA, backed by SQLite.

---

## 2. Architecture

```
Browser (Svelte 4 SPA, Pico CSS)
        │  fetch /api, /inventory, /map ...
        ▼
Flask 3 application (Gunicorn, 1 worker)
        ├── REST blueprints (inventory, map, documents, container groups)
        ├── SQLAlchemy 2 ORM  ──►  SQLite (/data/homelab-hub.db)
        ├── Alembic migrations (run at container start)
        └── Read-only FolderView Plus importer (CLI or admin sync endpoint)
```

Key architectural facts:

- **Single process, single SQLite file.** Gunicorn is configured with one worker because SQLite
  has a single writer.
- The SPA is built by Vite and copied into the Flask static directory at image build time.
  Flask serves `index.html` for unknown non-API paths (hash routing via `svelte-spa-router`).
- The application is designed for a trusted LAN. Most read endpoints and the older CRUD
  endpoints are unauthenticated. Phase 3 adds a token gate **only** to the new container-group
  write endpoints.
- FolderView Plus is only ever read. Nothing in HomeLab-Hub writes back to Unraid configuration.
- There is no Docker socket integration and no background scheduler. Inventory is entered
  through the UI/API or restored from an export; FolderView grouping is imported explicitly.

---

## 3. Technology stack

| Layer | Technology |
|-------|------------|
| Frontend | Svelte 4, Vite 5, `svelte-spa-router`, Cytoscape.js 3 (+ dagre), ByteMD, Pico CSS |
| Backend | Python 3.14, Flask 3, SQLAlchemy 2, Flask-SQLAlchemy, Alembic, Gunicorn |
| Database | SQLite by default; `DATABASE_URL` is configurable |
| Tests | Pytest (backend), `node:test` (frontend, no component-test framework) |
| Packaging | Multi-stage Docker (Node build + Python runtime) |

Frontend dependencies are declared in `frontend/package.json`; backend dependencies in
`backend/requirements.txt` (dev extras in `backend/requirements-dev.txt`).

---

## 4. Repository structure

```
HomeLab-Hub/
├── Dockerfile                     # stage 1 builds frontend; stage 2 runs Flask
├── docker-compose.yml             # upstream image + ./data:/data (adapt for fork)
├── README.md                      # upstream usage docs
├── backend/
│   ├── alembic.ini
│   ├── docker-entrypoint.sh       # alembic upgrade head + gunicorn
│   ├── wsgi.py                    # `app = create_app()`
│   ├── requirements*.txt
│   ├── app/
│   │   ├── __init__.py            # app factory, blueprints, SPA fallback
│   │   ├── config.py              # DATABASE_URL, ADMIN_TOKEN, FOLDERVIEW_CONFIG_PATH
│   │   ├── cli.py                 # `flask container-groups ...` commands
│   │   ├── models/                # SQLAlchemy models (one module per domain)
│   │   ├── routes/                # REST blueprints
│   │   ├── services/
│   │   │   ├── admin_auth.py      # Phase 3 admin-token gate
│   │   │   ├── folderview_import.py
│   │   │   ├── group_identity.py  # normalised host/container identity
│   │   │   ├── group_resolution.py# override > assignment > ungrouped
│   │   │   └── group_backup.py    # natural-key export/import
│   │   └── utils/
│   ├── migrations/versions/       # Alembic history
│   └── tests/                     # pytest suite + FolderView fixtures
├── frontend/
│   ├── src/
│   │   ├── App.svelte             # hash routes
│   │   ├── components/            # Layout, Sidebar, inventory forms, map components
│   │   ├── lib/                   # api, admin token, grouping, mapViews, preferences
│   │   ├── pages/                 # Overview, Inventory, Map, Groups, Docs, Settings
│   │   └── theme.css              # Pico overrides + semantic control tokens
│   └── tests/                     # node:test suites (pure logic + theme invariants)
└── docs/                          # investigation notes and phase reports
```

---

## 5. Database models and migration history

### 5.1 Models

Defined in `backend/app/models/`, all inheriting `BaseMixin` (`created_at`, `updated_at`,
`to_dict()`):

- `Hardware` — physical hosts (e.g. Betty, Blackbox).
- `VM` — virtual machines / runtimes, optionally parented to `Hardware`.
- `AppService` — applications and Docker containers; either `hardware_id` or `vm_id`
  (`ck_apps_single_parent` enforces not both). Stores `name`, `description`, `notes`,
  `hostname`, `ip_address`, `external_hostname`, `port`, `https`, `icon`.
- `Storage`, `Share` — storage devices and network shares.
- `Network`, `NetworkMember` — networks and memberships.
- `Misc` — other devices.
- `Document` — hierarchical markdown documentation.
- `MapLayout`, `MapEdge`, `Relationship` — legacy/optional server-side map data. The current
  map layouts used by the SPA are stored in browser `localStorage`, not in these tables.
- `ContainerGroup`, `ContainerGroupAssignment`, `ContainerGroupOverride` — Phase 1 grouping
  model (see section 6).

### 5.2 Migration chain

`backend/migrations/versions/`, in upgrade order:

| Revision | Purpose |
|----------|---------|
| `001` | Initial schema |
| `002` | Add icons, remove app URL |
| `003` | Remove hypervisor, add `misc.ip` |
| `004` | Add `misc.hostname` |
| `005` | Storage units GB → TB |
| `006` | Add `apps.ip_address` |
| `007` | Add `apps.https` |
| `add89462ccd0` | Add shares table |
| `008_add_mac_address` | Add `misc.mac_address` |
| `009_container_groups` | Add `container_groups`, `container_group_assignments`, `container_group_overrides` |

`009` is additive and guarded with `if_not_exists` / `add_column_if_not_exists` because the app
also calls `db.create_all()` at startup (see `migrations/env.py`). Downgrading `009` drops the
three group tables and therefore destroys grouping data.

The entrypoint runs `alembic upgrade head` before Gunicorn starts.

### 5.3 Export/import compatibility

`GET /inventory/export` includes `container_groups`, `container_group_assignments` and
`container_group_overrides` serialised with **natural keys** (no database ids) by
`services/group_backup.py`. Import replaces grouping data and accepts older exports that do not
contain these keys. Natural keys are:

- imported group: `folderview:<host_key>:<external_id>`
- manual group: `manual:<normalised name>`
- assignments/overrides: `(host_key, container_key)` pairs

---

## 6. Container grouping data model and identity rules

### 6.1 Tables

`container_groups`

- `source` = `folderview` or `manual`
- `host_key` = normalised owning host (Betty → `betty`)
- `external_id` / `external_parent_id` = FolderView folder id and parent id
- `name`, `color` (`#rrggbb`), `icon`, `sort_order`, `active`, `metadata_json`
- unique `(source, host_key, external_id)`

`container_group_assignments` — imported membership, one row per
`(host_key, container_key)`; unique on that pair. The importer owns these rows.

`container_group_overrides` — manual choice, unique on `(host_key, container_key)`.
`group_id = NULL` means **explicitly ungrouped**. The importer never modifies these rows.

### 6.2 Resolution order

`services/group_resolution.py`:

1. An override exists → use its group, or ungrouped when `group_id` is `NULL`.
2. Otherwise an imported assignment exists → use its group.
3. Otherwise ungrouped.
4. A group with `active = false` (archived) never produces an effective membership.

This precedence is what makes manual choices survive re-imports.

### 6.3 Identity rules (critical)

`services/group_identity.py`:

- Both host and container keys are **case-insensitive**, trimmed and whitespace-collapsed
  (`normalize_identity`). Display labels preserve original spelling (`display_identity`).
- **Host identity comes from the app's root Hardware ancestor**, not the direct parent:
  `app → VM("Docker") → Hardware("Betty")` resolves to `betty`. Direct-parent resolution
  previously produced the colliding key `docker` for both hosts (see
  `docs/container-grouping-resolution-report.md`).
- **Container identity prefers the scanner-recorded Docker container name**:
  - `## Docker configuration` block with a `Container: <name>` line, or
  - `Docker container: <name>` in the description.
  - Otherwise the app name is used. Ordinary notes/descriptions are not treated as Docker.
- Database ids are never the permanent assignment identity. Container recreation with the same
  host-scoped name keeps its assignments/overrides. Two containers with the same name on one
  host cannot be distinguished by this scheme.

---

## 7. FolderView Plus importer

`backend/app/services/folderview_import.py` reads
`/boot/config/plugins/folderview.plus/docker.json` (or any configured path) as **read-only**.

- Input is a JSON object keyed by folder id; folder order is sorted for determinism.
- Validates folders, container arrays, duplicate and empty names; returns `warnings` and
  `conflicts` rather than silently guessing.
- Parsed folder `name`, `parentId`, `icon`, `sort_order` (folder order), containers, and other
  metadata are preserved. `metadata_json` stores raw source metadata.
- Planning compares desired imported state with existing rows and emits counters:
  - groups: `created`, `updated`, `reactivated`, `unchanged`, `archived`
  - assignments: `added`, `moved`, `removed`, `unchanged`
  - `overrides.untouched`, `unmatched_containers`, `ungrouped_apps`
- Applying updates imported groups/assignments only. It **never** touches
  `container_group_overrides`, so manual overrides always win.
- File size is capped at 5 MB.

Two entry points:

```bash
# CLI inside the container/backend (preferred for one-off operations)
flask --app wsgi container-groups import-folderview --host Betty --dry-run
flask --app wsgi container-groups import-folderview --host Betty
flask --app wsgi container-groups list
```

```http
POST /api/container-groups/sync
X-Admin-Token: <token>
{ "host_key": "betty", "dry_run": true }
```

The HTTP sync is Phase 3, admin-protected, and reads `FOLDERVIEW_CONFIG_PATH` from the server
environment. It is not scheduled.

---

## 8. Graph, Grouped and Tree implementations

### 8.1 Shared graph data

`GET /map/graph` returns Cytoscape nodes/edges built from hardware → VM → app relationships.
`frontend/src/lib/mapViews.js` provides `filterGraph` (root/host, type filters, search,
individually selected members, depth) and shared type metadata.

### 8.2 Graph mode

`frontend/src/components/map/NetworkMap.svelte` with `mode="graph"` renders the filtered graph
using Cytoscape + dagre and the existing interactions (select, highlight, drag, fit, readable
zoom). Dragging saves positions to `hlh.mapLayout.<signature>`. Graph mode is independent from
Grouped mode and never reads Grouped positions or anchors.

### 8.3 Grouped mode

`frontend/src/lib/grouping.js`:

- `buildGroupedGraph(filtered, effectiveGrouping)` converts the effective grouping API response
  plus filtered app nodes into virtual group nodes (`type: "group"`), ungrouped nodes
  (`ungrouped@<host>`) and host containers.
- Imported and manual groups are displayed together; source is visible in the management page.
- Group node ids are stable: `group-<group id>@<host>` / `ungrouped@<host>`.
- Group nodes carry `groupColor` (if configured) and a label prefixed with the configured icon.
  `NetworkMap.svelte` styles `node[groupColor]` with a coloured border. Default border remains
  the theme primary colour.
- Groups start collapsed (`hlh.mapGroupExpanded` persists expansion). Click a group card to
  expand; members are laid out beneath it.
- `groupedLayoutPositions()` performs a compact per-host lane layout, respects manual anchors,
  reserves space for anchored cards and expanded members, and flows automatic cards around
  them.
- Manually dragging a group card writes an anchor to `hlh.mapGroupAnchors.<signature>` and
  re-flows members; other groups avoid the anchored area. Auto layout clears anchors.
- Group data is fetched from `GET /api/container-groups/effective`; failures show an inline
  message rather than breaking the rest of the map page.

### 8.4 Tree mode

`TreeView.svelte` + `TreeNode.svelte` render the same filtered graph as an accessible nested
tree with collapse/expand. It does not use Cytoscape or saved positions.

### 8.5 Switching and persistence

- The Graph/Grouped/Tree selector lives in `MapPage.svelte`. Switching views remounts the map
  component only when necessary (`{#key signature+viewMode}`); Grouped does not reinitialise
  Graph layouts.
- `hlh.mapCurrent` stores the current scope, filters and view mode.
- `hlh.mapViews` stores named saved views (browser-local).
- Phase 3 changed the selector to semantic theme tokens, fixing unreadable white text on light
  backgrounds (see section 11).

---

## 9. Browser storage keys

All are `localStorage` unless stated. They are per browser/profile, not per user or server.

| Key | Purpose |
|-----|---------|
| `hlh.theme` | `light` / `dark` |
| `hlh.siteName` | Custom site name |
| `hlh.mapViews` | Named saved map views (`id`, `name`, filters, `viewMode`) |
| `hlh.mapCurrent` | Current map scope/filters/view mode |
| `hlh.mapLayout.<signature>` | Graph node positions for the current filter signature |
| `hlh.mapLayoutGrouped.<signature>` | Grouped node positions (automatic + dragged) |
| `hlh.mapGroupAnchors.<signature>` | Explicitly dragged group-card positions only |
| `hlh.mapGroupExpanded` | Expanded group node ids (not signature-scoped) |
| `hlh.adminToken` | Phase 3 admin token, **sessionStorage only** |

The `<signature>` is the JSON of host root, sorted types, search query, sorted member ids and
depth. Changing the scope therefore has independent layouts.

---

## 10. Container group management (Phase 3)

### 10.1 Backend endpoints

Base path `/api/container-groups`.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/effective` | public | Active groups + effective memberships, unmatched, ungrouped apps |
| GET | `/management` | public | Hosts, all groups (with counts), all apps with effective/imported state, unmatched rows |
| POST | `` (collection) | admin | Create a manual group |
| PUT | `/<id>` | admin | Edit colour/icon/sort; rename manual only; archive/restore |
| DELETE | `/<id>` | admin | Delete an empty manual group |
| PUT | `/assignments` | admin | Set a manual override, or explicit ungrouped (`group_id: null`) |
| DELETE | `/assignments` | admin | Remove the override, reverting to the imported assignment |
| POST | `/sync` | admin | FolderView import from `FOLDERVIEW_CONFIG_PATH`, with `dry_run` |

Validation and error shape is consistent: `{"error": "message"}` with 400 (validation), 401
(invalid/missing token), 404 (missing entity), 409 (conflict / guarded delete), 503 (writes
disabled or sync path unconfigured). All writes commit or roll back as a single transaction.

Assignment identity: send `app_id`, or `host_key` + `container_key` for an unmatched identity.
The handler resolves the current normalised identity before writing, so overrides survive
container recreation.

Group rules:

- Manual names are unique per host, case-insensitively.
- Imported group names are immutable (FolderView owns them); colour, icon, sort order and
  active state can be edited.
- Imported groups cannot be deleted; archive instead.
- A manual group with assignments or overrides cannot be deleted; archive instead.
- Archiving hides effective memberships; restoring brings them back.
- Assigning to an archived group or to a group on another host is rejected.

### 10.2 Administrative access

`services/admin_auth.py` implements a configurable shared token:

- Server env: `HLH_ADMIN_TOKEN` (fallback `ADMIN_TOKEN`). Empty/absent → all writes return 503.
- Request: `X-Admin-Token: <token>` or `Authorization: Bearer <token>`.
- Comparison uses `hmac.compare_digest`.
- Reads stay public, matching the rest of the application.
- The frontend stores the token in **sessionStorage** (`hlh.adminToken`) and sends
  `X-Admin-Token` on management writes. It is never persisted to localStorage or exported.

### 10.3 Management UI

`frontend/src/pages/GroupsPage.svelte`, route `/groups`, Sidebar item **Container groups**.

- Token panel to save/clear the session token; write controls are disabled without it.
- Host filter and per-host group tables: colour dot, icon, name, source badge, member counts,
  active/archived status.
- Create manual group (name, host, colour, icon, sort order).
- Inline edit (imported names disabled with an explanation).
- Archive/restore and guarded delete with confirmation dialogs.
- Applications table: all discovered apps with effective group, source
  (FolderView / manual override / manually ungrouped / ungrouped), imported group and a Revert
  action when an override exists. The group selector writes manual overrides directly; choosing
  "Ungrouped" writes an explicit ungrouped override.
- Separate Ungrouped section and Unmatched FolderView memberships table.
- FolderView sync card: host selection, **Preview sync** (dry run) and **Apply sync**, rendering
  created/updated/reactivated/unchanged/archived groups, assignment deltas, untouched overrides,
  conflicts, warnings, unmatched containers and ungrouped apps.

---

## 11. Theming and control contrast

`frontend/src/theme.css` defines light/dark Pico overrides plus semantic control tokens:

- `--hlh-control-fg` → `--pico-contrast` (readable foreground on pale/dark surfaces)
- `--hlh-control-muted`, `--hlh-control-border`
- `--hlh-control-hover-bg` (tint)
- `--hlh-control-active-fg` / `--hlh-control-active-bg`
- `--hlh-control-focus`

The Map Graph/Grouped/Tree selector uses these tokens for base, hover, active, focus-visible and
disabled states. This fixes light mode, where Pico's button-local `--pico-color` resolved to
white while the button background stayed pale. The same tokens should be used for any new
custom toggle/tab controls. `frontend/tests/theme.test.js` guards the token definitions and the
selector rules.

---

## 12. Deployment on Betty

The live instance runs on **Betty** and is reachable on **port 8790** (referenced throughout the
phase reports). The repository's `docker-compose.yml` is the upstream template (publishes
`8000:8000`, image `raidowl/homelab-hub:latest`, volume `./data:/data`); a fork deployment
should build the local `Dockerfile` and publish whatever host port the reverse proxy expects
(8790 in the current setup).

Runtime contract:

- Database: `/data/homelab-hub.db` (`DATABASE_URL=sqlite:////data/homelab-hub.db` in the image).
- Persistent volume: `./data:/data` — this is the only state that must be backed up.
- Entrypoint applies migrations, then starts Gunicorn on `0.0.0.0:8000` with one worker.
- Optional Phase 3 environment:
  - `HLH_ADMIN_TOKEN` — enables container-group writes.
  - `FOLDERVIEW_CONFIG_PATH` — server-side path to a **read-only** mounted
    `docker.json` for HTTP sync. Leave unset to use CLI-only imports.
- Health check: `GET /api/health` → `{"status": "ok"}`.
- Example Phase 3 run (adapt names/ports to the existing Betty compose file):

```yaml
services:
  homelab-hub:
    build: .
    container_name: homelab-hub
    ports:
      - "8790:8000"
    volumes:
      - ./data:/data
      - /boot/config/plugins/folderview.plus/docker.json:/config/folderview-docker.json:ro
    environment:
      - HLH_ADMIN_TOKEN=${HLH_ADMIN_TOKEN}
      - FOLDERVIEW_CONFIG_PATH=/config/folderview-docker.json
    restart: unless-stopped
```

Deployment steps are repeated with rollback guidance in
`docs/container-group-management-phase3.md`.

---

## 13. Git and development workflow

- `origin` = `github.com/smith844/homelab-hub` (fork); `upstream` = `RaidOwl/homelab-hub`.
- Work happens on `feature/homelab-redesign` in small, logically separate commits.
- Do not commit or push without explicit instruction.
- Do not modify the live installation's database during development; use a local SQLite file or
  the test fixtures.
- Backend tests use an isolated temporary database per test (`backend/tests/conftest.py`).
- Frontend tests are pure Node tests over logic and source invariants; there is no browser/component
  test runner.
- Production build is validated with `npm run build`; warnings (chunk size, unused CSS) should be
  reviewed but are not build failures.

---

## 14. Completed phases and outstanding tasks

### Completed

- **Phase 1 — grouping data + FolderView importer.** Three grouping tables, normalised identity,
  read-only CLI importer, dry-run reporting, natural-key backup/restore.
- **Phase 2 — Grouped map.** Collapsible per-host group cards, effective membership API,
  Graph/Grouped/Tree selector, regression tests.
- **Phase 2.1 — hierarchy/layout improvements.** Host-scoped grouping, compact lanes,
  member placement, saved layouts per filter signature.
- **Phase 2.2 — anchors + expanded workspace.** Manual group anchors independent of saved layout,
  expanded in-page workspace with Escape, preserved Cytoscape instance.
- **Phase 3 — container group management (uncommitted).** Admin-token gate, management API/UI,
  overrides/ungrouped/revert, guarded archive/delete, FolderView HTTP sync with dry run, theme
  token contrast fix, group colour/icon propagation, backend and frontend tests.

### Outstanding / recommended next work

- Extend authentication to the rest of the mutating API (inventory CRUD, import/export, map
  layout/edges) or front the whole app with an authenticating reverse proxy.
- Add CSRF/rate-limit considerations if the app is ever exposed beyond the LAN.
- Scheduled or automatic FolderView sync (explicitly out of scope so far).
- Multi-host/multi-file sync (current HTTP sync handles one host and one configured path).
- Group nesting/hierarchy in the Grouped view (FolderView `parentId` is preserved but not yet
  rendered as nested groups).
- Group reordering UI (sort order is editable numerically, not drag-and-drop).
- Audit log for administrative changes; multiple admin users/roles.
- Component/browser tests for the management page and map interactions.
- Address the >500 kB MapPage chunk warning if startup size becomes a concern.

---

## 15. Testing commands

Backend (from `backend/`):

```powershell
.venv\Scripts\python.exe -m pytest -q        # Windows
# or: python -m pytest -q
```

Frontend (from `frontend/`):

```powershell
npm test
npm run build
```

Last recorded results at the end of Phase 3:

- Backend: **62 passed**, 1 pre-existing SQLAlchemy `SAWarning` in `routes/inventory.py:106`.
- Frontend: **46 passed**, 0 failed.
- `npm run build`: success (86 modules); only the Vite >500 kB chunk advisory.

Useful focused backend suites:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_group_management.py
.venv\Scripts\python.exe -m pytest -q tests/test_effective_groups.py tests/test_identity.py
.venv\Scripts\python.exe -m pytest -q tests/test_importer_sync.py tests/test_backup.py
```

---

## 16. Security considerations

- **Threat model:** trusted LAN, single operator. The app is not hardened for the public internet.
- New management writes require `HLH_ADMIN_TOKEN`. Unset → 503, wrong/missing → 401. This is a
  shared secret, not a user account system; there is no per-user attribution or audit trail.
- Reads (inventory, docs, graph, effective/management grouping views) are public. This matches
  the pre-existing application behaviour.
- **Pre-existing unauthenticated write endpoints remain:** inventory CRUD, `/inventory/import`,
  `/map/layout`, `/map/edges`, document editing. Phase 3 deliberately did not widen this surface
  but did not retrofit auth. Protect the app at the network/reverse-proxy layer.
- CORS is enabled when `flask_cors` is installed (development convenience). Consider disabling it
  in production.
- The admin token is stored only in `sessionStorage` and is cleared when the tab session ends.
  It is never written to exports, localStorage, logs or docs.
- The FolderView configuration is mounted read-only and opened read-only. The importer never
  writes to Unraid. Do not mount the whole `/boot` tree; mount only `docker.json`.
- SQLite has no row-level security. Anyone with access to the `data/` volume has full data access.
- Back up `data/homelab-hub.db` before applying migrations. Migration `009` is additive, but a
  downgrade drops grouping tables.

---

## 17. Known limitations

- Container identity cannot distinguish two containers with the same name on the same host.
- Host identity depends on the Hardware name; renaming a host changes its normalised key and
  effectively orphans imported assignments/overrides until re-imported/re-created.
- Apps whose Docker container name is not recorded in notes/description fall back to the app
  name; renaming the app changes its container key.
- Imported group names and hierarchy come from FolderView and cannot be renamed in HomeLab-Hub.
- Only active groups appear in Grouped mode. Archived groups keep their assignments and can be
  restored, but their members show as ungrouped while archived.
- Deleting a group is limited to empty manual groups. Imported and non-empty groups must be
  archived.
- Browser-local layouts/anchors/views do not sync between browsers or users, and are keyed by a
  filter signature.
- There is no scheduled sync, no live Docker discovery, and no bidirectional FolderView editing.
- Grouped mode currently shows flat categories per host; `external_parent_id` is stored but not
  rendered as nesting.
- The frontend has no component/E2E test harness; map rendering behaviour is validated manually
  and through pure layout-function tests.
- Single Gunicorn worker is intentional for SQLite; do not raise it without migrating to a
  multi-writer database.

---

## 18. Where to look first

1. `docs/container-grouping-investigation.md` — original problem/architecture investigation.
2. `docs/container-grouping-resolution-report.md` — why host identity uses the root Hardware.
3. `docs/grouped-map-workspace-improvements.md` — anchors and expanded workspace design.
4. `docs/container-group-management-phase3.md` — Phase 3 implementation report.
5. `backend/app/services/group_identity.py`, `group_resolution.py`,
   `folderview_import.py` — grouping semantics.
6. `frontend/src/lib/grouping.js`, `frontend/src/components/map/NetworkMap.svelte` — Grouped
   presentation and layout.
7. `frontend/src/pages/GroupsPage.svelte`, `backend/app/routes/container_groups.py` — management
   UI/API.
