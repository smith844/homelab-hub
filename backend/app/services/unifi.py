"""Read-only UniFi Network Integration API adapter and observation cache.

Uses the official local Network Integration API surface:
    GET /proxy/network/integration/v1/...
    X-API-KEY: <key>

Only GET requests are implemented. Controller credentials never leave the server,
never appear in responses or logs, and TLS verification is never disabled. A
private controller certificate may be trusted with HLH_UNIFI_CA_FILE.

The official Network 9.x surface supplies adopted infrastructure devices and
connected clients. Optional fields (last-seen, network/VLAN, vendor) are parsed
when a newer controller exposes them; none are invented.
"""
from __future__ import annotations

import copy
import functools
import hashlib
import hmac
import http.client
import ipaddress
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from flask import current_app

API_PREFIX = "/proxy/network/integration"
PAGE_LIMIT = 200
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_TEXT = 300


class UnifiError(ValueError):
    """Base UniFi integration error."""


class UnifiUnavailable(RuntimeError):
    """The controller is unconfigured, unreachable or temporarily unavailable."""


class UnifiAuthError(UnifiUnavailable):
    """The controller rejected the configured API key."""


class UnifiResponseError(UnifiError):
    """The controller returned malformed or incomplete data."""


class UnifiCertificateError(UnifiUnavailable):
    """The presented TLS certificate does not match the configured SHA-256 pin."""


_PIN_RE = re.compile(r"[0-9a-f]{64}\Z")


def normalise_certificate_pin(value):
    """Return a canonical lowercase SHA-256 hex fingerprint, or None if unset."""
    text = _text(value, 200)
    if not text:
        return None
    text = text.replace(":", "").replace(" ", "").replace("-", "").lower()
    if not _PIN_RE.fullmatch(text):
        raise UnifiUnavailable(
            "HLH_UNIFI_CERT_PIN_SHA256 must be a 64-character hexadecimal SHA-256 fingerprint"
        )
    return text


def _verify_certificate_pin(sock, expected):
    """Verify the peer certificate before any HTTP request is written."""
    try:
        der = sock.getpeercert(binary_form=True)
    except (OSError, ValueError) as exc:
        raise UnifiCertificateError("UniFi server did not present a usable certificate") from exc
    if not der:
        raise UnifiCertificateError("UniFi server did not present a usable certificate")
    actual = hashlib.sha256(der).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise UnifiCertificateError("UniFi server certificate SHA-256 pin did not match")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that checks a certificate fingerprint before sending."""

    def __init__(self, *args, cert_pin=None, **kwargs):
        self._cert_pin = cert_pin
        super().__init__(*args, **kwargs)

    def connect(self):
        super().connect()
        _verify_certificate_pin(self.sock, self._cert_pin)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """Use an unverified CA context only as transport to obtain the pinned cert.

    The pin is checked inside the connection before the HTTP request (including
    the X-API-KEY header) is sent. There is deliberately no fallback path when a
    pin is configured.
    """

    def __init__(self, cert_pin):
        super().__init__(context=ssl._create_unverified_context())
        self._cert_pin = cert_pin

    def https_open(self, req):
        return self.do_open(
            functools.partial(_PinnedHTTPSConnection, cert_pin=self._cert_pin),
            req,
            context=self._context,
        )


def _config(name, default=""):
    value = current_app.config.get(name, default)
    return value if value is not None else default


def _int_config(name, default, minimum, maximum):
    try:
        value = int(_config(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _text(value, limit=MAX_TEXT):
    if value is None:
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value)).strip()[:limit]


def _ip(value):
    text = _text(value, 64)
    if not text:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _mac(value):
    text = _text(value, 64).replace("-", ":").replace(".", ":").upper()
    if re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}", text):
        return text.casefold()
    return None


def _optional_timestamp(row, keys):
    for key in keys:
        if key in row and row.get(key):
            return _text(row.get(key), 64)
    return None


def _network(row):
    value = row.get("network") or row.get("networkName") or row.get("network_name")
    if isinstance(value, dict):
        name = _text(value.get("name") or value.get("networkName"), 120)
        vlan = value.get("vlan") if value.get("vlan") is not None else value.get("vlanId")
        try:
            vlan = int(vlan) if vlan is not None else None
        except (TypeError, ValueError):
            vlan = None
        return {"name": name or None, "vlan_id": vlan} if name or vlan is not None else None
    name = _text(value, 120)
    vlan = row.get("vlan")
    try:
        vlan = int(vlan) if vlan is not None else None
    except (TypeError, ValueError):
        vlan = None
    return {"name": name or None, "vlan_id": vlan} if name or vlan is not None else None


def _uplink_id(value):
    if isinstance(value, dict):
        value = value.get("deviceId") or value.get("id") or value.get("name")
    return _text(value, 64) or None



def configured():
    return bool(_text(_config("UNIFI_URL"), 500) and _text(_config("UNIFI_API_KEY"), 500))


class UnifiClient:
    """Minimal read-only official UniFi Network Integration client."""

    def __init__(self, url=None, api_key=None, site=None, ca_file=None, timeout=10,
                 max_pages=20, max_observations=5000, cert_pin=None, opener=None):
        self.url = (url if url is not None else _config("UNIFI_URL")).rstrip("/")
        self.api_key = api_key if api_key is not None else _text(_config("UNIFI_API_KEY"), 500)
        self.site_selector = _text(site if site is not None else _config("UNIFI_SITE"), 200)
        self.ca_file = ca_file if ca_file is not None else _config("UNIFI_CA_FILE", None)
        self.timeout = timeout
        self.max_pages = max_pages
        self.max_observations = max_observations
        configured_pin = cert_pin if cert_pin is not None else _config("UNIFI_CERT_PIN_SHA256", "")
        self.cert_pin = normalise_certificate_pin(configured_pin)
        self.opener = opener
        self._base = self._normalise_base(self.url)
        self._context = None

    @staticmethod
    def _normalise_base(url):
        raw = _text(url, 500).rstrip("/")
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme != "https" or not parsed.netloc:
            raise UnifiUnavailable("UniFi controller URL must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise UnifiUnavailable("UniFi controller URL must not contain credentials, query or fragment")
        base = raw
        if base.endswith("/proxy/network/integration/v1"):
            base = base[:-3]
        if not base.endswith(API_PREFIX):
            base += API_PREFIX
        return base

    def _context_obj(self):
        if self._context is None:
            try:
                self._context = ssl.create_default_context(cafile=self.ca_file) if self.ca_file \
                    else ssl.create_default_context()
            except (OSError, ssl.SSLError) as exc:
                raise UnifiUnavailable("The configured UniFi CA file could not be loaded") from exc
        return self._context

    def _open(self, request):
        if self.opener is not None:
            # Injected opener used by tests; production paths below never bypass
            # the configured trust mode.
            return self.opener(request, timeout=self.timeout, context=self._context_obj())
        if self.cert_pin:
            opener = urllib.request.build_opener(_PinnedHTTPSHandler(self.cert_pin))
            return opener.open(request, timeout=self.timeout)
        return urllib.request.urlopen(
            request, timeout=self.timeout, context=self._context_obj()
        )

    def _get(self, path, params=None):
        # Only GET is implemented on purpose: this adapter must never mutate UniFi.
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        request = urllib.request.Request(
            self._base + path + query,
            headers={"X-API-KEY": self.api_key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._open(request) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            message = ""
            try:
                payload = json.loads(exc.read(32 * 1024).decode("utf-8"))
                if isinstance(payload, dict):
                    message = _text(payload.get("message") or payload.get("statusName"), 200)
            except (ValueError, UnicodeDecodeError, OSError):
                pass
            if exc.code in (401, 403):
                raise UnifiAuthError("UniFi rejected the configured API key") from exc
            if exc.code == 429:
                raise UnifiUnavailable("UniFi is rate-limiting requests; try again later") from exc
            if exc.code == 404:
                raise UnifiResponseError(
                    "UniFi Network Integration API was not found; check the controller version and URL"
                ) from exc
            raise UnifiUnavailable(
                f"UniFi returned HTTP {exc.code}" + (f": {message}" if message else "")
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UnifiUnavailable("UniFi controller is unreachable or TLS verification failed") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise UnifiResponseError("UniFi response exceeded the size limit")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise UnifiResponseError("UniFi returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise UnifiResponseError("UniFi returned an invalid response")
        return payload

    def info(self):
        data = self._get("/v1/info")
        version = _text(data.get("applicationVersion"), 64)
        return {"application_version": version or None}

    def sites(self):
        rows, meta = self._paged("/v1/sites")
        sites = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            site_id = _text(row.get("id"), 64)
            if not site_id:
                continue
            sites.append({
                "id": site_id,
                "internal_reference": _text(row.get("internalReference"), 120),
                "name": _text(row.get("name"), 160) or site_id,
            })
        if not sites:
            raise UnifiResponseError("UniFi returned no sites")
        return {"sites": sites, "pagination": meta}

    def select_site(self, sites):
        if not self.site_selector:
            return sites[0]
        wanted = self.site_selector.casefold()
        for site in sites:
            if wanted in {site["id"].casefold(), site["name"].casefold(),
                          site["internal_reference"].casefold()}:
                return site
        raise UnifiResponseError("Configured UniFi site was not found")

    def devices(self, site_id):
        rows, meta = self._paged(f"/v1/sites/{urllib.parse.quote(site_id)}/devices")
        return rows, meta

    def clients(self, site_id):
        rows, meta = self._paged(f"/v1/sites/{urllib.parse.quote(site_id)}/clients")
        return rows, meta

    def _paged(self, path):
        rows = []
        offset = 0
        pages = 0
        total = None
        while True:
            if pages >= self.max_pages:
                raise UnifiResponseError("UniFi pagination exceeded the configured page limit")
            page = self._get(path, {"offset": offset, "limit": PAGE_LIMIT})
            data = page.get("data")
            if not isinstance(data, list):
                raise UnifiResponseError("UniFi page did not contain a data array")
            rows.extend(data)
            pages += 1
            if len(rows) > self.max_observations:
                raise UnifiResponseError("UniFi response exceeded the observation limit")
            try:
                total = int(page.get("totalCount")) if page.get("totalCount") is not None else total
            except (TypeError, ValueError) as exc:
                raise UnifiResponseError("UniFi returned an invalid total count") from exc
            if not data:
                if total is not None and offset < total:
                    raise UnifiResponseError("UniFi pagination ended before the reported total count")
                break
            if total is not None and offset + len(data) >= total:
                break
            if len(data) < PAGE_LIMIT:
                if total is not None and offset + len(data) < total:
                    raise UnifiResponseError("UniFi pagination returned an incomplete page")
                break
            offset += len(data)
        return rows, {"pages": pages, "total": total, "truncated": False}


def _normalise_device(raw, site, observed_at):
    if not isinstance(raw, dict):
        return None, "Skipped a malformed UniFi device"
    device_id = _text(raw.get("id"), 64)
    name = _text(raw.get("name"), 160)
    if not device_id and not name:
        return None, "Skipped a UniFi device without an identifier"
    ips = []
    for value in [raw.get("ipAddress")] + (raw.get("ipAddresses")[:16] if isinstance(raw.get("ipAddresses"), list) else []):
        parsed = _ip(value)
        if parsed and parsed not in ips:
            ips.append(parsed)
    features = raw.get("features") if isinstance(raw.get("features"), list) else []
    features = {_text(item, 40).casefold() for item in features}
    if "gateway" in features:
        device_type = "gateway"
    elif "switching" in features:
        device_type = "switch"
    elif "accesspoint" in features:
        device_type = "access_point"
    else:
        device_type = "network_device"
    state = _text(raw.get("state"), 32).upper()
    online = True if state == "ONLINE" else False if state == "OFFLINE" else None
    return {
        "source": "unifi",
        "observed_at": observed_at,
        "kind": "device",
        "id": device_id or _mac(raw.get("macAddress")) or name,
        "name": name,
        "hostname": _text(raw.get("hostname"), 200),
        "mac": _mac(raw.get("macAddress")),
        "ip": ips[0] if ips else None,
        "ips": ips,
        "model": _text(raw.get("model"), 120),
        "vendor": _text(raw.get("manufacturer") or raw.get("vendor"), 120),
        "device_type": device_type,
        "state": state or None,
        "online": online,
        "last_seen": _optional_timestamp(raw, ("lastSeen", "lastSeenAt", "last_seen")),
        "adopted_at": _optional_timestamp(raw, ("adoptedAt", "adopted_at")),
        "uplink_device_id": _uplink_id(raw.get("uplinkDeviceId") or raw.get("uplink")),
        "network": _network(raw),
        "site": {"id": site["id"], "name": site["name"]},
    }, None


def _normalise_client(raw, site, observed_at):
    if not isinstance(raw, dict):
        return None, "Skipped a malformed UniFi client"
    client_type = _text(raw.get("type"), 32).upper()
    mac = _mac(raw.get("macAddress"))
    name = _text(raw.get("name") or raw.get("hostname"), 160)
    ips = []
    for value in [raw.get("ipAddress")] + (raw.get("ipAddresses")[:16] if isinstance(raw.get("ipAddresses"), list) else []):
        parsed = _ip(value)
        if parsed and parsed not in ips:
            ips.append(parsed)
    if not name and not mac and not ips:
        return None, "Skipped a UniFi client without identity fields"
    online_value = raw.get("online") if "online" in raw else raw.get("isOnline")
    if isinstance(online_value, bool):
        online = online_value
    elif isinstance(online_value, str) and online_value.strip().lower() in ("true", "false"):
        online = online_value.strip().lower() == "true"
    elif _text(raw.get("state"), 32).upper() == "OFFLINE":
        online = False
    else:
        # The official /clients endpoint lists connected clients.
        online = True
    return {
        "source": "unifi",
        "observed_at": observed_at,
        "kind": "client",
        "id": _text(raw.get("id"), 64) or mac or name,
        "name": name,
        "hostname": _text(raw.get("hostname"), 200),
        "mac": mac,
        "ip": ips[0] if ips else None,
        "ips": ips,
        "model": "",
        "vendor": _text(raw.get("manufacturer") or raw.get("vendor") or raw.get("oui"), 120),
        "device_type": {"WIRED": "wired", "WIRELESS": "wireless", "VPN": "vpn",
                        "TELEPORT": "teleport"}.get(client_type, "client"),
        "state": _text(raw.get("state"), 32) or ("ONLINE" if online else "OFFLINE"),
        "online": online,
        "connected_at": _optional_timestamp(raw, ("connectedAt", "connected_at")),
        "last_seen": _optional_timestamp(raw, ("lastSeen", "lastSeenAt", "last_seen",
                                                "lastConnectionChange")) or _optional_timestamp(
                                                    raw, ("connectedAt", "connected_at")),
        "uplink_device_id": _uplink_id(raw.get("uplinkDeviceId") or raw.get("uplink")),
        "network": _network(raw),
        "site": {"id": site["id"], "name": site["name"]},
    }, None


def fetch_observations(opener=None):
    """Fetch and normalize current UniFi observations; never mutates the controller."""
    if not configured():
        raise UnifiUnavailable("UniFi integration is not configured")
    client = UnifiClient(
        timeout=_int_config("UNIFI_TIMEOUT", 10, 2, 60),
        max_pages=_int_config("UNIFI_MAX_PAGES", 20, 1, 200),
        max_observations=_int_config("UNIFI_MAX_OBSERVATIONS", 5000, 1, 50000),
        opener=opener,
    )
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    info = client.info()
    sites_payload = client.sites()
    site = client.select_site(sites_payload["sites"])
    devices_raw, device_pages = client.devices(site["id"])
    clients_raw, client_pages = client.clients(site["id"])
    observations = []
    warnings = []
    for raw in devices_raw:
        row, warning = _normalise_device(raw, site, observed_at)
        if warning:
            warnings.append(warning)
        elif row:
            observations.append(row)
    for raw in clients_raw:
        row, warning = _normalise_client(raw, site, observed_at)
        if warning:
            warnings.append(warning)
        elif row:
            observations.append(row)
    if len(observations) > _int_config("UNIFI_MAX_OBSERVATIONS", 5000, 1, 50000):
        raise UnifiResponseError("UniFi observations exceeded the configured limit")
    return {
        "observations": observations,
        "version": info["application_version"],
        "site": site,
        "pagination": {"devices": device_pages, "clients": client_pages},
        "warnings": warnings,
        "observed_at": observed_at,
    }


class UnifiStore:
    """Bounded, process-local cache. Never writes canonical inventory."""

    def __init__(self):
        self._lock = threading.Lock()
        self._observations = []
        self._last_success = None
        self._last_attempt = None
        self._error = None
        self._version = None
        self._site = None
        self._warnings = []

    def status(self):
        with self._lock:
            stale_seconds = _int_config("UNIFI_STALE_SECONDS", 3600, 60, 86400)
            stale = True
            if self._last_success:
                try:
                    age = time.time() - datetime.fromisoformat(
                        self._last_success.replace("Z", "+00:00")).timestamp()
                    stale = age > stale_seconds
                except ValueError:
                    stale = True
            devices = [row for row in self._observations if row["kind"] == "device"]
            clients = [row for row in self._observations if row["kind"] == "client"]
            return {
                "configured": configured(),
                "has_data": bool(self._last_success),
                "last_success": self._last_success,
                "last_attempt": self._last_attempt,
                "stale": stale,
                "error": self._error,
                "version": self._version,
                "site": copy.deepcopy(self._site),
                "warnings": list(self._warnings),
                "infrastructure_devices": len(devices),
                "clients": len(clients),
                "online_devices": sum(row.get("online") is True for row in devices),
                "offline_devices": sum(row.get("online") is False for row in devices),
                "current_clients": sum(row.get("online") is True for row in clients),
                "historical_clients": sum(row.get("online") is False for row in clients),
            }

    def observations(self):
        with self._lock:
            return copy.deepcopy(self._observations)

    def refresh(self):
        with self._lock:
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            self._last_attempt = now
            try:
                fetched = fetch_observations()
            except UnifiUnavailable as exc:
                self._error = str(exc)
                raise
            except UnifiError as exc:
                self._error = str(exc)
                raise
            self._observations = fetched["observations"]
            self._last_success = fetched["observed_at"]
            self._error = None
            self._version = fetched["version"]
            self._site = fetched["site"]
            self._warnings = fetched["warnings"]
            self._last_attempt = now
        return self.status()


unifi_store = UnifiStore()
