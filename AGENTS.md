# HomeLab-Hub agent development instructions

## Project and branch
- Repository: `smith844/homelab-hub`
- Working integration branch: `feature/homelab-redesign`
- Read `docs/HOMELAB-HUB-HANDOVER.md`, migration history and recent commits for context. The handover may contain historical status; Git and current code are authoritative.
- Application: Flask + Svelte + SQLite, with Graph, Grouped and Tree map presentations.
- Test deployment: Unraid Betty at `192.168.1.80:8790`. Original installation at port `8000` is **out of scope**.

## Streamlined development loop
1. Investigate and implement reasonable, reversible, in-scope changes autonomously.
2. Use targeted tests and frontend build for limited UI fixes. Use full relevant suites for major functionality; add migration/rollback tests for schema or importer changes.
3. Review diffs for credentials, unintended files, and unrelated refactoring.
4. For routine successful changes, commit and push **directly** to `feature/homelab-redesign`. A separate branch and PR are not required.
5. Verify the remote branch commit, then report the SHA, tests and any significant caveats succinctly.
6. Avoid creating large status reports for small changes; keep documentation meaningful and current.
7. Do not assume success: distinguish completed/verified work from planned work.

## Escalation and approvals
- Do not force-push, delete data, rewrite Git history, expose secrets or perform irreversible changes without explicit approval.
- Design and test schema migrations, but request approval before applying them to a live database.
- **Do not deploy to Betty automatically**. The owner must first explicitly approve the tested deployment process and any actual deployment.
- Never touch the original port-8000 HomeLab-Hub installation.
- Existing inventory CRUD routes may lack authentication; do not assume the entire app is access-controlled.
- Preserve host-scoped grouping identity, imported FolderView data, manual overrides, saved map anchors and browser layout keys.

## Betty test deployment
- Git checkout: `/mnt/cache/appdata/homelab-hub-redesign-source`
- Persistent data: `/mnt/cache/appdata/homelab-hub-redesign-data`
- Private env file: `/mnt/cache/appdata/homelab-hub-redesign-config/phase3.env` (never commit)
- FolderView input: `/boot/config/plugins/folderview.plus/docker.json` (read-only)
- Test container: `homelab-hub-redesign`; host port 8790 → container port 8000
- Once approved for local execution, run `bash scripts/deploy-betty-test.sh` from the checkout on Betty.
- Script builds the updated image, takes an online SQLite backup and checks integrity, preserves the old container, then health-checks the new one. **It never restores a database automatically**.
- IMPORTANT: images predating migration 010 cannot start normally against a revision-010 database. Rolling back across migrations requires the matching pre-migration SQLite backup **and** previous image; do not just switch the image.
