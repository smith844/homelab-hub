"""Nmap command construction, bounded execution and XML parsing.

This adapts the upstream scanner's host-discovery arguments and host/MAC/vendor
parsing to a dependency-free subprocess/XML implementation. It deliberately does
not use python-nmap, OS fingerprinting, NSE scripts or HTTP probing.
"""
from __future__ import annotations

import ipaddress
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

from .targets import TargetError, validate_ports, validate_target

MAX_RESULTS = 10000
MAX_TEXT = 200
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")


class NmapParseError(ValueError):
    """Nmap produced output that is not a usable nmaprun document."""


@dataclass
class CommandOutcome:
    returncode: int
    stdout: str
    stderr: str = ""
    timed_out: bool = False


@dataclass
class ParsedScan:
    hosts: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    hosts_up: int = 0
    hosts_down: int = 0
    finished_success: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    status: str
    hosts: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    hosts_up: int = 0
    hosts_down: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def complete(self) -> bool:
        return self.status == "completed"


def _text(value, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _short_error(value: str) -> str:
    text = _text(value, 300)
    return text or "nmap did not report a diagnostic"


def build_discovery_arguments(nmap_bin: str, target: str) -> list[str]:
    """Build a conservative host-discovery command (no OS or NSE probes)."""
    return [
        nmap_bin, "-sn", "-PR", "-PE", "-PS22,80,443,8080", "-PA80",
        "--max-retries", "2", "--max-rtt-timeout", "2s", "--host-timeout", "60s",
        "-T3", "-oX", "-", target,
    ]


def build_service_arguments(nmap_bin: str, target: str, ports: str) -> list[str]:
    """Build an unprivileged TCP connect scan with a bounded port list."""
    return [
        nmap_bin, "-sT", "-T3", "--max-retries", "2", "--max-rtt-timeout", "2s",
        "--host-timeout", "90s", "--open", "-p", ports, "-oX", "-", target,
    ]


def run_command(argv: list[str], timeout: int) -> CommandOutcome:
    """Run nmap without a shell; kill and salvage stdout on timeout."""
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
    except FileNotFoundError:
        return CommandOutcome(127, "", f"nmap executable not found: {argv[0]}")
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    return CommandOutcome(process.returncode, stdout or "", stderr or "", timed_out)


def _normalise_mac(value) -> str:
    text = _text(value, 32).replace("-", ":").upper()
    return text if _MAC_RE.fullmatch(text) else ""


def _hostname(host: ET.Element) -> str:
    for item in host.findall("hostnames/hostname"):
        name = _text(item.get("name"))
        if name:
            return name
    return ""


def _os_name(host: ET.Element) -> str:
    for item in host.findall("os/osmatch"):
        name = _text(item.get("name"))
        if name:
            return name
    return ""


def _vendor(addresses: dict[str, ET.Element]) -> str:
    mac = addresses.get("mac")
    if mac is None:
        return ""
    return _text(mac.get("vendor"))


def _service_version(service: ET.Element | None) -> tuple[str, str]:
    if service is None:
        return "", ""
    name = _text(service.get("name"))
    parts = [_text(service.get("product")), _text(service.get("version")),
             _text(service.get("extrainfo"))]
    version = " ".join(part for part in parts if part)
    return name, version


def parse_nmap_xml(xml: str, scan_type: str) -> ParsedScan:
    """Parse the useful host/service subset of nmap XML, skipping bad rows."""
    if scan_type not in ("discover", "services"):
        raise NmapParseError("Unknown scan type")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise NmapParseError("Nmap output is not valid XML") from exc
    if root.tag != "nmaprun":
        raise NmapParseError("Nmap output is not an nmaprun document")

    parsed = ParsedScan()
    for host in root.findall("host"):
        status = host.find("status")
        state = status.get("state") if status is not None else ""
        if state != "up":
            parsed.hosts_down += 1
            continue
        addresses = {item.get("addrtype"): item for item in host.findall("address")}
        ipv4 = _text(addresses.get("ipv4").get("addr") if addresses.get("ipv4") is not None else "")
        try:
            ip = str(ipaddress.IPv4Address(ipv4))
        except ValueError:
            parsed.warnings.append("Skipped a host without a valid IPv4 address")
            continue
        host_row = {
            "ip": ip,
            "hostname": _hostname(host),
            "mac": _normalise_mac(addresses.get("mac").get("addr")
                                  if addresses.get("mac") is not None else ""),
            "vendor": _vendor(addresses),
            "os": _os_name(host),
            "open_ports": 0,
        }
        parsed.hosts.append(host_row)
        parsed.hosts_up += 1
        if len(parsed.hosts) > MAX_RESULTS:
            parsed.warnings.append(f"Host results were truncated at {MAX_RESULTS}")
            break

        if scan_type == "discover":
            parsed.results.append(dict(host_row))
            continue

        service_rows = []
        for port_element in host.findall("ports/port"):
            if _text(port_element.get("protocol"), 16) != "tcp":
                continue
            state_element = port_element.find("state")
            if state_element is None or state_element.get("state") != "open":
                continue
            try:
                port = int(port_element.get("portid", ""))
            except (TypeError, ValueError):
                parsed.warnings.append("Skipped a service with an invalid port")
                continue
            if not 1 <= port <= 65535:
                parsed.warnings.append("Skipped a service with an invalid port")
                continue
            service_name, service_version = _service_version(port_element.find("service"))
            service_rows.append({
                **host_row,
                "port": port,
                "protocol": "tcp",
                "state": "open",
                "service_name": service_name,
                "service_version": service_version,
            })
            if len(parsed.results) + len(service_rows) > MAX_RESULTS:
                parsed.warnings.append(f"Service results were truncated at {MAX_RESULTS}")
                break
        host_row["open_ports"] = len(service_rows)
        for row in service_rows:
            row["open_ports"] = len(service_rows)
            parsed.results.append(row)

    runstats = root.find("runstats")
    if runstats is not None:
        hosts = runstats.find("hosts")
        if hosts is not None:
            try:
                parsed.hosts_up = int(hosts.get("up", parsed.hosts_up))
                parsed.hosts_down = int(hosts.get("down", parsed.hosts_down))
            except (TypeError, ValueError):
                parsed.warnings.append("Could not read host counts from nmap output")
    finished = root.find("runstats/finished")
    parsed.finished_success = finished is not None and finished.get("exit") == "success"
    return parsed


class NetworkScanner:
    """Run validated scans through an injectable command runner."""

    def __init__(self, nmap_bin: str = "nmap", max_scan_seconds: int = 300,
                 runner: Callable[[list[str], int], CommandOutcome] = run_command):
        self.nmap_bin = nmap_bin
        self.max_scan_seconds = max_scan_seconds
        self.runner = runner

    def scan(self, scan_type: str, target: str, ports: str | None = None,
             approved_ranges=None, max_hosts: int = 1024,
             max_ports: int = 256) -> ScanResult:
        try:
            canonical = validate_target(target, approved_ranges, max_hosts)
            port_text = validate_ports(ports, max_ports) if scan_type == "services" else ""
            if scan_type == "discover":
                argv = build_discovery_arguments(self.nmap_bin, canonical)
            elif scan_type == "services":
                argv = build_service_arguments(self.nmap_bin, canonical, port_text)
            else:
                raise TargetError("Scan type must be discover or services")
        except TargetError as exc:
            return ScanResult("failed", error=str(exc))

        outcome = self.runner(argv, self.max_scan_seconds)
        try:
            parsed = parse_nmap_xml(outcome.stdout, scan_type)
        except NmapParseError as exc:
            message = "Scan timed out before nmap produced usable results" if outcome.timed_out \
                else f"Could not parse nmap output: {exc}"
            if outcome.stderr:
                message += f" ({_short_error(outcome.stderr)})"
            return ScanResult("failed", error=message)

        warnings = list(parsed.warnings)
        if outcome.timed_out:
            warnings.append(f"Scan exceeded the {self.max_scan_seconds}s limit; results may be partial")
        if outcome.returncode != 0:
            warnings.append(f"nmap exited with status {outcome.returncode}")
        if not parsed.finished_success and not outcome.timed_out:
            warnings.append("nmap did not report a successful completed run")

        if outcome.timed_out or outcome.returncode != 0 or not parsed.finished_success:
            error = None
            if outcome.timed_out:
                error = f"Scan timed out after {self.max_scan_seconds}s; results are partial"
            elif outcome.returncode != 0:
                error = f"nmap failed: {_short_error(outcome.stderr)}"
            else:
                error = "nmap did not report a successful completed run; results are partial"
            return ScanResult("partial", parsed.hosts, parsed.results,
                              parsed.hosts_up, parsed.hosts_down, warnings, error)
        return ScanResult("completed", parsed.hosts, parsed.results,
                          parsed.hosts_up, parsed.hosts_down, warnings)
