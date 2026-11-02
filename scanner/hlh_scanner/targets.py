"""Explicit target and port validation for the restricted network scanner.

Only IPv4 addresses or CIDR networks that are fully contained in an operator
approved private range may be scanned. Targets are never derived from VLAN
numbers or interface names.
"""
from __future__ import annotations

import ipaddress
import re

MAX_HOSTS = 1024
MAX_PORTS = 256
DEFAULT_PORTS = "22,80,443,445,3389,8080,8443"

_PORT_TEXT_RE = re.compile(r"[0-9,\- ]+\Z")


class TargetError(ValueError):
    """An invalid or unapproved scan target or port specification."""


def _is_allowed_range(network: ipaddress.IPv4Network) -> bool:
    return not any((
        network.version != 4,
        not network.is_private,
        network.is_loopback,
        network.is_link_local,
        network.is_multicast,
        network.is_reserved,
        network.is_unspecified,
    ))


def parse_approved_ranges(value) -> list[ipaddress.IPv4Network]:
    """Parse comma/newline-separated approved private IPv4 ranges.

    An empty value means scanning is disabled. Invalid or non-private ranges
    are rejected rather than silently ignored.
    """
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else re.split(r"[,\n]+", str(value))
    networks: list[ipaddress.IPv4Network] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as exc:
            raise TargetError(f"Invalid approved network: {text}") from exc
        if network.version != 4 or not _is_allowed_range(network):
            raise TargetError(f"Approved networks must be private IPv4 ranges: {text}")
        if network not in networks:
            networks.append(network)
    return networks


def coerce_ranges(value) -> list[ipaddress.IPv4Network]:
    if not value:
        return []
    if all(isinstance(item, (ipaddress.IPv4Network, ipaddress.IPv6Network)) for item in value):
        return list(value)
    return parse_approved_ranges(value)


def validate_target(target, approved_ranges, max_hosts: int = MAX_HOSTS) -> str:
    """Return a canonical, approved IPv4 target or raise TargetError."""
    text = str(target or "").strip()
    if not text:
        raise TargetError("A scan target is required")
    if len(text) > 64:
        raise TargetError("Scan target is too long")
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError as exc:
        raise TargetError(f"Invalid IPv4 target: {text}") from exc
    if network.version != 4:
        raise TargetError("Only IPv4 scan targets are supported")

    networks = coerce_ranges(approved_ranges)
    if not networks:
        raise TargetError("No approved scan ranges are configured")
    if not any(network.subnet_of(approved) for approved in networks):
        raise TargetError("Scan target is outside the approved private ranges")
    if network.num_addresses > max_hosts:
        raise TargetError(
            f"Scan target contains {network.num_addresses} addresses; the limit is {max_hosts}"
        )
    return str(network) if "/" in text else str(network.network_address)


def validate_ports(value, max_ports: int = MAX_PORTS) -> str:
    """Return a canonical sorted comma-separated port list or raise TargetError."""
    text = str(value or "").strip()
    if not text:
        raise TargetError("A TCP port list is required for a service scan")
    if len(text) > 1024 or not _PORT_TEXT_RE.fullmatch(text):
        raise TargetError("Ports must be numbers, commas and ranges only")
    ports: set[int] = set()
    for token in text.replace(" ", "").split(","):
        if not token:
            raise TargetError("Port list contains an empty entry")
        if "-" in token:
            if token.count("-") != 1:
                raise TargetError(f"Invalid port range: {token}")
            start_text, end_text = token.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise TargetError(f"Invalid port range: {token}")
            start, end = int(start_text), int(end_text)
            if start > end:
                raise TargetError(f"Port range starts after it ends: {token}")
            candidates = range(start, end + 1)
        else:
            if not token.isdigit():
                raise TargetError(f"Invalid port: {token}")
            candidates = (int(token),)
        for port in candidates:
            if not 1 <= port <= 65535:
                raise TargetError(f"Port outside 1-65535: {port}")
            ports.add(port)
            if len(ports) > max_ports:
                raise TargetError(f"Too many ports; the limit is {max_ports}")
    if not ports:
        raise TargetError("A TCP port list is required for a service scan")
    return ",".join(str(port) for port in sorted(ports))
