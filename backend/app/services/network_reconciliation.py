"""Compare the verified scanner's network observations without inventing containers."""
import ipaddress
from ..models import VM
from .group_identity import root_hardware


def _ip(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _mac(value):
    return (value or "").strip().replace("-", ":").casefold()


def compare_network_scan(scan, host, apps):
    if scan is None:
        return None
    hosts = [host] + VM.query.filter_by(hardware_id=host.id).all()
    results = []
    for row in scan["results"]:
        ip = _ip(row.get("ip") or scan["target_ip"])
        if scan["type"] in ("discover", "identify"):
            mac = _mac(row.get("mac") or row.get("mac_address"))
            matches = [h for h in hosts if (ip and _ip(h.ip_address) == ip) or (mac and _mac(h.mac_address) == mac)]
            kind = "host"
        else:
            def endpoint(app):
                parent = app.vm if app.vm_id else root_hardware(app)
                return _ip(app.ip_address or (parent.ip_address if parent else None))
            matches = [app for app in apps if ip and endpoint(app) == ip and app.port == row["port"]]
            kind = "service"
        unverified = scan["status"] != "completed" or row.get("probe_failed")
        classification = "unverified" if unverified else "duplicate" if len(matches) > 1 else "matched" if matches else "unmatched"
        reason = (
            "Job is not completed or HTTP probing failed; candidate matches do not confirm availability." if unverified else
            "Multiple inventory records share the observed IP/MAC or service endpoint; review duplicates." if len(matches) > 1 else
            "Matched IP/MAC for a host or IP+port for an application within the selected root host." if matches else
            "No matching IP/MAC or IP+port in the selected root host's inventory; this does not establish a Docker identity or absence."
        )
        results.append({"kind": kind, "ip": ip, "port": row.get("port"),
                        "name": row.get("suggested_name") or row.get("hostname") or row.get("service_name") or ip,
                        "classification": classification,
                        "matches": [{"id": m.id, "name": m.name, "type": m.__tablename__} for m in matches],
                        "reason": reason})

    return {"type": scan["type"], "status": scan["status"], "rows": results,
            "reason": "Imported status response only; this page never starts network scans or calls scanner import endpoints."}
