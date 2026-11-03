"""Read-only, network-wide matching of Nmap observations against inventory.

Docker reconciliation remains host-scoped and unchanged. This module indexes
network identity evidence across the whole inventory (hardware, VMs, other
devices, application endpoints and network-member addresses) and explains each
proposed match. It never modifies inventory or map data.

The observation layer is deliberately separate from inventory matching so future
sources (for example UniFi client/DHCP evidence) can supply the same normalized
observations without changing the matching rules.
"""
from __future__ import annotations

import ipaddress
import re
from collections import OrderedDict
from urllib.parse import urlsplit

from ..models import AppService, Hardware, Misc, Network, NetworkMember, VM

SCAN_STATUSES = ("running", "completed", "partial", "failed", "expired", "unknown")
SCAN_TYPES = ("discover", "portscan")
MAX_OBSERVATIONS = 5000
DEVICE_TYPES = {"hardware", "vms", "misc"}
MEMBER_TYPE_ALIASES = {
    "hardware": "hardware",
    "host": "hardware",
    "hosts": "hardware",
    "vm": "vms",
    "vms": "vms",
    "app": "apps",
    "apps": "apps",
    "misc": "misc",
    "other": "misc",
    "others": "misc",
}
CATEGORY_LABELS = {
    "hardware": "Physical host",
    "vms": "VM / runtime",
    "misc": "Other device",
    "apps": "Application / service",
}


class NetworkWideError(ValueError):
    """Malformed network-wide comparison input."""


def _text(value, limit=300):
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


def _normalise_hostname(value):
    text = _text(value, 300).strip().rstrip(".").casefold()
    if not text:
        return None
    if "://" in text:
        try:
            text = (urlsplit(text).hostname or "").rstrip(".").casefold()
        except ValueError:
            return None
    # Strip a common host:port form without touching IPv4/IPv6-like values.
    if text.count(":") == 1:
        host, port = text.rsplit(":", 1)
        if port.isdigit():
            text = host
    if not text or len(text) > 253 or any(char.isspace() for char in text):
        return None
    return text


def _hostname_values(value):
    names = set()
    for token in re.split(r"[\s,]+", _text(value, 500)):
        normalized = _normalise_hostname(token)
        if normalized:
            names.add(normalized)
    return names


def _normalise_name(value):
    text = _text(value, 300).strip().rstrip(".").casefold()
    if not text or len(text) > 253:
        return None
    return re.sub(r"\s+", " ", text)


def _add_name_alias(record, name):
    key = _normalise_name(name)
    if key:
        record["hostnames"].setdefault(key, "inventory name")


def _related_devices(records):
    """True only for one hardware host plus its single VM/runtime candidate."""
    hardware = [row for row in records if row["type"] == "hardware"]
    vms = [row for row in records if row["type"] == "vms"]
    if len(hardware) != 1 or len(vms) != 1 or len(records) != 2:
        return False
    parent = vms[0].get("parent") or {}
    return parent.get("type") == "hardware" and parent.get("id") == hardware[0]["id"]


def _network_contexts():
    contexts = []
    for network in Network.query.all():
        if not network.subnet:
            continue
        try:
            subnet = ipaddress.ip_network(network.subnet, strict=False)
        except ValueError:
            continue
        contexts.append({
            "id": network.id,
            "name": network.name,
            "vlan_id": network.vlan_id,
            "_subnet": subnet,
        })
    return contexts


def _network_for_ip(ip, contexts):
    if not ip:
        return None
    address = ipaddress.ip_address(ip)
    for context in contexts:
        if address in context["_subnet"]:
            return {key: value for key, value in context.items() if key != "_subnet"}
    return None


def _record(kind, entity_type, entity, category, parent=None):
    return {
        "kind": kind,
        "type": entity_type,
        "id": entity.id,
        "name": _text(entity.name, 200) or f"{entity_type}-{entity.id}",
        "category": category,
        "parent": parent,
        "ips": set(),
        "ip_evidence": {},
        "macs": set(),
        "hostnames": {},
        "port": None,
    }


def _add_ip(record, value, evidence):
    ip = _ip(value)
    if ip:
        record["ips"].add(ip)
        record["ip_evidence"].setdefault(ip, evidence)


def _add_hostname(record, value, label):
    for normalized in _hostname_values(value):
        record["hostnames"].setdefault(normalized, label)


def build_inventory_index():
    """Index all inventory identity evidence without interpreting one table as all."""
    hardware = Hardware.query.all()
    vms = VM.query.all()
    misc = Misc.query.all()
    apps = AppService.query.all()
    members = NetworkMember.query.all()
    networks = _network_contexts()

    hardware_by_id = {row.id: row for row in hardware}
    vm_by_id = {row.id: row for row in vms}
    records: OrderedDict[tuple[str, int], dict] = OrderedDict()

    for host in hardware:
        row = _record("device", "hardware", host, CATEGORY_LABELS["hardware"])
        _add_ip(row, host.ip_address, "IP address")
        mac = _mac(host.mac_address)
        if mac:
            row["macs"].add(mac)
        _add_hostname(row, host.hostname, "hostname")
        _add_name_alias(row, host.name)
        records[("hardware", host.id)] = row

    for vm in vms:
        parent_host = hardware_by_id.get(vm.hardware_id)
        parent = None
        if parent_host:
            parent = {"type": "hardware", "id": parent_host.id, "name": parent_host.name}
        row = _record("device", "vms", vm, CATEGORY_LABELS["vms"], parent)
        _add_ip(row, vm.ip_address, "IP address")
        mac = _mac(vm.mac_address)
        if mac:
            row["macs"].add(mac)
        _add_hostname(row, vm.hostname, "hostname")
        _add_name_alias(row, vm.name)
        records[("vms", vm.id)] = row

    for item in misc:
        row = _record("device", "misc", item, CATEGORY_LABELS["misc"])
        _add_ip(row, item.ip_address, "IP address")
        _add_hostname(row, item.hostname, "hostname")
        _add_name_alias(row, item.name)
        records[("misc", item.id)] = row

    for app in apps:
        parent = None
        parent_ip = None
        if app.vm_id and vm_by_id.get(app.vm_id):
            parent_vm = vm_by_id[app.vm_id]
            parent = {"type": "vms", "id": parent_vm.id, "name": parent_vm.name}
            parent_ip = parent_vm.ip_address
        elif app.hardware_id and hardware_by_id.get(app.hardware_id):
            parent_host = hardware_by_id[app.hardware_id]
            parent = {"type": "hardware", "id": parent_host.id, "name": parent_host.name}
            parent_ip = parent_host.ip_address
        row = _record("service", "apps", app, CATEGORY_LABELS["apps"], parent)
        row["port"] = app.port if isinstance(app.port, int) and 1 <= app.port <= 65535 else None
        explicit = _ip(app.ip_address)
        if explicit:
            _add_ip(row, explicit, "application IP")
        elif parent_ip:
            _add_ip(row, parent_ip, "parent IP")
        _add_hostname(row, app.hostname, "service hostname")
        _add_hostname(row, app.external_hostname, "external hostname")
        records[("apps", app.id)] = row

    for member in members:
        member_type = MEMBER_TYPE_ALIASES.get(_text(member.member_type, 32).casefold())
        if not member_type:
            continue
        record = records.get((member_type, member.member_id))
        if record is None:
            continue
        network = next((item for item in networks if item["id"] == member.network_id), None)
        evidence = "network membership"
        if network:
            evidence = f"network membership ({network['name']})"
        _add_ip(record, member.ip_on_network, evidence)

    devices = [row for row in records.values() if row["kind"] == "device"]
    services = [row for row in records.values() if row["kind"] == "service"]
    return {"devices": devices, "services": services, "networks": networks}


def _clean_observation(row, *, service=False):
    ip = _ip(row.get("ip"))
    if not ip:
        return None, "Skipped an observation without a valid IPv4 address"
    hostname = _text(row.get("hostname"), 300)
    mac = _mac(row.get("mac") or row.get("mac_address"))
    vendor = _text(row.get("vendor"), 200)
    os_name = _text(row.get("os"), 200)
    if service:
        try:
            port = int(row.get("port"))
        except (TypeError, ValueError):
            return None, "Skipped a service observation without a valid port"
        if not 1 <= port <= 65535:
            return None, "Skipped a service observation without a valid port"
        return {
            "ip": ip,
            "hostname": hostname,
            "mac": mac or "",
            "vendor": vendor,
            "os": os_name,
            "port": port,
            "service_name": _text(row.get("service_name"), 200),
            "service_version": _text(row.get("service_version"), 400),
        }, None
    return {
        "ip": ip,
        "hostname": hostname,
        "mac": mac or "",
        "vendor": vendor,
        "os": os_name,
        "open_ports": row.get("open_ports") if isinstance(row.get("open_ports"), int) else 0,
    }, None


def normalise_scan_observations(scan):
    """Validate and normalize scanner status into host/service observations."""
    if not isinstance(scan, dict):
        raise NetworkWideError("A scanner status object is required")
    if isinstance(scan.get("data"), dict):
        scan = scan["data"]
    status = scan.get("status", "unknown")
    if status not in SCAN_STATUSES:
        raise NetworkWideError("Unknown scanner status")
    scan_type = scan.get("type")
    if scan_type not in SCAN_TYPES:
        raise NetworkWideError("Network comparison requires discover or portscan results")
    results = scan.get("results")
    if not isinstance(results, list) or len(results) > MAX_OBSERVATIONS:
        raise NetworkWideError("Scanner results must be an array with at most 5000 entries")
    raw_hosts = scan.get("hosts") if isinstance(scan.get("hosts"), list) else []
    if len(raw_hosts) > MAX_OBSERVATIONS:
        raise NetworkWideError("Scanner hosts must contain at most 5000 entries")

    params = scan.get("params") if isinstance(scan.get("params"), dict) else {}
    target = _text(scan.get("target") or params.get("target"), 64)
    warnings = []
    hosts = OrderedDict()

    def add_host(row):
        cleaned, warning = _clean_observation(row)
        if warning:
            warnings.append(warning)
            return None
        current = hosts.get(cleaned["ip"])
        if current is None:
            current = dict(cleaned)
            current["open_ports"] = max(0, current["open_ports"])
            hosts[cleaned["ip"]] = current
        else:
            for key in ("hostname", "mac", "vendor", "os"):
                if not current[key] and cleaned[key]:
                    current[key] = cleaned[key]
            current["open_ports"] = max(current["open_ports"], cleaned["open_ports"])
        return cleaned["ip"], current

    for row in raw_hosts:
        if not isinstance(row, dict):
            warnings.append("Skipped a malformed host observation")
            continue
        add_host(row)

    services = []
    service_ports: dict[str, set[int]] = {}
    for row in results:
        if not isinstance(row, dict):
            warnings.append("Skipped a malformed service observation")
            continue
        if scan_type == "discover":
            add_host(row)
            continue
        service, warning = _clean_observation(row, service=True)
        if warning:
            warnings.append(warning)
            continue
        services.append(service)
        service_ports.setdefault(service["ip"], set()).add(service["port"])
        current = hosts.get(service["ip"])
        if current is None:
            current = {
                "ip": service["ip"], "hostname": service["hostname"],
                "mac": service["mac"], "vendor": service["vendor"],
                "os": service["os"], "open_ports": 0,
            }
            hosts[service["ip"]] = current
        for key in ("hostname", "mac", "vendor", "os"):
            if not current[key] and service[key]:
                current[key] = service[key]
    # A scanner host row may already contain a count; use the larger of that
    # count and the unique service ports actually present in this result set.
    for ip, ports in service_ports.items():
        hosts[ip]["open_ports"] = max(hosts[ip].get("open_ports", 0), len(ports))

    if scan_type == "discover" and not hosts:
        for row in results:
            if isinstance(row, dict):
                add_host(row)

    def ip_sort_key(item):
        try:
            return (0, int(ipaddress.ip_address(item["ip"])))
        except ValueError:
            return (1, item["ip"])

    host_rows = sorted(hosts.values(), key=ip_sort_key)
    service_rows = sorted(services, key=lambda item: (ip_sort_key(item), item["port"]))
    source_warnings = scan.get("warnings")
    if not isinstance(source_warnings, list):
        source_warnings = []
    return {
        "type": scan_type,
        "status": status,
        "target": target,
        "completed_at": _text(scan.get("completed_at"), 64) or None,
        "hosts": host_rows,
        "services": service_rows,
        "warnings": warnings + [_text(item, 300) for item in source_warnings
                                if isinstance(item, str)][:50],
        "uncertain": status != "completed" or scan.get("complete") is False,
    }


def _candidate(record, evidence):
    return {
        "type": record["type"],
        "id": record["id"],
        "name": record["name"],
        "category": record["category"],
        "parent": record.get("parent"),
        "ip": sorted(record["ips"])[0] if record["ips"] else None,
        "port": record.get("port"),
        "evidence": list(dict.fromkeys(evidence)),
    }


def _evidence(record, ip, mac, hostnames):
    evidence = []
    if ip and ip in record["ips"]:
        evidence.append(record["ip_evidence"].get(ip, "IP address"))
    if mac and mac in record["macs"]:
        evidence.append("MAC address")
    for hostname in hostnames:
        label = record["hostnames"].get(hostname)
        if label:
            evidence.append(label)
    return evidence


def _append_unique(target, record, evidence):
    key = (record["type"], record["id"])
    existing = next((item for item in target if (item["record"]["type"], item["record"]["id"]) == key), None)
    if existing:
        existing["evidence"].extend(item for item in evidence if item not in existing["evidence"])
    else:
        target.append({"record": record, "evidence": list(dict.fromkeys(evidence))})


def _device_summary(record, evidence):
    return _candidate(record, evidence)


def _classify_host(observation, index, uncertain):
    ip = observation["ip"]
    mac = observation["mac"]
    hostnames = set(_hostname_values(observation["hostname"]))
    hostnames.update(observation.get("_unifi_names") or [])
    ip_devices = [row for row in index["devices"] if ip in row["ips"]]
    mac_devices = [row for row in index["devices"] if mac and mac in row["macs"]]
    hostname_devices = [
        row for row in index["devices"]
        if any(hostname in row["hostnames"] for hostname in hostnames)
    ]
    service_candidates = []
    service_ip = []
    service_hostname = []
    for record in index["services"]:
        evidence = _evidence(record, ip, mac, hostnames)
        if ip and ip in record["ips"]:
            service_ip.append((record, evidence))
        elif any(hostname in record["hostnames"] for hostname in hostnames):
            service_hostname.append((record, evidence))
        if evidence:
            _append_unique(service_candidates, record, evidence)

    device_candidates = []
    for record in ip_devices:
        _append_unique(device_candidates, record, _evidence(record, ip, mac, hostnames))
    for record in mac_devices:
        _append_unique(device_candidates, record, _evidence(record, ip, mac, hostnames))
    for record in hostname_devices:
        _append_unique(device_candidates, record, _evidence(record, ip, mac, hostnames))

    ip_ids = {(row["type"], row["id"]) for row in ip_devices}
    mac_ids = {(row["type"], row["id"]) for row in mac_devices}
    hostname_ids = {(row["type"], row["id"]) for row in hostname_devices}
    conflict = bool(ip_ids and mac_ids and not ip_ids.intersection(mac_ids))
    conflict = conflict or bool(ip_ids and hostname_ids and not ip_ids.intersection(hostname_ids))

    candidates = []
    evidence = []
    service_only = False
    if uncertain:
        classification = "unverified"
        reason = "Scan is partial, failed or incomplete; candidates are unverified and absence is never inferred."
    elif conflict:
        classification = "ambiguous"
        if len(ip_devices) > 1:
            reason = ("Multiple inventory devices share this IP (possible virtual IP or "
                      "shared endpoint), and hostname evidence points elsewhere; review candidates.")
        else:
            reason = "IP, MAC and hostname evidence point to different inventory records; review before deciding."
    elif device_candidates:
        records = [item["record"] for item in device_candidates]
        if len(records) > 1 and _related_devices(records):
            classification = "shared"
            reason = "Host and its VM/runtime share this address; treated as one endpoint, not duplicate physical devices."
        elif len(records) > 1:
            classification = "ambiguous"
            reason = "Multiple inventory devices share this address; possible virtual IP or shared endpoint."
        else:
            record = records[0]
            evidence_types = device_candidates[0]["evidence"]
            if ip in record["ips"] or (mac and mac in record["macs"]):
                classification = "matched"
                reason = "Exact IP/MAC evidence in inventory."
            else:
                classification = "plausible"
                reason = "Hostname or inventory name matches, but IP/MAC does not; DNS may be stale."
            evidence = evidence_types
        candidates = [_device_summary(item["record"], item["evidence"]) for item in device_candidates]
    elif service_candidates:
        classification = "plausible"
        reason = "Only application/service endpoints match this address; no physical device record."
        candidates = [_device_summary(item["record"], item["evidence"])
                      for item in service_candidates]
        service_only = True
        evidence = [item for item in (service_ip + service_hostname) for item in item[1]]
    else:
        classification = "unmatched"
        reason = "No reliable inventory match; this does not establish that a device is absent."

    if uncertain:
        evidence = [item for candidate in device_candidates for item in candidate["evidence"]]
        if not evidence:
            evidence = [item for item in (service_ip + service_hostname) for item in item[1]]
    if not candidates and device_candidates:
        candidates = [_device_summary(item["record"], item["evidence"]) for item in device_candidates]
    if not candidates and service_candidates:
        candidates = [_device_summary(item["record"], item["evidence"]) for item in service_candidates]
        service_only = True
    if not evidence:
        evidence = [item for candidate in device_candidates for item in candidate["evidence"]]
        if not evidence:
            evidence = [item for item in (service_ip + service_hostname) for item in item[1]]

    # Applications are always shown separately from physical/device candidates,
    # except when the host itself is service-only and those apps are the candidates.
    services_on_address = ([] if service_only else
                           [_device_summary(item["record"], item["evidence"])
                            for item in service_candidates])

    return {
        **observation,
        "classification": classification,
        "reason": reason,
        "evidence": list(dict.fromkeys(evidence)),
        "candidates": candidates,
        "service_candidates": services_on_address,
        "network": _network_for_ip(ip, index["networks"]),
    }


def _classify_service(observation, index, uncertain):
    ip = observation["ip"]
    mac = observation["mac"]
    hostnames = _hostname_values(observation["hostname"])
    port = observation["port"]
    matches = []
    explicit = []
    inherited = []
    hostname_only = []
    for record in index["services"]:
        if record.get("port") != port:
            continue
        evidence = _evidence(record, ip, mac, hostnames)
        if not evidence:
            continue
        _append_unique(matches, record, evidence)
        if ip in record["ips"]:
            label = str(record["ip_evidence"].get(ip, ""))
            if label == "application IP" or label.startswith("network membership"):
                explicit.append(record)
            else:
                inherited.append(record)
        else:
            hostname_only.append(record)

    if uncertain:
        classification = "unverified"
        reason = "Scan is partial, failed or incomplete; service candidates are unverified."
    elif len(matches) > 1:
        classification = "ambiguous"
        reason = "Multiple application/service records share this IP and port; review before deciding."
    elif len(matches) == 1:
        if explicit:
            classification = "matched"
            reason = "Explicit application IP and TCP port match."
        elif inherited:
            classification = "plausible"
            reason = "Application has no explicit IP; it inherits the parent address for this port."
        else:
            classification = "plausible"
            reason = "Service hostname and port match; DNS may be stale or shared."
    else:
        classification = "unmatched"
        reason = "No application/service endpoint recorded for this IP and port; a host-level match may still exist."

    candidates = [_device_summary(item["record"], item["evidence"]) for item in matches]
    evidence = [item for candidate in matches for item in candidate["evidence"]]
    return {
        **observation,
        "classification": classification,
        "reason": reason,
        "evidence": list(dict.fromkeys(evidence)),
        "candidates": candidates,
    }


def normalise_unifi_observations(rows):
    """Normalize cached UniFi observations without trusting extra controller fields."""
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows[:MAX_OBSERVATIONS]:
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        if kind not in ("device", "client"):
            continue
        mac = row.get("mac")
        mac = mac.casefold() if isinstance(mac, str) and _mac(mac) else ""
        ip = _ip(row.get("ip"))
        ips = []
        for value in [row.get("ip")] + (row.get("ips")[:16] if isinstance(row.get("ips"), list) else []):
            parsed = _ip(value)
            if parsed and parsed not in ips:
                ips.append(parsed)
        if not ip and ips:
            ip = ips[0]
        name = _text(row.get("name"), 200)
        hostname = _text(row.get("hostname"), 300)
        if not name and not hostname and not ip and not mac:
            continue
        network = row.get("network") if isinstance(row.get("network"), dict) else None
        cleaned_network = None
        if network:
            vlan = network.get("vlan_id")
            try:
                vlan = int(vlan) if vlan is not None else None
            except (TypeError, ValueError):
                vlan = None
            cleaned_network = {"name": _text(network.get("name"), 120) or None, "vlan_id": vlan}
        online = row.get("online") if isinstance(row.get("online"), bool) else None
        result.append({
            "source": "unifi",
            "observed_at": _text(row.get("observed_at"), 64) or None,
            "kind": kind,
            "id": _text(row.get("id"), 128) or mac or name,
            "name": name,
            "hostname": hostname,
            "mac": mac or None,
            "ip": ip,
            "ips": ips,
            "model": _text(row.get("model"), 120),
            "vendor": _text(row.get("vendor"), 120),
            "device_type": _text(row.get("device_type"), 64),
            "state": _text(row.get("state"), 32) or None,
            "online": online,
            "connected_at": _text(row.get("connected_at"), 64) or None,
            "last_seen": _text(row.get("last_seen"), 64) or None,
            "uplink_device_id": _text(row.get("uplink_device_id"), 128) or None,
            "network": cleaned_network,
        })
    return result


def _unifi_names(row):
    names = set(_hostname_values(row.get("hostname")))
    friendly = _normalise_name(row.get("name"))
    if friendly:
        names.add(friendly)
    return names


def _unifi_index(rows):
    by_mac, by_ip, by_name = {}, {}, {}
    for row in rows:
        if row.get("mac"):
            by_mac.setdefault(row["mac"], []).append(row)
        for ip in row.get("ips") or ([row["ip"]] if row.get("ip") else []):
            by_ip.setdefault(ip, []).append(row)
        for name in _unifi_names(row):
            by_name.setdefault(name, []).append(row)
    return {"by_mac": by_mac, "by_ip": by_ip, "by_name": by_name}


def _matching_unifi(observation, unifi_index):
    matches = OrderedDict()
    mac = observation.get("mac")
    ip = observation.get("ip")
    names = _hostname_values(observation.get("hostname"))
    for row in unifi_index["by_mac"].get(mac, []) if mac else []:
        matches[(row["kind"], row["id"])] = row
    for row in unifi_index["by_ip"].get(ip, []) if ip else []:
        matches[(row["kind"], row["id"])] = row
    for name in names:
        for row in unifi_index["by_name"].get(name, []):
            matches[(row["kind"], row["id"])] = row
    return list(matches.values())


def _unifi_record_evidence(record, row):
    evidence = []
    if row.get("mac") and row["mac"] in record["macs"]:
        evidence.append("UniFi MAC")
    if any(ip in record["ips"] for ip in (row.get("ips") or [row.get("ip")]) if ip):
        evidence.append("UniFi IP")
    if _unifi_names(row).intersection(record["hostnames"]):
        evidence.append("UniFi name")
    return evidence


def _append_candidate(candidates, record, evidence):
    key = (record["type"], record["id"])
    existing = next((item for item in candidates
                     if (item["type"], item["id"]) == key), None)
    if existing:
        existing["evidence"] = list(dict.fromkeys(existing["evidence"] + evidence))
    else:
        candidates.append(_candidate(record, evidence))


def _public_unifi(row):
    return {
        "source": "unifi",
        "kind": row["kind"],
        "name": row["name"],
        "hostname": row["hostname"],
        "mac": row["mac"],
        "ip": row["ip"],
        "ips": row.get("ips") or ([row["ip"]] if row["ip"] else []),
        "device_type": row["device_type"],
        "online": row["online"],
        "state": row["state"],
        "last_seen": row["last_seen"],
        "connected_at": row["connected_at"],
        "network": row.get("network"),
        "vendor": row["vendor"],
        "model": row["model"],
        "uplink_device_id": row["uplink_device_id"],
    }


def _apply_unifi(row, matches, index):
    """Attach UniFi evidence without letting stale records override Nmap."""
    if not matches:
        row["sources"] = ["nmap"]
        row.setdefault("unifi_matches", [])
        row.setdefault("unifi_evidence", [])
        row.setdefault("source_conflict", False)
        return row

    row["sources"] = ["nmap", "unifi"]
    row["unifi_matches"] = [_public_unifi(item) for item in matches]
    current = [item for item in matches if item.get("online") is True]
    historical = [item for item in matches if item.get("online") is not True]
    evidence = []
    hits = {}
    for item in current:
        item_hits = []
        for record in index["devices"]:
            hit_evidence = _unifi_record_evidence(record, item)
            if hit_evidence:
                item_hits.append((record, hit_evidence))
        mac_hits = [pair for pair in item_hits if "UniFi MAC" in pair[1]]
        if mac_hits:
            item_hits = mac_hits
        for record, hit_evidence in item_hits:
            key = (record["type"], record["id"])
            hits.setdefault(key, {"record": record, "evidence": []})
            hits[key]["evidence"] = list(dict.fromkeys(hits[key]["evidence"] + hit_evidence))
            evidence.extend(hit_evidence)

    existing_ids = {(candidate["type"], candidate["id"])
                    for candidate in row.get("candidates", [])
                    if candidate["type"] in DEVICE_TYPES}
    for item in hits.values():
        _append_candidate(row.setdefault("candidates", []), item["record"], item["evidence"])
    hit_ids = set(hits)

    if hit_ids:
        if len(hit_ids) == 1:
            record = next(iter(hits.values()))["record"]
            item_evidence = next(iter(hits.values()))["evidence"]
            if not existing_ids:
                row["classification"] = "matched" if "UniFi MAC" in item_evidence else "plausible"
                row["reason"] = (
                    "UniFi current evidence identifies this inventory device; "
                    "it was not matched by the Nmap inventory lookup alone."
                )
            elif hit_ids.issubset(existing_ids):
                row["evidence"] = list(dict.fromkeys(row.get("evidence", []) + item_evidence))
        else:
            row["classification"] = "ambiguous"
            row["source_conflict"] = True
            row["reason"] = (
                "UniFi current evidence matches multiple inventory devices; "
                "review before deciding."
            )
    if existing_ids and hit_ids and not existing_ids.intersection(hit_ids):
        row["classification"] = "ambiguous"
        row["source_conflict"] = True
        row["reason"] = "Nmap and UniFi evidence identify different inventory devices; review."

    # A Nmap MAC and a UniFi MAC that disagree are an explicit source conflict.
    nmap_mac = row.get("mac")
    unifi_macs = {item["mac"] for item in current if item.get("mac")}
    if nmap_mac and unifi_macs and nmap_mac not in unifi_macs:
        row["source_conflict"] = True
        evidence.append("UniFi MAC differs from Nmap MAC")
        if row["classification"] == "matched":
            row["classification"] = "ambiguous"
            row["reason"] = "Nmap and UniFi MAC evidence disagree; review before deciding."

    for item in historical:
        evidence.append("UniFi historical record (not current)")
    for item in matches:
        evidence.append("UniFi " + item["kind"])
        if item.get("name"):
            evidence.append("UniFi friendly name")
        if item.get("network"):
            evidence.append("UniFi network")
    row["unifi_evidence"] = list(dict.fromkeys(evidence))
    row["evidence"] = list(dict.fromkeys(row.get("evidence", []) + evidence))
    row.setdefault("source_conflict", False)
    return row


def _classify_unifi_only(row, index):
    observation = {
        "ip": row.get("ip"),
        "hostname": row.get("hostname") or "",
        "mac": row.get("mac") or "",
        "_unifi_names": list(_unifi_names(row)),
        "open_ports": 0,
    }
    result = _classify_host(observation, index, False)
    result.pop("_unifi_names", None)
    result.update({
        "source": "unifi",
        "sources": ["unifi"],
        "unifi_only": True,
        "unifi_matches": [_public_unifi(row)],
        "online": row.get("online"),
        "state": row.get("state"),
        "last_seen": row.get("last_seen"),
        "connected_at": row.get("connected_at"),
        "device_type": row.get("device_type"),
        "network": row.get("network") or result.get("network"),
        "reason": (
            "UniFi-only known device; it was not observed in the current Nmap scan. "
            + ("UniFi reports it offline/historical. " if row.get("online") is False else "")
            + result["reason"]
        ),
    })
    unifi_evidence = []
    for record in index["devices"]:
        evidence = _unifi_record_evidence(record, row)
        if evidence:
            _append_candidate(result.setdefault("candidates", []), record, evidence)
            unifi_evidence.extend(evidence)
    if unifi_evidence:
        result["evidence"] = list(dict.fromkeys(result.get("evidence", []) + unifi_evidence))
    result["unifi_evidence"] = list(dict.fromkeys(unifi_evidence + [
        "UniFi " + row["kind"], "UniFi friendly name" if row.get("name") else "",
        "UniFi offline" if row.get("online") is False else "UniFi online",
    ]))
    result["unifi_evidence"] = [item for item in result["unifi_evidence"] if item]
    return result


def reconcile_observations(observations, inventory_index=None, unifi_observations=None,
                            unifi_status=None):
    """Match normalized host/service observations against the full inventory.

    Future evidence sources (for example UniFi client/DHCP data) can produce the
    same normalized observation shape and reuse these rules without becoming
    authoritative or writing inventory.
    """
    if not isinstance(observations, dict):
        raise NetworkWideError("Normalized observations are required")
    index = inventory_index or build_inventory_index()
    unifi_rows = normalise_unifi_observations(unifi_observations or [])
    unifi_by = _unifi_index(unifi_rows)
    used_unifi = set()
    hosts = []
    for row in observations.get("hosts", []):
        matches = _matching_unifi(row, unifi_by)
        prepared = dict(row)
        current_macs = {item["mac"] for item in matches
                        if item.get("online") is True and item.get("mac")}
        supplied_unifi_mac = False
        if not prepared.get("mac") and len(current_macs) == 1:
            prepared["mac"] = next(iter(current_macs))
            supplied_unifi_mac = True
        prepared["_unifi_names"] = sorted({
            name for item in matches for name in _unifi_names(item)})
        result = _classify_host(prepared, index, observations.get("uncertain", False))
        result.pop("_unifi_names", None)
        result = _apply_unifi(result, matches, index)
        if supplied_unifi_mac and result["classification"] == "ambiguous":
            result["source_conflict"] = True
            result["reason"] = "Nmap IP and UniFi MAC evidence identify different inventory devices; review."
        used_unifi.update((item["kind"], item["id"]) for item in matches)
        hosts.append(result)
    services = []
    for row in observations.get("services", []):
        result = _classify_service(row, index, observations.get("uncertain", False))
        result["sources"] = ["nmap"]
        services.append(result)

    unifi_only = []
    for row in unifi_rows:
        if (row["kind"], row["id"]) in used_unifi:
            continue
        unifi_only.append(_classify_unifi_only(row, index))

    devices = [row for row in unifi_rows if row["kind"] == "device"]
    clients = [row for row in unifi_rows if row["kind"] == "client"]
    status = dict(unifi_status or {})
    status.update({
        "configured": bool(status.get("configured", bool(unifi_rows))),
        "has_data": bool(status.get("has_data", bool(unifi_rows))),
        "infrastructure_devices": len(devices),
        "clients": len(clients),
        "online_devices": sum(row.get("online") is True for row in devices),
        "offline_devices": sum(row.get("online") is False for row in devices),
        "current_clients": sum(row.get("online") is True for row in clients),
        "historical_clients": sum(row.get("online") is False for row in clients),
        "unifi_only": len(unifi_only),
    })

    host_counts = {key: sum(row["classification"] == key for row in hosts)
                   for key in ("matched", "plausible", "shared", "ambiguous", "unmatched", "unverified")}
    service_counts = {key: sum(row["classification"] == key for row in services)
                      for key in ("matched", "plausible", "ambiguous", "unmatched", "unverified")}
    return {
        "source": observations.get("source", "nmap"),
        "sources": ["nmap"] + (["unifi"] if unifi_rows else []),
        "scan": {
            "type": observations.get("type"),
            "status": observations.get("status"),
            "target": observations.get("target"),
            "completed_at": observations.get("completed_at"),
            "uncertain": bool(observations.get("uncertain")),
            "warnings": list(observations.get("warnings") or []),
        },
        "hosts": hosts,
        "services": services,
        "unifi_only": unifi_only,
        "unifi": status,
        "summary": {
            "hosts_discovered": len(hosts),
            **{f"hosts_{key}": value for key, value in host_counts.items()},
            "services_discovered": len(services),
            **{f"services_{key}": value for key, value in service_counts.items()},
            "inventory_devices": len(index["devices"]),
            "inventory_services": len(index["services"]),
            "unifi_infrastructure_devices": len(devices),
            "unifi_clients": len(clients),
            "unifi_current_clients": status["current_clients"],
            "unifi_historical_clients": status["historical_clients"],
            "unifi_only": len(unifi_only),
            "nmap_hosts_with_unifi": sum("unifi" in row.get("sources", []) for row in hosts),
            "unifi_source_conflicts": sum(bool(row.get("source_conflict")) for row in hosts),
        },
        "reason": (
            "Read-only network-wide comparison across hardware, VMs, other devices, "
            "application endpoints and network memberships. Nmap observations are current "
            "scan evidence; UniFi records are separate client/device evidence and offline "
            "or missing records are never treated as Nmap absence. A missing observation "
            "never proves that an inventory device was removed."
        ),
    }


def compare_network_wide(scan, unifi_observations=None, unifi_status=None):
    """Return a read-only, network-wide comparison for a scanner status object."""
    return reconcile_observations(
        normalise_scan_observations(scan),
        unifi_observations=unifi_observations,
        unifi_status=unifi_status,
    )
