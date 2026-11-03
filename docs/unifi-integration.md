# UniFi network enrichment

Phase 5.2 adds optional, read-only UniFi Network evidence to the existing Nmap
discovery workflow. Nmap remains the current-observation source; UniFi is separate
client/device evidence and never makes an Nmap host or an inventory record appear or
disappear by itself.

## API and authentication

The adapter uses the official **UniFi Network Integration API** on the local
controller/gateway:

- Base path: `/proxy/network/integration`
- Authentication header: `X-API-KEY: <key>`
- Read-only endpoints used:
  - `GET /v1/info`
  - `GET /v1/sites`
  - `GET /v1/sites/{siteId}/devices`
  - `GET /v1/sites/{siteId}/clients`
- Pagination: `offset` / `limit` (200 per request), bounded by
  `HLH_UNIFI_MAX_PAGES` and `HLH_UNIFI_MAX_OBSERVATIONS`.
- Site selection: the first site by default, or the ID/name/internal reference in
  `HLH_UNIFI_SITE`.

No login/password or classic controller endpoints are used. The adapter only
implements GET; it cannot restart, adopt, provision, block, kick or remove anything.

### API key

Create a dedicated local API key in the UniFi Network application under
**Settings / Control Plane / Integrations** (wording varies by version). API keys
inherit the creating admin's permissions; use a **View Only** local administrator
where possible. Do not use the owner/super-admin account.

The key is sent only from the Flask backend to the configured controller. It is
never returned to the browser, logged, included in error bodies or committed to Git.

### TLS

Controller URLs must be HTTPS. TLS verification is always enabled. For a private or
self-signed controller certificate, point `HLH_UNIFI_CA_FILE` at the trusted CA
certificate. Do **not** disable verification or copy the old upstream scanner's
`verify=False` behaviour.

### SHA-256 certificate pinning

Some controller certificates (for example the UCG Max certificate valid for
`unifi.local`) are self-signed leaves without the Basic Constraints CA extension,
so Python rejects them as a CA file. In that case configure an explicit certificate
pin instead:

```sh
HLH_UNIFI_CERT_PIN_SHA256=AA:BB:...:FF
```

- The pin is the SHA-256 fingerprint of the server's leaf certificate, 64 hex
  characters; colons, spaces, dashes and upper/lower case are tolerated.
- With a pin configured, the adapter establishes TLS only to obtain the peer
  certificate, verifies the SHA-256 fingerprint **before sending the HTTP request
  or `X-API-KEY` header**, and then uses that same connection.
- A mismatched pin, missing certificate or TLS handshake failure is rejected. There
  is no fallback to an unpinned connection.
- Pin mode intentionally does not require the controller hostname/SAN to match, so
  `https://unifi.local` and a Docker hostname mapping resolve to the same trusted
  controller certificate. The URL still must resolve and use HTTPS.
- Without a pin, normal CA verification (including hostname checks) is preserved.
- Do not log the certificate, fingerprint or API key. Pin rotation is required when
  the controller certificate is renewed.

Obtaining the fingerprint without printing credentials or private key material:

```sh
openssl s_client -connect unifi.local:443 -servername unifi.local </dev/null 2>/dev/null \
  | openssl x509 -noout -fingerprint -sha256
```

The output is `SHA256 Fingerprint=AA:BB:...`; copy that value into the private env
file. This is a public certificate fingerprint, not an API key. Never paste a
private key or controller credential into chat.


## Configuration

Add these to the existing private web environment, following the same `600`-mode
convention as `phase3.env`:

```sh
HLH_UNIFI_URL=https://192.168.1.1
HLH_UNIFI_API_KEY=<view-only API key>
HLH_UNIFI_SITE=<optional site id/name/internal reference>
HLH_UNIFI_CA_FILE=/path/to/private-controller-ca.pem
HLH_UNIFI_CERT_PIN_SHA256=<optional 64-hex certificate SHA-256 fingerprint>
HLH_UNIFI_TIMEOUT=10
HLH_UNIFI_MAX_PAGES=20
HLH_UNIFI_MAX_OBSERVATIONS=5000
HLH_UNIFI_STALE_SECONDS=3600
```

Leave all `HLH_UNIFI_*` variables unset to keep Nmap-only operation. The web app
never contacts the controller on page load: it reads the last in-memory cache.
Refreshing is an explicit admin action.

The controller URL is trusted server configuration only. It cannot be supplied by a
scan request or browser, which prevents user-controlled SSRF through this adapter.

For the Betty test container, place a private CA certificate in the already-mounted
data volume (for example `/data/unifi-ca.pem`) and set
`HLH_UNIFI_CA_FILE=/data/unifi-ca.pem`; no extra mount or TLS bypass is required.
Keep the CA certificate readable only as needed by the container runtime.

## Cache and refresh

The adapter stores a bounded, normalized observation list in a process-local cache
(one Gunicorn worker by project convention). It is separate from inventory and is
lost on restart.

- `GET /api/network-discovery/unifi/status` — configured/stale state, last success
  and counts; no secrets or raw client records.
- `POST /api/network-discovery/unifi/refresh` — admin-token required. Fetches the
  official API once and replaces the cache on complete success.
- A failed refresh keeps the previous cache, records a short error and updates the
  last-attempt time.
- `POST /api/network-discovery/reconcile` — admin-token required; combines the
  supplied Nmap status with the cached UniFi observations. It never starts a scan.

## Normalized observations

Every UniFi record is reduced to an explicit subset:

- Source (`unifi`), observation time, kind (`device` or `client`), stable ID.
- Name/friendly name and hostname where present.
- MAC address (normalized) and current/optional additional IP addresses.
- Network/VLAN when supplied by the controller version.
- Online/offline/unknown state and last-seen/connected timestamps when available.
- Device type (gateway, switch, access point, network device; wired, wireless,
  VPN, Teleport client).
- Uplink device ID, model and manufacturer when available.
- Site ID/name.

Official Network 9.x supplies adopted infrastructure devices with state and
connected clients. It does **not** expose full offline/historical client history or
client VLAN membership in the list response; optional fields from newer controller
versions are parsed when present. The UI reports those limitations rather than
inventing data.

## Matching rules

UniFi is added to the Phase 5.1 inventory matcher as **evidence**, not as a replacement
for Nmap or inventory:

1. Exact MAC address.
2. Current IP addresses.
3. Hostnames/friendly names.
4. Existing hardware/VM parent relationships.
5. Network/VLAN context and online/current versus offline/historical state.
6. Source conflicts.

Rules:

- A current UniFi MAC can supply identity evidence when Nmap has no MAC.
- An offline/historical UniFi record can enrich detail but never overrides a current
  Nmap match or claims a current host.
- If Nmap IP evidence and current UniFi MAC evidence identify different inventory
  devices, the host becomes **ambiguous** with a source-conflict reason.
- Multiple devices or a virtual/shared address remain ambiguous; they are not merged.
- A UniFi-only client/device is listed separately and is never counted as an Nmap
  discovery. Missing from Nmap is not offline; missing from UniFi is not missing.
- Multiple applications inheriting one host IP remain associated services, not
  additional physical-device candidates.
- No MAC/IP/hostname automatically merges or edits inventory records.

## UI

The Network Discovery page now shows:

- UniFi configured/cache status, last successful refresh, device/client/current/
  historical counts and stale/error state.
- An explicit refresh button (admin token; does not start Nmap).
- Source, match, UniFi state, network/VLAN and device-type filters plus global search.
- Separate host-level device/runtime identities and associated application/service
  lists with their own counts and a per-host application search box.
- Expandable UniFi evidence including name, MAC/IP, current/historical state,
  network/VLAN and last-seen time.
- A separate UniFi-only known-device table with inventory candidates and clear
  warnings that these were not observed by the current Nmap scan.

All existing inventory links, dark/light theme conventions and read-only warnings
remain in place.

## Tests

```sh
python -m pytest -q backend/tests/test_unifi.py
python -m pytest -q backend/tests/test_network_wide_reconciliation.py
python -m pytest -q backend/tests/test_network_discovery.py
cd frontend && npm test
```

UniFi tests inject a mocked opener and never require live credentials. Cover:
authentication rejection, timeout/unavailable, malformed JSON, pagination,
multiple IPs, optional network/offline fields, cache preservation on failure,
Nmap/UniFi conflicts, certificate-pin normalization/verification and no inventory
mutation.

## Supervised Betty test steps

1. Obtain a View Only API key from the UniFi controller. Do not print it or paste it
   into chat.
2. On Betty, add the `HLH_UNIFI_*` variables to the private test web environment
   (mode `600`). Do not modify `phase3.env` values that already exist and do not
   touch the production port-8000 installation.
3. Redeploy/restart only the test web instance after explicit approval. No database
   migration is required and the scanner is unchanged.
4. Open `http://192.168.1.80:8790/#/network-discovery`, save the HomeLab-Hub admin
   token, and confirm the UniFi status card says configured with no error.
5. Click **Refresh UniFi observations**. Confirm counts and last-success time. This
   does not start an Nmap scan.
6. Run the normal approved single-host Nmap scan, then inspect host hierarchy,
   UniFi evidence, source conflicts and UniFi-only devices. No inventory is changed.
7. If TLS verification fails, either install the controller CA via
   `HLH_UNIFI_CA_FILE` or use the explicitly reviewed certificate fingerprint in
   `HLH_UNIFI_CERT_PIN_SHA256`; do not disable verification.

Live controller validation is still outstanding until these steps are executed with
operator approval. No controller credentials are present in this repository.

## Limitations / future work

- No UniFi write actions, device restart, adoption, provisioning or client actions.
- Official 9.x may not expose offline client history, VLAN assignment or rich
  last-seen data; optional fields are tolerated but not fabricated.
- MAC randomization and multiple interfaces can make identity evidence weaker.
- UniFi-only devices are not inventory records and do not update maps.
- Cache is process-local and not persisted; no scheduled refresh.
- No automatic merge or deletion based on MAC/IP/hostname.
- UniFi Site Manager cloud API and write-capable API keys are out of scope.
