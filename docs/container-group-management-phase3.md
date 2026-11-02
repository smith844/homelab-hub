# Container group management — Phase 3 implementation report

> Historical implementation/validation report. Branch states, deployment guidance and
> test counts below describe that development cycle; the changes are now committed
> on the development branch. Use [the current handover](HOMELAB-HUB-HANDOVER.md) and
> [AGENTS.md](../AGENTS.md) for current state, workflow and deployment approvals.

- **Project:** HomeLab-Hub (`smith844/homelab-hub` fork)
- **Branch:** `feature/homelab-redesign`
- **Base revision:** `1992ca2 Preserve grouped map positions and add expanded workspace`
- **Date:** 2026-11-01
- **Scope:** Container-group management API/UI, protected writes, FolderView Plus synchronisation,
  light-mode control contrast, tests and documentation.
- **Status:** implemented, tested, **uncommitted** and not pushed. No database migration was added
  in this phase.

---

## 1. Executive summary

Phase 3 makes container grouping manageable from HomeLab-Hub without compromising imported
FolderView Plus data:

- A dedicated **Container groups** page (`/groups`) lists groups per host, creates/edits/archives
  manual and imported groups, manages application assignments and reports unmatched FolderView
  memberships.
- Manual assignment overrides — including **explicitly ungrouped** — are stored separately from
  imported assignments, take precedence, can be reverted, and survive FolderView re-imports and
  container recreation.
- All new write endpoints are protected by a configurable shared admin token
  (`HLH_ADMIN_TOKEN`). When no token is configured, writes are disabled entirely (503). Reads
  remain public, consistent with the existing application.
- FolderView synchronisation is available through the protected
  `POST /api/container-groups/sync` endpoint using a read-only `FOLDERVIEW_CONFIG_PATH`, with a
  full dry-run preview. Nothing is written back to Unraid and no schedule was introduced.
- Grouped mode already consumed the effective grouping API; it now also receives group colours
  (card border) and icons (label prefix) without changing node identity, saved layouts or
  anchors. Graph and Tree behaviour is unchanged.
- The light-mode Graph/Grouped/Tree selector contrast bug was fixed with semantic theme tokens,
  preserving dark mode and covering hover/focus/disabled states.

Final verification:

| Check | Result |
|-------|--------|
| Backend `pytest -q` | **62 passed**, 1 pre-existing `SAWarning` |
| Frontend `npm test` | **46 passed**, 0 failed |
| Frontend `npm run build` | success, 86 modules (Vite >500 kB chunk advisory only) |

---

## 2. Security investigation and decision

### 2.1 What existed

Before Phase 3 the application had **no authentication**:

- Inventory CRUD, exports/imports, document editing and map layout/edge writes are public.
- The only existing grouping endpoint (`GET /api/container-groups/effective`) and the FolderView
  importer are read-only; the importer runs via Flask CLI, not HTTP.
- `flask_cors` is enabled when installed, and there is no concept of users, roles or sessions.

### 2.2 Approach

Retrofitting full authentication was out of scope and would have touched every existing route.
Instead, Phase 3 introduces a minimal, explicit administrative gate for **new** mutating
endpoints only:

- Environment variable `HLH_ADMIN_TOKEN` (fallback `ADMIN_TOKEN`) is read in
  `backend/app/config.py`.
- Requests send `X-Admin-Token: <token>` or `Authorization: Bearer <token>`.
- `backend/app/services/admin_auth.py`:
  - no configured token → **503** with a message explaining writes are disabled;
  - missing/invalid token → **401**;
  - comparison uses `hmac.compare_digest`.
- Reads (`/effective`, `/management`) stay public.
- The SPA keeps the token in **sessionStorage** only and shows write controls as disabled until a
  token is entered.

This satisfies "do not silently expose unauthenticated database-mutating operations" while
remaining appropriate for a self-hosted LAN app: the secure default is **writes off**, and
enabling them is an explicit operator action.

The pre-existing unauthenticated write surface is documented as a known limitation in the
handover and is not widened by Phase 3.

---

## 3. Backend implementation

### 3.1 Changed/new modules

- `backend/app/config.py` — `ADMIN_TOKEN` (from `HLH_ADMIN_TOKEN`/`ADMIN_TOKEN`) and
  `FOLDERVIEW_CONFIG_PATH`.
- `backend/app/services/admin_auth.py` — token extraction, constant-time comparison,
  `@admin_required` decorator.
- `backend/app/services/group_identity.py` — app identity rows now include a display `name` for
  management views; resolution rules unchanged.
- `backend/app/routes/container_groups.py` — read endpoints refactored and write/sync endpoints
  added.

### 3.2 Endpoints

All under `/api/container-groups`.

| Method | Path | Auth | Behaviour |
|--------|------|------|-----------|
| GET | `/effective` | public | Unchanged contract: active groups, effective memberships, unmatched, ungrouped apps |
| GET | `/management` | public | Hosts, groups with imported/manual/override/unmatched counts, apps with effective+imported state, unmatched rows |
| POST | `` | admin | Create manual group |
| PUT | `/<id>` | admin | Update name (manual only), colour, icon, sort order, active |
| DELETE | `/<id>` | admin | Delete an empty manual group |
| PUT | `/assignments` | admin | Create/update override; `group_id: null` = explicitly ungrouped |
| DELETE | `/assignments` | admin | Delete override → revert to imported assignment |
| POST | `/sync` | admin | Import from `FOLDERVIEW_CONFIG_PATH`; `dry_run` preview/apply |

### 3.3 Validation and error handling

- JSON object bodies are required; malformed bodies return `400`.
- Group name: trimmed, whitespace-collapsed, 1–80 characters.
- Colour: `#rrggbb` only (normalised to lowercase); empty clears it.
- Icon: trimmed string, capped at 100 000 characters (icons may be base64 in existing data).
- `sort_order`: integer in `[-100000, 100000]`; booleans rejected.
- `active` / `dry_run`: booleans only.
- Host must resolve to a known host (Hardware name or an app's root host).
- Manual group names are unique per host, case-insensitively (compares normalised names).
- Assignment target must exist, be active, and belong to the same host (or be host-less).
- Requests use `{"error": "..."}` consistently: 400 validation, 401 auth, 404 missing,
  409 conflict/guarded delete, 503 disabled/unconfigured.
- Writes use a single `commit()` with `rollback()` on `ValidationError`/`IntegrityError`.

### 3.4 Group lifecycle rules

- Imported (`source = folderview`) groups: name immutable; colour/icon/sort/active editable;
  cannot be deleted; archive/restore available.
- Manual groups: full edit; delete only when no assignments and no overrides exist; otherwise
  archive.
- Archiving hides memberships from `/effective` and Grouped mode; restoring reinstates them.
- Assignments to archived groups are rejected so the UI cannot create hidden state.

### 3.5 Assignment identity and precedence

- `PUT /assignments` accepts `app_id`, or `host_key` + `container_key` for unmatched identities.
- The handler resolves the current normalised identity from the app before writing, so container
  recreation with the same name keeps the override.
- Overrides live in `container_group_overrides`; imported rows in
  `container_group_assignments` are never modified. `group_id = NULL` is an explicit ungrouped
  override that also beats an imported assignment.
- `DELETE /assignments` removes the override and returns the effective imported group (or
  ungrouped) without touching imported data.
- No database ids are used as permanent assignment identity.

### 3.6 FolderView sync

`POST /api/container-groups/sync`:

```json
{ "host_key": "betty", "dry_run": true }
```

- Requires the admin token and `FOLDERVIEW_CONFIG_PATH`; otherwise 401/503.
- Opens the configured file read-only through the existing importer (5 MB cap).
- Dry run builds and returns the same report without committing.
- Report includes: `dry_run`, `host`, `folders.total`, `groups.created/updated/reactivated/
  unchanged/archived`, `assignments.added/moved/removed/unchanged`, `overrides.untouched`,
  `conflicts`, `warnings`, `unmatched_containers`, `ungrouped_apps`.
- No scheduled sync, no writes to Unraid, and manual overrides are structurally excluded from
  the import plan.

---

## 4. Frontend implementation

### 4.1 API and admin token helpers

- `frontend/src/lib/api.js` — supports per-call `options`, custom headers and JSON bodies on
  `DELETE`; header merge order fixed so caller headers win.
- `frontend/src/lib/admin.js` — `getAdminToken` / `setAdminToken` / `adminHeaders`, sessionStorage
  key `hlh.adminToken`.

### 4.2 Container Groups page

`frontend/src/pages/GroupsPage.svelte`, route `/groups`, Sidebar entry **Container groups**.

- Administrative access panel: password field, save/clear token, enabled/disabled status.
- Host filter and per-host group tables: colour dot, icon, name, source badge, imported/manual/
  missing counts, active/archived status.
- Create manual group: name, host, colour, icon, sort order.
- Inline edit: imported names are disabled with an explanation; colour/icon/sort editable.
- Archive/restore and delete with explicit confirmation; delete is only offered for manual
  groups (server still enforces the empty-group guard).
- Applications table: all discovered apps for the selected scope with effective group, source
  (FolderView, manual override, manually ungrouped, ungrouped), imported group and a Revert
  button when an override exists. The group selector writes overrides immediately; the
  "Ungrouped" option writes an explicit ungrouped override.
- Ungrouped summary chips and a separate **Unmatched FolderView memberships** table.
- FolderView sync card: host selector, **Preview sync**, **Apply sync**, rendered report
  (counters, conflicts, warnings, unmatched containers, ungrouped apps). Apply requires
  confirmation and reloads data afterwards.
- All custom controls use Pico variables or the new semantic control tokens; no hardcoded
  foreground colours.

### 4.3 Navigation

- `frontend/src/App.svelte` registers `/groups` (eager import, like other inventory pages).
- `frontend/src/components/Sidebar.svelte` adds **Container groups** under INVENTORY.

### 4.4 Grouped map integration

- `frontend/src/lib/grouping.js`:
  - group metadata now carries `icon`;
  - group labels are prefixed with the icon when configured;
  - group nodes receive `groupColor` when a colour is configured.
- `frontend/src/components/map/NetworkMap.svelte`:
  - adds a `node[groupColor]` style rule using `data(groupColor)` for the border;
  - default group border remains theme-primary when no colour is set.
- Node ids (`group-<id>@<host>`, `ungrouped@<host>`), saved layout keys and anchor keys are
  unchanged, so existing layouts and manual anchors remain valid. No Cytoscape reinitialisation
  was added.

### 4.5 Light-mode control contrast fix

Problem: the Graph/Grouped/Tree selector used `background: transparent` with
`color: var(--pico-color)`. Pico's button styles resolve `--pico-color` inside buttons to a
light/white value, so inactive buttons rendered white text on the pale page background in light
mode.

Fix (theme-token based, not a one-off colour patch):

- `frontend/src/theme.css` adds semantic tokens:
  - `--hlh-control-fg: var(--pico-contrast)`
  - `--hlh-control-muted`, `--hlh-control-border`, `--hlh-control-hover-bg`
  - `--hlh-control-active-fg`, `--hlh-control-active-bg`, `--hlh-control-focus`
- `frontend/src/pages/MapPage.svelte` `.view-toggle button` now uses these tokens for base,
  `:hover:not(.active)`, `.active`, `:focus-visible` and `:disabled` states.
- Dark mode is preserved: Pico's dark `--pico-contrast` is light text and active colours remain
  the primary/inverse pair.
- The management page and other new controls use Pico variables or the same tokens, so the same
  defect is not reintroduced there.

---

## 5. Changed files

Phase 3 changes (uncommitted):

| File | Change |
|------|--------|
| `backend/app/config.py` | `ADMIN_TOKEN`, `FOLDERVIEW_CONFIG_PATH` |
| `backend/app/services/admin_auth.py` | **new** token gate |
| `backend/app/routes/container_groups.py` | management view, CRUD, assignments, sync |
| `backend/app/services/group_identity.py` | display name in identity rows |
| `backend/tests/test_group_management.py` | **new** 15 backend tests |
| `frontend/src/lib/admin.js` | **new** session token helper |
| `frontend/src/lib/api.js` | options/headers/DELETE body |
| `frontend/src/pages/GroupsPage.svelte` | **new** management UI |
| `frontend/src/App.svelte` | `/groups` route |
| `frontend/src/components/Sidebar.svelte` | navigation item |
| `frontend/src/theme.css` | semantic control tokens |
| `frontend/src/pages/MapPage.svelte` | selector uses control tokens |
| `frontend/src/lib/grouping.js` | group icon/colour propagation |
| `frontend/src/components/map/NetworkMap.svelte` | `node[groupColor]` border style |
| `frontend/tests/theme.test.js` | **new** token/selector regression tests |
| `frontend/tests/grouping.test.js` | group colour/icon propagation test |
| `docs/HOMELAB-HUB-HANDOVER.md` | **new** project handover |
| `docs/container-group-management-phase3.md` | **new** this report |

Unrelated pre-existing untracked files (`opencode.json` and earlier phase reports) were left
untouched.

No changes were made to migrations, the FolderView importer, scheduler/background work, or the
live installation's database.

---

## 6. Tests

### 6.1 Backend

New suite: `backend/tests/test_group_management.py` (15 tests). Coverage against the requested
matrix:

| Requirement | Test(s) |
|-------------|---------|
| Group creation/editing/archival | `test_create_edit_archive_and_restore_manual_group`, `test_group_archival_hides_effective_memberships_and_restores` |
| Imported vs manual groups | `test_management_read_endpoint_is_public_and_host_scoped`, `test_imported_groups_allow_colour_and_icon_but_not_rename` |
| Manual assignment overrides | `test_manual_override_precedence_and_revert` |
| Explicit ungrouped override | `test_explicit_ungrouped_override` |
| Reverting to imported assignment | `test_manual_override_precedence_and_revert`, `test_delete_group_guards` |
| Host isolation | `test_group_validation_and_name_conflicts`, `test_assignment_host_and_archive_validation`, management view host scoping |
| Container recreation with same name | `test_container_recreation_keeps_override_identity` |
| Missing/unmatched containers | `test_management_read_endpoint_is_public_and_host_scoped`, sync report tests |
| Re-import preserving overrides | `test_reimport_preserves_manual_override` |
| Protected endpoints/permissions | `test_management_writes_are_disabled_without_a_configured_token`, `test_management_writes_require_a_valid_token`, `test_sync_is_protected_and_requires_a_configured_path` |
| Invalid inputs/conflicting names | `test_group_validation_and_name_conflicts`, `test_assignment_host_and_archive_validation` |
| Dry-run vs apply | `test_sync_dry_run_and_apply` |
| Grouped map/layout regressions | existing `test_effective_groups.py` plus frontend grouping/layout tests |
| Legacy backup compatibility | existing `test_backup.py` (natural-key groups, older exports) |

Full suite: **62 passed** (`backend/.venv/Scripts/python.exe -m pytest -q`). One pre-existing
`SAWarning` from `backend/app/routes/inventory.py:106` during `test_backup.py`; unrelated to
Phase 3.

### 6.2 Frontend

- `frontend/tests/theme.test.js` (new):
  - all semantic control tokens exist and `--hlh-control-fg` derives from `--pico-contrast`;
  - the selector base rule uses `--hlh-control-fg` and no longer `--pico-color`;
  - active, hover, focus-visible and disabled rules exist.
- `frontend/tests/grouping.test.js`:
  - new test asserts `groupColor` is propagated and the icon prefixes the group label;
  - all existing hierarchy/layout/anchor tests still pass.
- Existing `mapViews.test.js` and `workspace.test.js` unchanged.

Full suite: **46 passed** (`npm test`).

### 6.3 Build

`npm run build` succeeds (86 modules). Output includes the pre-existing Vite advisory that the
MapPage chunk exceeds 500 kB; no new warnings remain (the earlier unused `.create-card p` CSS
selector was removed).

---

## 7. Manual verification checklist (for deployment)

1. Open `/groups`; confirm hosts and groups load without a token and write buttons are disabled.
2. Save a deliberately invalid token → write returns 401 with a readable error.
3. Save the valid token; create a manual group with colour/icon; verify it appears in Grouped
   mode after refresh with the icon label and coloured border.
4. Move an application to the manual group → source shows "Manual override"; verify the imported
   group is still shown in the Imported column.
5. Choose "Ungrouped" → source shows "Manually ungrouped"; the app leaves the grouped card.
6. Revert → effective group returns to the FolderView category.
7. Archive an imported group → its members disappear from Grouped mode; restore → they return.
8. Attempt to delete an imported/non-empty group → blocked with an explanation; delete an empty
   manual group → succeeds after confirmation.
9. Preview FolderView sync → counters shown, nothing changes; Apply → groups/assignments update,
   overrides remain, report shows untouched overrides and unmatched containers.
10. Toggle light/dark and check the Graph/Grouped/Tree selector: inactive, hover, active, focus
    and disabled states are all readable.
11. Confirm Graph saved positions and Grouped manual anchors survive all of the above.

---

## 8. Deployment steps (recommended)

1. **Back up first.** Copy `data/homelab-hub.db` and take an inventory export
   (`GET /inventory/export`). Grouping data is included via natural keys.
2. Build the fork image (no new migration in this phase; `009` already applied by Phase 1/2):

   ```bash
   docker build -t homelab-hub:phase3 .
   ```

3. Update the Betty compose file:
   - publish the existing host port (`8790:8000` in the current setup);
   - keep `./data:/data`;
   - set `HLH_ADMIN_TOKEN` from a secret/`.env` file (do not commit it);
   - optionally mount the FolderView config read-only:
     `/boot/config/plugins/folderview.plus/docker.json:/config/folderview-docker.json:ro`
     and set `FOLDERVIEW_CONFIG_PATH=/config/folderview-docker.json`.
4. Recreate the container (`docker compose up -d`), then verify:
   - `GET /api/health` → `{"status":"ok"}`;
   - `/groups` loads; writes return 503 if the token is unset, 401 if wrong;
   - run a **Preview sync** before any Apply.
5. Keep the previous image tag and the database backup until the manual checklist passes.

**Rollback:** restore the previous image tag and the backed-up database. Do not run
`alembic downgrade 009_container_groups` unless grouping data loss is acceptable — it drops the
three group tables.

---

## 9. Outstanding issues and limitations

- **Auth scope:** only the new container-group writes are protected. Existing inventory CRUD,
  `/inventory/import`, document editing and `/map/layout`/`/map/edges` remain unauthenticated.
  Front the app with an authenticating reverse proxy or extend the token gate in a later phase.
- **Single shared token:** no users, roles, attribution or audit log; stored in sessionStorage
  and cleared at session end.
- **No scheduled sync:** sync is operator-triggered only; one configured path and one host per
  request.
- **Imported names/hierarchy:** imported group names cannot be renamed; `external_parent_id` is
  preserved but not rendered as nested groups.
- **Deletion policy:** imported and non-empty groups can only be archived. There is no bulk
  reassignment/merge flow.
- **Identity limits:** duplicate container names on one host are indistinguishable; renaming a
  host or an app without recorded Docker metadata changes identity keys.
- **Browser-local state:** layouts, anchors and saved views do not sync across browsers.
- **Test coverage:** frontend tests cover pure logic and theme invariants only; map rendering and
  the management page still need manual browser validation on Betty.
- **Build size:** the MapPage chunk remains above Vite's 500 kB advisory threshold.

---

## 10. Git state

All Phase 3 work is in the working tree on `feature/homelab-redesign`. Nothing was committed,
pushed or deployed by this session, and the live installation/database was not modified.
