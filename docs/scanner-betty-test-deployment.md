# Supervised scanner test deployment on Betty

This document prepares the Phase 5 scanner for the **redesign test instance only**.
Nothing here has been executed against Betty. The original HomeLab-Hub installation
on host port **8000** must remain untouched.

## Topology

```text
host 192.168.1.80:8790 ──► homelab-hub-redesign (web test)
                                  │ Docker DNS
                                  ▼
                         homelab-hub-nmap-test-net
                         (dedicated private bridge)
                                  │
                                  ▼
                         homelab-hub-nmap-test
                         (scanner API :8791, no host publish)
                                  │ outbound NAT
                                  ▼
                         approved private LAN targets
```

- The scanner has **no published host port** and is reachable only by containers on
  `homelab-hub-nmap-test-net`.
- The web container joins that network and receives
  `HLH_SCANNER_URL=http://homelab-hub-nmap-test:8791`.
- The existing `homelab-hub-scanner` container is not touched, renamed or replaced.
- The scanner gets only `NET_RAW` (dropping all other capabilities), no
  `--privileged`, no host networking and no Docker socket.
- The scanner container is read-only with a `/tmp` tmpfs and
  `no-new-privileges`. Initial discovery uses IP/ICMP/TCP and unprivileged TCP
  connect scans. **MAC/vendor information may be unavailable over a bridge**, because
  the scanner does not share the LAN L2 segment. That is the deliberate minimum-
  privilege trade-off for the first test; do not add host networking or
  `NET_ADMIN` without a new review.

## Prerequisites

- Run on Betty from the test source checkout:
  `/mnt/cache/appdata/homelab-hub-redesign-source`.
- The existing private web env remains:
  `/mnt/cache/appdata/homelab-hub-redesign-config/phase3.env` (mode `600`).
- The scanner gets a separate private env file:
  `/mnt/cache/appdata/homelab-hub-redesign-config/scanner-test.env` (mode `600`).
- `docker`, `git`, `openssl` and the usual deployment prerequisites are available.
- An explicitly approved private scanner range has been verified. **Do not derive
  subnets from VLAN numbers.** For example, VLAN 10 being "Guest" does not mean
  `192.168.10.0/24`; verify the actual subnet.

## 1. Create the shared scanner env without printing the token

Run on Betty. This writes a fresh token directly to a mode-600 file; the token is not
echoed to the terminal:

```sh
cd /mnt/cache/appdata/homelab-hub-redesign-source

umask 077
CONFIG_DIR=/mnt/cache/appdata/homelab-hub-redesign-config
APPROVED_RANGE='<verified-private-subnet>'
TMP_ENV="$(mktemp "$CONFIG_DIR/.scanner-test.env.XXXXXX")"
{
  printf 'HLH_SCANNER_TOKEN='
  openssl rand -hex 32
  printf '\n'
  printf 'HLH_SCANNER_APPROVED_RANGES=%s\n' "$APPROVED_RANGE"
} > "$TMP_ENV"
chmod 600 "$TMP_ENV"
mv "$TMP_ENV" "$CONFIG_DIR/scanner-test.env"
```

Replace the `<verified-private-subnet>` placeholder with the **verified approved
subnet** before running the command. Add optional scanner settings here if needed:

```sh
HLH_SCANNER_MAX_SCAN_SECONDS=300
HLH_SCANNER_MAX_CONCURRENCY=1
HLH_SCANNER_MAX_HOSTS=1024
HLH_SCANNER_MAX_PORTS=256
HLH_SCANNER_RETENTION_SECONDS=3600
```

The web deploy script passes this same file to the web container, so the shared
token is never copied into `phase3.env`, source code or a command line. Do not print
the file, quote the token in chat, or commit it. Verify permissions only:

```sh
stat -c '%a %n' /mnt/cache/appdata/homelab-hub-redesign-config/scanner-test.env
# expected: 600 /mnt/cache/appdata/.../scanner-test.env
```

## 2. Deploy the scanner first

The scanner deployment script is idempotent: it ensures the dedicated bridge exists,
fast-forwards the test checkout, builds a revision-tagged scanner image, replaces
**only** `homelab-hub-nmap-test`, verifies health and confirms that no host port is
published.

```sh
cd /mnt/cache/appdata/homelab-hub-redesign-source
bash scripts/deploy-betty-test-scanner.sh
```

If it fails, inspect the test container/logs before retrying. Do not alter the
existing scanner or the port-8000 installation to work around a failure.

Verify the result:

```sh
docker ps --filter name=homelab-hub-nmap-test \
  --format '{{.Names}} {{.Status}} {{.Image}}'

docker exec homelab-hub-nmap-test python -c \
  'import json,urllib.request; print(json.load(urllib.request.urlopen("http://127.0.0.1:8791/health", timeout=3)))'

test -z "$(docker port homelab-hub-nmap-test)" && echo 'no published host port'
docker inspect -f '{{json .NetworkSettings.Networks}}' homelab-hub-nmap-test
```

Health does not require the token. Scanner start/status APIs do. No scan is started
by deployment or container startup.

## 3. Deploy the web test instance

Only after the scanner is healthy:

```sh
cd /mnt/cache/appdata/homelab-hub-redesign-source
bash scripts/deploy-betty-test.sh
```

The updated web deployment preserves the existing SQLite online backup, rollback
container, FolderView mount, admin token, host port 8790 and environment settings.
It additionally:

- ensures the dedicated bridge exists;
- attaches the new web container to `homelab-hub-nmap-test-net`;
- passes `HLH_SCANNER_URL=http://homelab-hub-nmap-test:8791`;
- passes `scanner-test.env` when present, so token and approved ranges are shared;
- checks scanner health before replacing the web container;
- checks scanner health from inside the new web container after startup.

If `scanner-test.env` is absent, the web deployment retains its previous behaviour
and network discovery stays disabled; it does not require a scanner. For this
supervised test, deploy the scanner first.

Verify connectivity from the web container:

```sh
docker exec homelab-hub-redesign python -c \
  'import json,urllib.request; print(json.load(urllib.request.urlopen("http://homelab-hub-nmap-test:8791/health", timeout=4)))'
```

Open `http://192.168.1.80:8790/#/network-discovery`.

## 4. First scan sequence

1. Save the existing HomeLab-Hub admin token in the Network discovery page.
2. Confirm the approved range comes from `scanner-test.env`. Do **not** type a subnet
   that was guessed from a VLAN number.
3. Enter **one explicitly approved host** from that range in "Specific host or CIDR"
   for the first test; do not type a full subnet or a VLAN-derived guess.
4. Choose **Host discovery** first. Do not start with a full-range service scan.
5. Start the scan; confirm status and UTC start/completion timestamps.
6. Review discovered host rows and the read-only inventory comparison. A matched
   result does not prove a Docker identity or current availability.
7. Optionally repeat with "Hosts and TCP services" for the same single host and a
   small port list.
8. Confirm no inventory records or map layouts changed. Any future inventory/map
   action must be separately reviewed.

A `partial` or `failed` scan is not proof of absence. Do not rescan automatically or
interpret missing devices as deletions.

## Rollback / cleanup

- Web: the deployment script already retains the previous stopped web container.
  Follow the existing rollback rules; do not restart an old image against an
  incompatible database. This phase adds no schema migration.
- Scanner: stop/remove only the test scanner when approved:
  ```sh
  docker stop homelab-hub-nmap-test
  docker rm homelab-hub-nmap-test
  ```
  Do **not** stop or remove `homelab-hub-scanner` or the original port-8000 instance.
- The dedicated bridge can remain for later tests. Remove it only after no test
  container is attached:
  ```sh
  docker network rm homelab-hub-nmap-test-net
  ```
- To rotate the token: stop the test web container, regenerate
  `scanner-test.env` with the command above, rerun the scanner script, then redeploy
  the web test instance.

## Safety rules

- Never publish port `8791` to the host or LAN.
- Never mount `/var/run/docker.sock` into the web container or scanner.
- Never use `--privileged`; only `NET_RAW` is added and all other capabilities are
  dropped for the initial scanner.
- Never automatically scan all VLANs, add VLAN-derived ranges, or start scans from
  deployment scripts.
- Confirm the test container names before removing anything; the existing scanner is
  `homelab-hub-scanner` and must remain untouched.
