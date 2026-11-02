# Container group polish — review notes

> Historical implementation/validation report. Branch states, deployment guidance and
> test counts below describe that development cycle; the changes are now committed
> on the development branch. Use [the current handover](HOMELAB-HUB-HANDOVER.md) and
> [AGENTS.md](../AGENTS.md) for current state, workflow and deployment approvals.

Changes are prepared on `fix/container-group-polish`, based on `feature/homelab-redesign` at `cce1db8`.
No deployment, Betty connection, live database access, or port-8000 operation was performed.

## Behaviour

- Container Groups renders HTTP/HTTPS image icons and raster base64 data images through a
  shared validator and Svelte component. Emoji remain text; missing, invalid or failed images
  use a folder glyph. Markup, executable schemes, credential-bearing URLs and SVG data payloads
  are rejected. Remote image requests on this page suppress the referrer.
- Grouped map uses validated images as Cytoscape card backgrounds, retaining readable group
  names/counts if an image cannot load. URLs no longer appear in labels. Group identities,
  layout keys and manual anchors are unchanged. Map images use anonymous cross-origin loading;
  servers that disallow that loading may show only the fallback card name.
- Buttons share centred flex alignment, a bounded line height and vertical padding that fits
  the existing fixed heights. Explicit theme contrast colours keep custom control text readable.
- Sync reports identify group name, external id, action, individual effective fields and raw
  `source_metadata.*` fields, with before/after values. Missing fields are distinguished from
  empty/null values. JSON key order alone is not an update. Timestamp/settings/membership changes
  can still update the source snapshot; the preview explains those updates explicitly.
- Source metadata remains a raw FolderView snapshot. Local icon, sort and active choices are
  tracked separately; colour remains locally owned. Assignment overrides remain untouched.
  Saving an unchanged icon/order in the UI does not accidentally claim local ownership.
- New additive migration `010_group_customisations` adds one nullable text column. Backup exports
  include the local ownership flags and imports retain them; older backups remain supported.
  Run normal `alembic upgrade head` before starting against an existing database.

## Existing Phase 3 data

Phase 3 did not record edit provenance. For legacy rows, preserve ordering and inactive state
conservatively; infer icon customisation by comparing it with the saved source icon. These inferred
choices are persisted on the next apply/edit and survive later syncs. A legacy automatically
archived group is indistinguishable from a manually archived one and therefore remains archived
until explicitly restored. Newly imported groups continue to follow source icon/order until
edited locally; newly source-archived groups reactivate when their folder returns, unless the
operator has explicitly chosen their active state. There is currently no UI to relinquish an
explicit local presentation choice back to automatic source ownership.

## Validation (Linux, Python 3.12.14, Node 24.19.0)

- Full backend: **70 passed**, including a populated Phase 3 migration and repeated upgrade,
  dry-run/apply equivalence, detailed field changes, null additions, local choices, repeated
  imports and backup restoration. One existing SQLAlchemy identity-map warning in inventory import.
- Full frontend unit suite: **50 passed**, including icon allow/reject cases, safe Grouped image
  data, readable fallback labels, existing layout/anchor tests and theme invariants.
- Playwright Chromium: **4 passed**, covering both light and dark themes, actual management icon
  loading/fallback, Save/Create group line-box centring, detailed preview rendering, Graph/Grouped/
  Tree active/hover/focus contrast, toolbar contrast (at least 4.5:1), and Grouped canvas image styling.
  Browser APIs/icons are fixtures; these tests do not connect to Betty.
- Production build: succeeds, 89 modules. Existing MapPage >500 kB chunk advisory remains.
- Local Gunicorn smoke: health, management, effective grouping, graph, built SPA and its JavaScript
  asset all return 200, using an isolated `/tmp` database on port 5001.
- `git diff --check` passes. Lockfile changes are limited to browser-test development dependencies.

## Reproduce

From `backend/`, use the installed `/workspace/hlh-venv/bin/python -m pytest -q`.
From `frontend/`:

```sh
npm ci
npm test
npm run build
CHROMIUM_PATH=/usr/bin/chromium npm run test:browser
```

For other machines, install Playwright Chromium with `npx playwright install chromium` and omit
`CHROMIUM_PATH`, or point it at an existing Chromium executable. The browser suite manages its own
Vite process on port 3000, which must be free. Pico CSS is read from the test-only npm dependency
rather than fetched from the CDN. Browser output directories are ignored.

The cloud environment draft contains tested dependency/build instructions, startup commands,
local database/port guidance and the selected repository revision/path. Saving the draft does not
publish it or deploy the application. Review/save the environment settings and publish the cloud
environment when desired. Review the application changes separately before any later Betty deployment.

## Pre-publication migration review

Migration 010 adds only nullable `container_groups.customisations_json TEXT`, without a default,
index, foreign key, constraint or data backfill. Existing rows receive NULL; Alembic's version
marker advances from `009_container_groups` to `010_group_customisations`. Its downgrade drops
only the new column, losing local ownership tracking (including inferred legacy choices).

A separate local Phase 3-schema fixture containing 14 imported groups, one archived manual group,
14 assignments and two overrides (one explicit ungrouped) was upgraded. All original column values
in all three grouping tables matched exactly before/after, including ids and active flags. This is
synthetic-data validation, not an inspection or migration of Betty's database.

**Old-image rollback limitation:** original cce1db8 backend code read health, management and
effective grouping successfully against that migrated fixture. However, the old image's entrypoint
runs `alembic upgrade head` and exits with `Can't locate revision identified by
'010_group_customisations'`. Therefore an ordinary switch back to the Phase 3 image does not work.
For an operational rollback, prefer restoring a consistent pre-upgrade database backup with the
old image. A deliberate downgrade using the NEW code's migration chain is another option, but loses
the ownership-tracking column and should be rehearsed on a copy first. Never edit/stamp the version
marker merely to hide the mismatch. The old importer also lacks the new preservation policy.

Five simulated metadata-only changes produced five named group updates, each with exact
`source_metadata.updatedAt` before/after values. The real five changes on Betty have not been
inspected; their current count and fields must be established by a fresh dry-run when a later
Betty deployment is separately authorised. Migration 010 itself performs no sync.

**Migration hardening completed:** migration 010 checks the reflected column list explicitly.
Only an already-existing `customisations_json` column causes the add to be skipped. Inspection
and DDL failures propagate normally. New regression tests execute the upgrade twice against a
populated existing column and confirm its values survive, and cause a real SQLite read-only DDL
failure to verify that `OperationalError` reaches the caller. The shared helper and other
migrations are unchanged.

The saved cloud draft contains no secret declarations, configured runtime values or credential
values. Token/path names are instructions only. It contains cloud-specific workspace/venv paths,
a local `/tmp` database, loopback development ports, a Chromium executable path, the name Betty in
a no-deployment instruction, and the repository identity/revision. These are not secrets but should
be generalised for a public reusable template if desired. The draft is still pinned to cce1db8;
commit the reviewed changes and update its repository pin before relying on Git-based reproduction.
Cloud snapshot publication and Git publication are separate operations.


## Final branch review

The final checks passed: 70 backend tests, 50 frontend unit tests, four Chromium tests and the
production build. Existing SQLAlchemy identity-map and Vite chunk-size warnings remain. Source,
migration, test and dependency changes were reviewed for unintended files and credentials;
no credential values or local databases are included. Test-only tokens are synthetic fixtures.
The additional npm dependencies are development-only; production dependency versions are unchanged.
The backend was validated on Python 3.12, not inside the production Python 3.14 Alpine image.

No cloud environment settings were updated during the fix-branch/PR workflow. No production
installation was modified. For any future rollback, restore BOTH the previous image and a
consistent pre-migration database backup; a simple image-only rollback fails at old Alembic startup.
