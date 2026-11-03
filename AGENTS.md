# HomeLab-Hub agent development instructions

Applies equally to OpenCode / DeepSeek Flash, Codex and other coding assistants.
Use ordinary Git, language tools and the existing checkout; no cloud-specific
plugins, published environment, fixed workspace path or particular model is required.

## Project and branch
- Repository: `smith844/homelab-hub`; integration branch: `feature/homelab-redesign`.
- Read [the handover](docs/HOMELAB-HUB-HANDOVER.md), migration history and recent commits.
  Current code/Git and the owner's latest instructions override historical reports.
- Flask + Svelte + SQLite; Graph, Grouped and Tree maps; Container Groups and Reconciliation.
- Phase 4 baseline: `e1e595b`. The owner verified 92 Betty containers: 84 matched,
  eight unmatched (redesign, six rollback containers, scanner), zero unmatched
  inventory apps. Most runtime/image IDs are not yet recorded. These are historical
  observations, not hard-coded targets or permission to add/delete resources.

## Current focus and next-session handover (3 November 2026)
- **Core purpose:** HomeLab-Hub is a readable, attractive, user-maintained visual
  reference for the owner's homelab: what devices/services exist, where they run,
  how they relate, and useful configuration details. Prioritise **Maps, Inventory,
  and presentation** over additional automation or discovery machinery. The owner
  explicitly wants to avoid growing this into an unnecessarily complex tool.
- Keep changes small, focused and reversible; prefer correcting inventory data
  or simplifying UI over new background systems, matching rules, migrations or
  integrations. Treat Nmap/UniFi discovery and Docker reconciliation as
  **optional supporting tools**, not the main workflow. No new discovery features
  are requested at present.
- The existing sidebar has a visually separated, collapsible **Tools** group
  containing Network discovery and Reconciliation. Its state is remembered, a
  selected tool automatically expands it, and the scan-running indicator persists.
  The owner confirmed this on the Betty **test** instance.
- Network discovery scan state survives in-tab navigation and browser refresh;
  the owner confirmed both the running indicator and completed results persist.
  UniFi read-only enrichment was verified against the owner's local UCG Max.
  Do not rework these completed features without a specific defect/request.
- Map **Depth** now applies to **All hosts** as well as selected hosts: level 0
  represents top-level placement records, with one level per child. Commit
  `9f9a5a63a920f16a07c3439ef54b69e6b1abc2d3` fixes the earlier all-hosts
  bypass. The owner visually confirmed **Host only** shows Betty and Blackbox,
  while **One level** displays their immediate children. A few Docker apps
  appeared at level 1 due to **inventory parent assignments**, not a depth bug.
  Preserve ancestor context, selected-member semantics, saved layouts and filters.
- Two identically named `Docker` inventory runtime records exist: Unraid/Betty
  (`192.168.1.80`) and the Proxmox-hosted Docker LXC/Blackbox
  (`192.168.1.200`). They are distinct runtime records; never merge them.
  The `homelab-hub-redesign` app was observed assigned directly to Betty
  (`Runs on: Hardware (bare metal)`) even though it is a Docker container;
  `homelab-hub-scanner` also appeared as a direct child in the map.
  **Do not assume these parent assignments have already been corrected.**
  The owner favours simply renaming the runtime display names to
  **`Unraid Docker`** and **`Proxmox Docker`** in the inventory rather than
  adding dropdown-label code. Renaming and reparenting are separate, user-reviewed
  inventory edits; neither is an instruction to perform them automatically.
- Current development branch head at this handover: `9f9a5a63a920f16a07c3439ef54b69e6b1abc2d3`.
  Check the **actual** remote branch head and local worktree before editing;
  the branch may have advanced. The immediately prior sidebar Tools commit was
  `2914953623d22381b7e80e967718094f838b57c3`. Historical commit IDs
  are context, not a request to reset or check out an old version.
- Work style: concise, actionable explanations; for supervised terminal tasks,
  offer one safe, verifiable step at a time. Do not contradict previous commands,
  guess which duplicate parent was selected or unnecessarily ask for information
  already supplied. Never expose tokens or secrets in commands/log output.
- **ChatGPT Work handover:** start by reading this file, the handover document
  and relevant current code; inspect branch status, then confirm the owner's
  **next requested task**. Do not launch a deployment, scan, inventory edit
  or other live action simply because this handover exists.

## Autonomous development loop
1. Inspect branch, status, relevant code and existing integrations. Preserve local
   work; do not discard changes or create extra worktrees without a clear owner request.
2. Investigate and implement reasonable, reversible, in-scope changes autonomously.
   Deliver a working vertical slice when scope is large; do not stop at a plan.
3. Scale checks: targeted tests plus frontend build for small UI changes; full relevant
   suites for significant backend work, with migration/rollback coverage for schema changes.
   Documentation-only work needs consistency/link/diff checks rather than unrelated builds.
4. Review for credentials, unintended files and unrelated refactoring. Keep secrets,
   private env files, live databases and infrastructure credentials out of Git.
5. Commit and push routine successful work **directly to `feature/homelab-redesign`**;
   verify the remote SHA. Do not create a feature branch/PR or request routine Git approval.
   Use a PR only for a significant architectural/operational reason or owner request.
6. End with a concise summary: changes, checks, commit SHA, remaining issues/decisions.
   Prefer useful functionality over extensive reports or unnecessary process documentation.
7. Distinguish observed facts, owner-reported validation, tests and planned work.

## Safeguards and invariants
- **Never modify the original HomeLab-Hub installation on Betty, host port 8000.**
- No automatic deployment to Betty. The deployment script's existence is not approval
  to execute it; obtain explicit approval for the actual deployment/production change.
- Back up the database before migrations. Request approval for destructive actions,
  live schema migrations, force pushes, production changes and irreversible operations.
- Preserve stable root-host + logical container-name identity, app/group IDs, imported
  FolderView data, explicit Ungrouped/manual overrides and saved map anchors/layout keys.
  Runtime container/image IDs are observations, not permanent identity. Network-wide
  discovery matching is read-only and independent of host-scoped Docker matching.
  It must not create, update, merge or delete inventory or change map layouts.
  UniFi integration is read-only, GET-only, API-key/TLS-verified, and never treats
  offline/historical clients as current Nmap hosts or writes to the controller.
- Preserve `hlh-discovery:v1` notes metadata when editing/extending importers. Comparison
  is read-only by default; reviewed apply needs admin authentication. Never auto-delete
  inventory or interpret failed/partial/missing scans as proof of absence.
- Existing legacy CRUD/import APIs are not fully authenticated. Preserve token gates on
  new writes; do not assume a trusted LAN makes arbitrary destructive imports safe.
- Reuse the separate Nmap scanner (`dpinna13/homelab-hub`, `feature/network-scanner`,
  observed `9feebd5`). It provides network observations, **not Docker identities**.
  Keep collection separate from reconciliation; no privileged Docker socket in the web app.

## Local development and checks
- Use a local virtual environment and `backend/requirements*.txt`; use `npm ci` in
  `frontend/`. Match the repository's toolchain instead of assuming a previous agent's paths.
- Backend from checkout root: `python -m pytest -q backend/tests` (activated environment).
- Frontend from `frontend/`: `npm test`, `npm run build`, `npm run test:browser` as relevant.
- Playwright needs installed Chromium; use `npx playwright install chromium` or an existing
  executable through `CHROMIUM_PATH`. Inspect actual screenshots for rendering changes.
- Use fresh local test databases. Do not connect to Betty or request production tokens for
  ordinary tests. Use one Gunicorn worker unless concurrency/signing/storage are redesigned.

## Betty test deployment: reference only, approval required
- Test address: `192.168.1.80:8790`; container: `homelab-hub-redesign`.
- Source: `/mnt/cache/appdata/homelab-hub-redesign-source`.
- Data: `/mnt/cache/appdata/homelab-hub-redesign-data`.
- Private env: `/mnt/cache/appdata/homelab-hub-redesign-config/phase3.env` (never commit values).
- FolderView input: `/boot/config/plugins/folderview.plus/docker.json`, read-only.
- Script: `scripts/deploy-betty-test.sh`; execute on Betty only after explicit approval.
  The separate idempotent `scripts/deploy-betty-test-scanner.sh` builds/starts only
  `homelab-hub-nmap-test` on the private `homelab-hub-nmap-test-net` bridge and
  publishes no host port. Shared token/ranges live in the private
  `scanner-test.env` (mode 600), never in Git or command output.
  It builds, takes/verifies an online SQLite backup, retains the stopped previous container,
  starts the test image on host 8790 and health-checks it. No automatic database restoration.
- Retained rollback containers share the data volume; they are not frozen database backups.
  Do not delete them to eliminate reconciliation discrepancies.
- Images predating migration 010 cannot start normally against revision 010. Cross-migration
  rollback requires **both the matching pre-migration database backup and previous image**.
  Restoring data requires approval; do not falsify Alembic's version marker.
- The upstream compose template uses host port 8000. Do not use it as a Betty test shortcut.
