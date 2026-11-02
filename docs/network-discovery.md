# Network discovery (Nmap)

Phase 5 adds a **separate, restricted Nmap scanner** as another read-only
discovery source. It is deliberately independent from Docker collection: an open
network port does not imply a Docker container, and network observations never
create, overwrite or delete inventory.

## Architecture

```text
Svelte Network discovery page
        │  admin-authenticated start / read-only status + comparison
        ▼
Flask web app  ──HTTP + X-Scanner-Token──►  scanner service (this repo)
        │                                      │
        │                                      └── nmap subprocess (validated argv)
        │
        └── existing /api/reconciliation/compare for IP/MAC/IP+port comparison
```

- The web container does **not** run nmap, hold network capabilities or mount the
  Docker socket. It validates the target against its own approved ranges and
  proxies a small request to the scanner.
- The scanner is token-authenticated, binds to loopback by default and exposes only
  start/status/health endpoints.
- Scanner jobs live in memory with a bounded TTL. No inventory or map is changed.
  Comparison reuses the Phase 4 network adapter and is displayed next to the scan.
- The scanner cannot add, edit or delete HomeLab-Hub records.

## Reused upstream scanner components

Source inspected: `dpinna13/homelab-hub`, branch `feature/network-scanner`,
commit `9feebd509ae58ad98bc7fc8881100b51e6add357`.

Reused/adapted:

- Host-discovery options (`-sn -PR -PE -PS22,80,443,8080 -PA80`) and bounded
  retries/timeouts from `services/scanner.py`.
- Hostname, MAC normalization and Nmap vendor parsing for host discoveries.
- Unprivileged TCP connect scanning (`-sT`) instead of raw SYN scans.
- Threaded background job lifecycle and TTL eviction ideas from `scan_manager.py`.

Deliberately not reused:

- `python-nmap` and `requests` dependencies — replaced by argument-safe
  `subprocess` plus Nmap XML parsing, which is easier to test and avoids extra
  packages in the scanner.
- OS fingerprinting / aggressive probes (`-O --osscan-guess`, `-A`, NSE scripts).
- HTTP probing that disables TLS verification.
- Direct inventory/import endpoints from the upstream scanner. Comparison and any
  future apply remain inside HomeLab-Hub's reviewed reconciliation model.

## Runtime requirements

| Component | Requirement |
|-----------|-------------|
| Scanner | Python 3.10+ and the `nmap` executable (7.x). No Python packages are required. |
| Web app | Existing Flask app. No nmap, Python package or network capability is added. |
| Network | Web app must be able to reach the scanner address; scanner needs access to the approved target ranges. |

MAC addresses and vendor information require the scanner to see the same L2
network, typically host networking with `NET_RAW`/`NET_ADMIN` in a container. Without
that, host discovery and TCP service discovery still work, but MAC/vendor data is
usually unavailable. The scanner never uses `--privileged` and never mounts the
Docker socket.

## Configuration

### Web app

```sh
HLH_SCANNER_URL=http://127.0.0.1:8791
HLH_SCANNER_TOKEN=<shared random token>
HLH_SCANNER_APPROVED_RANGES=<verified-private-subnet>
HLH_SCANNER_DEFAULT_PORTS=22,80,443,445,3389,8080,8443
HLH_SCANNER_MAX_HOSTS=1024
HLH_SCANNER_MAX_PORTS=256
```

`HLH_SCANNER_APPROVED_RANGES` is an explicit comma-separated allowlist. Empty means
network discovery is disabled. The web app validates targets again before forwarding
so a browser cannot bypass the allowlist.

### Scanner

```sh
HLH_SCANNER_TOKEN=<the same shared token>
HLH_SCANNER_APPROVED_RANGES=<verified-private-subnet>
HLH_SCANNER_BIND=127.0.0.1
HLH_SCANNER_PORT=8791
HLH_SCANNER_DEFAULT_PORTS=22,80,443,445,3389,8080,8443
HLH_SCANNER_MAX_HOSTS=1024
HLH_SCANNER_MAX_PORTS=256
HLH_SCANNER_MAX_SCAN_SECONDS=300
HLH_SCANNER_MAX_CONCURRENCY=1
HLH_SCANNER_RETENTION_SECONDS=3600
HLH_SCANNER_NMAP=nmap
```

Both processes must use the same approved ranges. **Ranges are always supplied by
the operator.** VLAN numbers are never converted into subnets. For example, VLAN 10
being "Guest" does not imply `192.168.10.0/24`; verify the actual subnet and add only
that. Do not add every VLAN at once or scan automatically at startup.

## Running the scanner

Host-side (simplest for a supervised test):

```sh
cd /path/to/homelab-hub
export HLH_SCANNER_TOKEN="$(openssl rand -hex 32)"
export HLH_SCANNER_APPROVED_RANGES='<verified-private-subnet>'
export HLH_SCANNER_BIND=127.0.0.1
PYTHONPATH=scanner python -m hlh_scanner.server
```

Verify without exposing it publicly:

```sh
curl --silent http://127.0.0.1:8791/health
```

Container option (built, not deployed by this repository):

```sh
docker build -t homelab-hub-scanner:local scanner
docker run -d --name homelab-hub-scanner \
  --network host \
  --cap-add NET_RAW --cap-add NET_ADMIN \
  --read-only --tmpfs /tmp \
  -e HLH_SCANNER_TOKEN=... \
  -e HLH_SCANNER_APPROVED_RANGES='<verified-private-subnet>' \
  -e HLH_SCANNER_BIND=127.0.0.1 \
  homelab-hub-scanner:local
```

`--network host` is what enables MAC/vendor discovery on the local L2; a bridge
network still supports IP/TCP discovery but usually loses that information. Binding
to `127.0.0.1` means the web container must reach it through a deliberate host
gateway or private Docker network; do not publish the scanner port to the internet.
If the scanner must listen on a non-loopback interface, restrict it with host
firewall rules and keep token authentication enabled.

For the supervised Betty test instance, use the prepared dedicated bridge and
scripts instead of the host-network example:
[scanner-betty-test-deployment.md](scanner-betty-test-deployment.md). The scanner
there is `homelab-hub-nmap-test`, publishes no host port, and receives only
`NET_RAW` with all other capabilities dropped.

The supervised sequence uses the separate `scanner-test.env` described in that
document; the web deploy script passes it to the test container and no scanner
values need to be copied into `phase3.env`. Do not deploy or modify either running
installation without explicit approval.

## API

All `/api/scanner/*` requests require `X-Scanner-Token`. `/health` is public but
contains no targets or credentials.

```http
POST /api/scanner/scan
Content-Type: application/json
X-Scanner-Token: ...

{"target":"192.168.1.0/24","scan_type":"services","ports":"22,80,443"}
```

```json
{
  "scan_id": "…",
  "type": "portscan",
  "scan_type": "services",
  "status": "running",
  "progress": 0,
  "target": "192.168.1.0/24",
  "started_at": "2026-11-02T18:00:00Z",
  "completed_at": null,
  "hosts": [],
  "results": [],
  "warnings": [],
  "error": null,
  "complete": false
}
```

`GET /api/scanner/scan/<scan_id>` returns the same shape with `status` one of
`running`, `completed`, `partial` or `failed`, plus `completed_at`, host counts,
warnings and result rows. `scan_type=discover` returns one result per host;
`scan_type=services` returns one row per open TCP port and a separate `hosts` list.

Web bridge:

- `GET /api/network-discovery/config` — approved ranges, limits, scan types,
  whether URL/token are configured. No secrets.
- `POST /api/network-discovery/scan` — admin token required; validates target,
  starts the scanner, returns `202 {scan}`.
- `GET /api/network-discovery/scan/<uuid>` — read-only status proxy.
- `POST /api/network-discovery/reconcile` — read-only, network-wide matching of a
  scan status against the full inventory. No admin token is needed because it only
  reads inventory and cannot write.

## Network-wide inventory matching

The Network discovery page no longer requires a selected root host. It uses a
dedicated read-only matcher (`services/network_wide_reconciliation.py`) that indexes
identity evidence across the whole inventory:

- Hardware hosts: IP, MAC, hostname/FQDN and inventory name.
- VMs/runtimes: IP, MAC, hostname and parent hardware.
- Other devices: IP/hostname and inventory name.
- Application/service endpoints: explicit IP, parent IP (with lower confidence),
  hostname/FQDN and TCP port.
- Network members: `NetworkMember.ip_on_network` addresses and their network names.
- Network subnets: context only; a network record is never treated as a device.
- Storage pools and shares are not treated as devices; they have no reliable host
  identity in the current schema.

Evidence rules:

- Exact IP or MAC match to one device is a **matched** host-level result.
- A hostname-only match is **plausible** and explicitly warns that DNS may be stale.
- A hardware host and its single VM/runtime sharing an IP are **shared**, not a
  duplicate physical device.
- Multiple unrelated devices sharing an IP, or conflicting IP/hostname evidence, are
  **ambiguous**; this covers possible virtual IPs and shared endpoints.
- An address with only application/service records is **plausible** service-only
  evidence; it is not promoted to a physical host.
- Partial/failed scans mark all observations **unverified**. Missing observations
  never imply that inventory devices were removed.
- Service rows are separate from host rows. An explicit application IP+port is
  matched; an inherited parent IP+port or hostname-only service is plausible; multiple
  applications at the same IP+port are ambiguous.
- No confidence percentages are used; candidates and evidence labels are returned
  instead.

```http
POST /api/network-discovery/reconcile
{"scan": <scanner status object>}
```

The response contains `hosts`, `services`, `summary` counts and short reasons.
Candidate records include a type/id for the existing inventory links. The matcher
never creates, updates, merges or deletes inventory, never edits maps and never
changes Docker reconciliation.


## Status, failure and freshness

- `completed` means nmap finished successfully, XML parsed and
  `<finished exit="success"/>` was present. Hosts reported **down** do not prove
  absence.
- `partial` means a timeout, non-zero nmap exit or an incomplete Nmap run. Any
  parsed observations are retained for review, but the UI marks them uncertain and
  they cannot establish device absence.
- `failed` means no usable scan. It never proves absence.
- Results are in memory and expire after the retention period or scanner restart.
  Completion and start timestamps are exposed to the UI; there is no persisted scan
  history yet.
- The Reconciliation adapter treats every network observation as host/service
  evidence. It never maps a port to a Docker container and never writes inventory.

## Limits and safety

- Targets: IPv4 only, explicit address or CIDR, must be fully inside an approved
  private range; max 1024 addresses by default.
- Ports: explicit list/ranges, max 256 by default.
- Commands: fixed argv, no shell, no user-added nmap flags, no OS detection, no NSE,
  no HTTP probes and no auto-discovery of interfaces/VLANs.
- Jobs: bounded by `HLH_SCANNER_MAX_SCAN_SECONDS` and
  `HLH_SCANNER_MAX_CONCURRENCY` (default 1).
- Authentication: constant-time token comparison; scanner refuses to start without
  a token; web start requires the admin token.
- No Docker socket, no inventory writes, no automatic map changes.

## Comparison and review

The page posts the completed/partial scanner status to the network-wide matcher:

```json
{"scan": {"type": "portscan", "status": "completed", "hosts": [...], "results": [...]}}
```

The result separates host-level device matches from service-level endpoint matches.
Matched means evidence exists in inventory; it does not mean the record is current, and
it does not establish a Docker identity. Partial/failed results are unverified. Any
future inventory edit or map change must remain a separate reviewed action.

The Phase 4 host-scoped `compare_network_scan` adapter remains in use by the existing
Reconciliation page for saved network status responses. Docker container matching,
group assignments, manual overrides, exclusions and bulk metadata reconciliation are
unchanged.


## Tests

```sh
python -m pytest -q scanner/tests
python -m pytest -q backend/tests/test_network_discovery.py
python -m pytest -q backend/tests/test_network_wide_reconciliation.py
cd frontend && npm test
```

Scanner tests mock the Nmap command runner and XML outputs, so no live nmap or
network access is required. Backend tests mock the scanner HTTP bridge and validate
target rejection, authentication, partial results and reconciliation integration.

## Future work

- Future UniFi client/DHCP/device evidence can feed the same normalized observation
  layer without changing inventory matching rules. UniFi is not assumed authoritative.
- Persisted scan history/freshness tracking.
- Reviewable inventory additions/map placement from network results.
- Optional HTTP probing with verified TLS (never copy the upstream
  `verify=False` behaviour).
- Optional scheduling with explicit operator approval.
- Proxmox/UniFi integrations remain separate; they are not part of this slice.
