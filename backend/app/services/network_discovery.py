"""Server-side bridge to the separate, token-authenticated Nmap scanner.

The web application never runs nmap, receives no privileged network access and
never writes scanner results into inventory. It validates targets against its
own approved ranges and forwards requests over a small HTTP interface.
"""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from flask import current_app

MAX_HOSTS = 1024
MAX_PORTS = 256
DEFAULT_PORTS = "22,80,443,445,3389,8080,8443"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000
PORT_TEXT_RE = re.compile(r"[0-9,\- ]+\Z")
SCAN_STATUSES = ("running", "completed", "partial", "failed")


class NetworkDiscoveryError(ValueError):
    """Invalid discovery request or scanner response."""


class NetworkDiscoveryNotFound(NetworkDiscoveryError):
    """The scanner no longer retains the requested scan job."""


class NetworkDiscoveryUnavailable(RuntimeError):
    """The scanner service is missing, unreachable or misconfigured."""


class NetworkDiscoveryBusy(RuntimeError):
    """The scanner is running its maximum number of jobs."""


def _config(name, default=""):
    value = current_app.config.get(name, default)
    return value if value is not None else default


def _max_hosts():
    try:
        value = int(_config("SCANNER_MAX_HOSTS", MAX_HOSTS))
    except (TypeError, ValueError):
        return MAX_HOSTS
    return value if value > 0 else MAX_HOSTS


def _max_ports():
    try:
        value = int(_config("SCANNER_MAX_PORTS", MAX_PORTS))
    except (TypeError, ValueError):
        return MAX_PORTS
    return value if value > 0 else MAX_PORTS


def _is_allowed_range(network):
    return not any((
        network.version != 4,
        not network.is_private,
        network.is_loopback,
        network.is_link_local,
        network.is_multicast,
        network.is_reserved,
        network.is_unspecified,
    ))


def approved_ranges():
    """Parse the web app's approved ranges without deriving them from VLANs."""
    raw = str(_config("SCANNER_APPROVED_RANGES", "") or "")
    networks = []
    for item in re.split(r"[,\n]+", raw):
        text = item.strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as exc:
            raise NetworkDiscoveryError(f"Invalid approved network: {text}") from exc
        if network.version != 4 or not _is_allowed_range(network):
            raise NetworkDiscoveryError(f"Approved networks must be private IPv4 ranges: {text}")
        if network not in networks:
            networks.append(network)
    return networks


def scanner_configured():
    return bool(str(_config("SCANNER_URL", "")).strip() and str(_config("SCANNER_TOKEN", "")).strip())


def validate_scan_request(target, scan_type, ports=None):
    """Validate a request in the web process before contacting the scanner."""
    if scan_type not in ("discover", "services"):
        raise NetworkDiscoveryError("Scan type must be discover or services")
    text = str(target or "").strip()
    if not text:
        raise NetworkDiscoveryError("A scan target is required")
    if len(text) > 64:
        raise NetworkDiscoveryError("Scan target is too long")
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError as exc:
        raise NetworkDiscoveryError(f"Invalid IPv4 target: {text}") from exc
    if network.version != 4:
        raise NetworkDiscoveryError("Only IPv4 scan targets are supported")
    ranges = approved_ranges()
    if not ranges:
        raise NetworkDiscoveryError("No approved scan ranges are configured")
    if not any(network.subnet_of(item) for item in ranges):
        raise NetworkDiscoveryError("Scan target is outside the approved private ranges")
    if network.num_addresses > _max_hosts():
        raise NetworkDiscoveryError(
            f"Scan target contains {network.num_addresses} addresses; the limit is {_max_hosts()}"
        )
    canonical_target = str(network) if "/" in text else str(network.network_address)
    canonical_ports = None
    if scan_type == "services":
        canonical_ports = _validate_ports(ports)
    return canonical_target, canonical_ports


def _validate_ports(value):
    text = str(value or "").strip()
    if not text:
        raise NetworkDiscoveryError("A TCP port list is required for a service scan")
    if len(text) > 1024 or not PORT_TEXT_RE.fullmatch(text):
        raise NetworkDiscoveryError("Ports must be numbers, commas and ranges only")
    ports = set()
    for token in text.replace(" ", "").split(","):
        if not token:
            raise NetworkDiscoveryError("Port list contains an empty entry")
        if "-" in token:
            if token.count("-") != 1:
                raise NetworkDiscoveryError(f"Invalid port range: {token}")
            start_text, end_text = token.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise NetworkDiscoveryError(f"Invalid port range: {token}")
            start, end = int(start_text), int(end_text)
            if start > end:
                raise NetworkDiscoveryError(f"Port range starts after it ends: {token}")
            candidates = range(start, end + 1)
        else:
            if not token.isdigit():
                raise NetworkDiscoveryError(f"Invalid port: {token}")
            candidates = (int(token),)
        for port in candidates:
            if not 1 <= port <= 65535:
                raise NetworkDiscoveryError(f"Port outside 1-65535: {port}")
            ports.add(port)
            if len(ports) > _max_ports():
                raise NetworkDiscoveryError(f"Too many ports; the limit is {_max_ports()}")
    if not ports:
        raise NetworkDiscoveryError("A TCP port list is required for a service scan")
    return ",".join(str(port) for port in sorted(ports))


def _scanner_base():
    url = str(_config("SCANNER_URL", "")).strip().rstrip("/")
    token = str(_config("SCANNER_TOKEN", "")).strip()
    if not url or not token:
        raise NetworkDiscoveryUnavailable(
            "Network discovery is not configured; set HLH_SCANNER_URL and HLH_SCANNER_TOKEN"
        )
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise NetworkDiscoveryUnavailable("HLH_SCANNER_URL must be an http(s) URL")
    return url, token


def _request(method, path, payload=None):
    base, token = _scanner_base()
    data = None
    headers = {"X-Scanner-Token": token, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        message = ""
        try:
            body = json.loads(exc.read(64 * 1024).decode("utf-8"))
            if isinstance(body, dict):
                message = str(body.get("error") or "")[:300]
        except (ValueError, UnicodeDecodeError, OSError):
            pass
        if exc.code == 429:
            raise NetworkDiscoveryBusy(message or "The scanner is busy; retry shortly") from exc
        if exc.code in (401, 403):
            raise NetworkDiscoveryUnavailable(
                "The scanner rejected HomeLab-Hub's configured token"
            ) from exc
        if exc.code == 404 and method == "GET":
            raise NetworkDiscoveryNotFound(message or "Scan not found or expired") from exc
        if exc.code in (400, 404, 413):
            raise NetworkDiscoveryError(message or f"Scanner rejected the request (HTTP {exc.code})") from exc
        raise NetworkDiscoveryUnavailable(
            f"Scanner returned HTTP {exc.code}" + (f": {message}" if message else "")
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkDiscoveryUnavailable(
            "The scan service is unreachable; check HLH_SCANNER_URL and the scanner process"
        ) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise NetworkDiscoveryError("Scanner response exceeded the size limit")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise NetworkDiscoveryError("Scanner returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise NetworkDiscoveryError("Scanner returned an invalid response")
    return result


def _clean_text(value, limit=300):
    if value is None:
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value)).strip()[:limit]


def _clean_row(row):
    if not isinstance(row, dict):
        return None
    cleaned = {
        "ip": _clean_text(row.get("ip"), 64),
        "hostname": _clean_text(row.get("hostname"), 200),
        "mac": _clean_text(row.get("mac") or row.get("mac_address"), 32),
        "vendor": _clean_text(row.get("vendor"), 200),
        "os": _clean_text(row.get("os"), 200),
        "open_ports": row.get("open_ports") if isinstance(row.get("open_ports"), int) else 0,
    }
    if row.get("port") is not None:
        try:
            port = int(row["port"])
        except (TypeError, ValueError):
            return None
        if not 1 <= port <= 65535:
            return None
        cleaned.update({
            "port": port,
            "protocol": _clean_text(row.get("protocol"), 16) or "tcp",
            "state": _clean_text(row.get("state"), 16) or "open",
            "service_name": _clean_text(row.get("service_name"), 200),
            "service_version": _clean_text(row.get("service_version"), 300),
        })
    return cleaned


def _sanitize_scan(scan):
    if not isinstance(scan, dict):
        raise NetworkDiscoveryError("Scanner returned an invalid scan")
    try:
        scan_id = str(uuid.UUID(str(scan.get("scan_id"))))
    except (ValueError, TypeError, AttributeError) as exc:
        raise NetworkDiscoveryError("Scanner returned an invalid scan id") from exc
    status = scan.get("status")
    if status not in SCAN_STATUSES:
        raise NetworkDiscoveryError("Scanner returned an invalid scan status")
    scan_type = scan.get("type")
    if scan_type not in ("discover", "portscan"):
        raise NetworkDiscoveryError("Scanner returned an invalid scan type")
    results = scan.get("results", [])
    hosts = scan.get("hosts", [])
    if not isinstance(results, list) or not isinstance(hosts, list) \
            or len(results) > MAX_ROWS or len(hosts) > MAX_ROWS:
        raise NetworkDiscoveryError("Scanner returned too many results")
    clean_results = [row for row in (_clean_row(item) for item in results) if row is not None]
    clean_hosts = [row for row in (_clean_row(item) for item in hosts) if row is not None]
    params = scan.get("params") if isinstance(scan.get("params"), dict) else {}
    return {
        "scan_id": scan_id,
        "type": scan_type,
        "scan_type": _clean_text(scan.get("scan_type"), 32),
        "status": status,
        "progress": scan.get("progress") if isinstance(scan.get("progress"), int) else 0,
        "target": _clean_text(scan.get("target"), 64),
        "params": {"target": _clean_text(params.get("target"), 64),
                   "ports": _clean_text(params.get("ports"), 1024) or None},
        "started_at": _clean_text(scan.get("started_at"), 64) or None,
        "completed_at": _clean_text(scan.get("completed_at"), 64) or None,
        "hosts_up": scan.get("hosts_up") if isinstance(scan.get("hosts_up"), int) else 0,
        "hosts_down": scan.get("hosts_down") if isinstance(scan.get("hosts_down"), int) else 0,
        "result_count": len(clean_results),
        "hosts": clean_hosts,
        "results": clean_results,
        "warnings": [_clean_text(item, 300) for item in (scan.get("warnings") or [])
                     if isinstance(item, str)][:50],
        "error": _clean_text(scan.get("error"), 300) or None,
        "complete": scan.get("complete") is True,
    }


def start_scan(target, scan_type, ports=None):
    canonical_target, canonical_ports = validate_scan_request(target, scan_type, ports)
    result = _request("POST", "/api/scanner/scan", {
        "target": canonical_target,
        "scan_type": scan_type,
        "ports": canonical_ports,
    })
    return _sanitize_scan(result)


def scan_status(scan_id):
    try:
        normalized = str(uuid.UUID(str(scan_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise NetworkDiscoveryError("Invalid scan id") from exc
    return _sanitize_scan(_request("GET", f"/api/scanner/scan/{normalized}"))


def config_payload():
    error = None
    try:
        ranges = [str(item) for item in approved_ranges()]
    except NetworkDiscoveryError as exc:
        ranges = []
        error = str(exc)
    return {
        "configured": scanner_configured(),
        "approved_ranges": ranges,
        "default_ports": str(_config("SCANNER_DEFAULT_PORTS", DEFAULT_PORTS)),
        "max_hosts": _max_hosts(),
        "max_ports": _max_ports(),
        "scan_types": [
            {"value": "discover", "label": "Host discovery"},
            {"value": "services", "label": "Hosts and TCP services"},
        ],
        "error": error,
    }
