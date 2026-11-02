# Docker snapshot exporter

`scripts/docker-snapshot.sh` collects a read-only Docker inventory and writes the
Phase 4 [container snapshot contract](phase4-reconciliation.md#separate-container-input-contract)
(`schema_version: 1`). It exists so a real, complete snapshot no longer has to be
assembled by hand from `docker inspect`.

It is deliberately separate from the web application:

- It runs on the Docker host (or inside the Docker VM) as an ordinary shell script.
- It never imports or applies anything. Loading the file into Reconciliation remains
  an explicit, reviewed operator action.
- The web application is not given the Docker socket, Docker credentials or a
  collection schedule.
- It exports **container name, container ID, image ID and image reference only**.
  Environment variables, labels, mounts, ports, health checks and other inspect
  fields are discarded before the JSON is written.

This document describes the supported manual execution method and how to load the
result. It does not authorize deployment, scheduling or changes to Betty.

## Requirements

| Requirement | Notes |
|-------------|-------|
| Bash 4 or newer | Default shell on Unraid and normal Linux distributions. |
| Docker CLI | The user running the script must be able to run `docker ps` (Unraid root shell already can). |
| `jq` | Used to build and validate the JSON. No Python is needed on the host. |

If `jq` is not installed, install it from Unraid **NerdTools** (the `jq` package) or
place the static binary on `PATH`. Confirm with:

```sh
jq --version
```

`jq` is a single binary with no runtime dependencies; installing it does not add
Python or change the Docker daemon configuration. The script stops with a clear
error (exit code 2) if it cannot find `jq`.

## Supported execution

Run the script from the repository checkout on the Docker host. The `--host-key`
value must match the **root hardware host** selected on the Reconciliation page
(case-insensitive), not an individual app or VM name:

```sh
cd /mnt/cache/appdata/homelab-hub-redesign-source
bash scripts/docker-snapshot.sh --host-key Betty \
  --output /mnt/user/backups/homelab-hub/betty-docker-snapshot.json
```

Without `--output`, a timestamped file is written in the current directory:

```text
docker-snapshot-betty-20261102T120000Z.json
```

Examples for the two known Docker locations:

```sh
# Betty (Unraid host Docker daemon) - HOST_KEY is the root hardware record.
bash scripts/docker-snapshot.sh --host-key Betty --output /tmp/betty-docker.json

# Blackbox (Docker inside a VM) - run this inside that VM, not on Betty.
bash scripts/docker-snapshot.sh --host-key Blackbox --output /tmp/blackbox-docker.json
```

Optional arguments and environment variables:

| Argument | Environment variable | Purpose |
|----------|----------------------|---------|
| `--host-key <name>` | `HLH_HOST_KEY` | Root hardware host key. Required. |
| `--output <path>` | `HLH_SNAPSHOT_OUTPUT` | Destination file. |
| `--source <text>` | `HLH_SNAPSHOT_SOURCE` | Recorded `source` label. |
| `--docker-bin <path>` | `HLH_DOCKER_BIN` | Non-default Docker CLI. |
| `--jq-bin <path>` | `HLH_JQ_BIN` | Non-default `jq`. |

The script uses `docker ps --all --quiet --no-trunc` followed by a single
`docker inspect --type container` call for those IDs. `--all` is what includes
stopped and retained rollback containers. Because `docker inspect` receives the
complete ID list at once, a container removed mid-collection fails the whole
snapshot instead of silently dropping an entry.

## Output

```json
{
  "schema_version": 1,
  "host_key": "Betty",
  "source": "docker-snapshot.sh v1 (docker ps --all + docker inspect)",
  "status": "success",
  "complete": true,
  "coverage": "all_containers",
  "completed_at": "2026-11-02T12:00:00Z",
  "containers": [
    {
      "container_name": "plex",
      "container_id": "…64 hex characters…",
      "image_id": "sha256:…",
      "image": "plex:latest"
    }
  ]
}
```

- `completed_at` is the real UTC completion time of the collection, written after
  `docker inspect` returns and the result is mapped.
- Container and image IDs are **observations**, not identities. HomeLab-Hub matches
  on normalized root host + Docker container name.
- An explicitly empty `containers` array with `status: success`, `complete: true`,
  `coverage: all_containers` is valid evidence for a host with no containers.

## Failure behaviour

The exporter only writes a successful all-container snapshot when the complete
collection succeeded and passed validation. Otherwise it writes a snapshot with:

```json
{
  "status": "failed",
  "complete": false,
  "coverage": "unknown",
  "containers": [],
  "error": "…short diagnostic…"
}
```

and exits with code 3. That file is still valid contract input, but it can never
prove absence: the Reconciliation page treats it as non-authoritative and refuses
write previews. A failed snapshot intentionally lists no containers, so partial
output is not mistaken for a complete host inventory.

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | Complete all-container snapshot written. |
| `1` | Unexpected scripting failure. |
| `2` | Invalid usage/configuration or missing `jq`; no snapshot written. |
| `3` | Docker collection failed; explicit failed snapshot written. |
| `4` | Snapshot could not be written/validated atomically; previous file untouched. |

Output is written to a temporary file in the destination directory, validated with
`jq`, then renamed over the destination. Interrupted or invalid runs never leave a
truncated snapshot file.

## Loading into the Reconciliation page

1. Start the test instance (`http://192.168.1.80:8790`) and open
   **Reconciliation** (`#/reconciliation`).
2. Select the same root hardware host that was used as `--host-key`. A snapshot
   whose `host_key` does not match the selected host is rejected.
3. Use **JSON snapshot file** to upload the exported file (5 MB limit), or paste it
   into **Paste snapshot JSON**.
4. The comparison is read-only. Review matched containers, additions, changed
   IDs/images, duplicates, confirmed-absent recorded Docker identities and grouping
   gaps.
5. To change inventory, preview one addition, metadata update or manual match and
   apply it with the admin token. Nothing is applied automatically by the exporter
   or by the comparison itself.

Snapshot files are page-local: HomeLab-Hub does not persist scan history. A snapshot
older than 24 hours (or with a missing, future or `failed` status) is not
authoritative and cannot confirm container absence.

For the accepted Betty baseline (92 containers: 84 matched, eight expected
unmatched), see the [current handover](HOMELAB-HUB-HANDOVER.md). Those counts are
observations and must not be hard-coded into scheduling or validation.

## Not implemented here

- Automatic or scheduled collection. Running the script from cron/User Scripts is
  possible later, but no such job is configured by this repository; any scheduler
  must preserve the failed/incomplete semantics above.
- Automatic import, reconciliation apply or inventory deletion.
- Network scanning. Nmap-based discovery remains a separate source that feeds the
  same reconciliation engine without producing Docker identities.
- Docker socket access from the Flask application.

## Tests

The exporter tests run the real script against a fake Docker CLI and validate every
accepted output with the Phase 4 adapter:

```sh
python -m pytest -q backend/tests/test_docker_snapshot_exporter.py
```

They require `bash` and `jq`. On Windows, use Git Bash; the tests skip with an
explanation if either tool is unavailable. Override discovery with `HLH_TEST_BASH`
and `HLH_TEST_JQ` when the binaries are not on `PATH`. No Docker daemon, Betty
installation or network access is required for the tests.
