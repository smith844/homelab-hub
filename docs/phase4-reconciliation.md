# Phase 4 — first reconciliation slice

Open **Reconciliation** (`#/reconciliation`) and choose the root hardware host.
Without a snapshot, FolderView and ungrouped counts are investigation targets;
missing scan data never marks applications absent. The first implementation is
committed as `e1e595b`; it did not access either Betty installation.

## Owner-verified Betty comparison (handover update)

The owner reports **92 Docker containers**, **84 inventory matches**, **eight
unmatched** (one current redesign container, six retained rollback containers and
one separate network scanner), and **zero inventory applications without a
discovered container match**. Most inventory entries do not yet record container/
image IDs. These are point-in-time owner-verified results, not live agent probes.
The earlier seven FolderView gaps and eleven ungrouped apps are separate grouping
investigation targets; do not conflate their counts with the eight Docker resources.
Do not automatically add all eight or delete retained backups. See the
[current handover](HOMELAB-HUB-HANDOVER.md) for workflow, deployment safeguards and
next priorities: read-only Docker collection, reviewed bulk metadata apply,
persistent exclusions, existing-scanner integration and dashboard filtering.

## Verified existing scanner

Inspected `dpinna13/homelab-hub`, branch `feature/network-scanner`, exact deployed
commit `9feebd509ae58ad98bc7fc8881100b51e6add357`, particularly:
`backend/app/routes/scanner.py`, `services/scanner.py`, `services/scan_manager.py`.

- `discover`: IPv4 nmap/ARP/ICMP/TCP discovery, reverse DNS and MAC/vendor hints.
- `identify`: hostname/MAC/OS inference, with a less-privileged nmap fallback.
- `portscan`/`probe-http`: TCP services and HTTP header/title/name hints.
- `interfaces` and asynchronous job `status/<scan_id>` support its existing UI.
- Jobs are in memory and completed/failed jobs expire after 600 seconds. Status
  returns type, status, progress, results, error and params; it does NOT return
  its internally recorded started/finished timestamps.
- There are **no Docker identities, container/image IDs, Docker exports, or Proxmox
  API inventory** in this implementation. Existing Docker configuration notes in
  HomeLab-Hub are a separate inventory convention, not network-scanner output.
- Its import endpoints mutate that process's database directly, deduplicate hosts
  by IP/MAC and apps by port/parent, and have no preview/admin gate in this commit.
  Do not assume the two containers share a database. Its HTTP probe also disables
  TLS verification; that behaviour is not copied into HomeLab-Hub.

This slice adapts saved **actual status JSON** (the `data` wrapper is accepted)
into read-only IP/MAC or IP+port comparisons within the selected host scope.
A failed HTTP probe remains unverified even if its job completed. Network results
cannot prove Docker presence/absence or make container changes.

Phase 5 adds a separate, token-authenticated Nmap service and a Network discovery
page. The page starts scans through `/api/network-discovery/scan`, then submits the
scanner status to this same adapter for comparison. It supports `completed`,
`partial` and `failed` statuses; partial/failed results stay visible but are
unverified. The scanner never calls upstream import endpoints and never writes
inventory. See [network-discovery.md](network-discovery.md) for architecture,
approved-target configuration, APIs and supervised deployment prerequisites.

## Separate container input contract

The modular container adapter accepts an operator-supplied snapshot, not an
invented upstream scanner API:

```json
{
  "schema_version": 1,
  "host_key": "betty",
  "source": "separate container collector",
  "status": "success",
  "complete": true,
  "coverage": "all_containers",
  "completed_at": "2026-11-02T12:00:00Z",
  "containers": [
    {"container_name": "plex", "container_id": "observed-id", "image_id": "observed-image-id", "image": "plex:tag"}
  ]
}
```

Use the real completion time. Docker-inspect `Name`, `Id`, `Image`, `Config.Image`
are also accepted within `containers`; environment/mounts/extra fields are ignored.
Do not put credentials in snapshots. `complete:false`, `coverage:running_only`,
unknown/failed status, missing/future/older-than-24-hour timestamps cannot establish
absence. A successful complete snapshot must explicitly include `containers`,
including stopped containers; an explicitly empty list can confirm an empty host.
Coverage/success are uploaded declarations, not independently verified live probes.
Newer recorded observations block older snapshots from regressing metadata or
claiming current absence. Unrecorded/non-Docker services remain unknown.

The separate host-side exporter [`scripts/docker-snapshot.sh`](../scripts/docker-snapshot.sh)
writes this contract from the Docker CLI and is documented in
[docker-snapshot-exporter.md](docker-snapshot-exporter.md). It runs outside the web
app, never imports or applies changes, and emits explicit failed evidence rather
than a falsely complete snapshot.

## Review and apply

Comparison/previews are read-only. Preview one addition, matched metadata update
or manual match; applying requires `HLH_ADMIN_TOKEN` through the existing session
admin mechanism. Signed previews expire after ten minutes/restart and reject
concurrent inventory/grouping changes. SQLite apply checks/writes are serialized.
No action deletes inventory.

Matching uses root host + normalized Docker name, never transient runtime IDs.
Existing app IDs, parent, display name, icon and user notes are retained. A reserved
`hlh-discovery:v1` JSON comment in notes records the chosen name and last observations;
ordinary inventory export/import therefore preserves matches without a schema
migration. Preserve that owned marker if editing notes or extending another importer.
Existing manual overrides (including explicit Ungrouped) follow a manually matched
identity. Conflicting choices/duplicate identities block the action. FolderView
assignments, group IDs and browser map anchor/layout keys are not rewritten.

### Reviewed bulk metadata updates

`POST /api/reconciliation/preview-bulk` and
`POST /api/reconciliation/apply-bulk` extend the same reviewed-action model to many
confidently matched containers:

- The preview requires a **successful, fresh, authoritative** all-container snapshot
  and selects only rows classified `matched`. Duplicate, older, excluded,
  unconfirmed-absent and un-matched observations are reported as skipped, never
  silently updated. An explicit `container_keys` selection containing an ineligible
  row is rejected instead of partially applied.
- The plan contains only `container_id`, `image_id`, `image`, `observed_at` and the
  target application id. Application names, descriptions, user notes, parents,
  icons, grouping overrides, imported assignments and map data are not fields and
  are not written. The existing Docker label casing is retained.
- Apply requires the admin token and a signed unexpired preview. The state
  fingerprint check and every per-application metadata write happen in **one SQLite
  transaction** (`BEGIN IMMEDIATE`), with full rollback on error. No application is
  created or deleted, and nothing runs in the background.

### Persistent exclusions

`GET/POST /api/reconciliation/exclusions` and
`DELETE /api/reconciliation/exclusions/<id>` manage explicit host-scoped policy
rows keyed by normalized Docker container name. Writes require the admin token.
Exclusions never infer from name prefixes, never modify Docker, inventory or
grouping, and never delete anything. They only move matching resources out of
ordinary missing-inventory warnings and into a separately listed **Excluded**
section; snapshots still show whether each exclusion was observed. Removing an
exclusion restores the ordinary warning. An excluded unmatched container is not
eligible for add/match/bulk actions until its exclusion is removed. Exclusions are
stored in the SQLite `reconciliation_exclusions` table (migration 011), so they
survive restarts.

Dashboard summaries distinguish matched, unmatched, excluded, uncertain and
not-seen resources, and the page can filter/search discovered rows without hiding
the detailed sections.

Snapshots are page-local; there is no persisted scan history, automatic refresh,
network-resource mutation or trusted live transport yet. The separate scanner now
provides authenticated start/status transport and read-only comparison; next work is
persisted scan history/freshness, reviewed inventory/map actions, optional verified-
TLS HTTP probing and supervised deployment/scheduling. This also determines how
Betty and Blackbox produce authoritative container data; network probing alone
cannot supply it. No deployment or live collection is authorized by these
instructions.
