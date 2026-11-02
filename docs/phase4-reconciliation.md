# Phase 4 — first reconciliation slice

Open **Reconciliation** (`#/reconciliation`) and choose the root hardware host.
Without a snapshot, FolderView and ungrouped counts are investigation targets;
missing scan data never marks applications absent. Betty's reported seven/eleven
entries have not been inspected or modified during development.

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
It does not call the scanner, start scans, copy nmap dependencies or call import
endpoints. A failed HTTP probe remains unverified even if its job completed.
Network results cannot prove Docker presence/absence or make container changes.

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

Snapshots are page-local; there is no persisted scan history, automatic refresh,
network-resource mutation or trusted live transport yet. Next integration work is
an authenticated read-only transport for the existing scanner and a separately
verified all-container collector/export (including Docker-in-VM host provenance).
This also determines how Betty and Blackbox produce authoritative container data;
network probing alone cannot supply it. Neither Betty installation was accessed.
