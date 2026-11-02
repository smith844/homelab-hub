"""Input-only adapters: no scanner calls or assumptions about Docker from ports.

The dpinna13 status adapter follows deployed 9feebd5. Container snapshot v1 is
HomeLab-Hub's separate operator-supplied contract, NOT an upstream scanner API.
"""
from datetime import datetime, timezone
import re

from .group_identity import normalize_identity

MAX_AGE_SECONDS = 24 * 60 * 60


class ReconciliationError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def text(value, limit=1024):
    return value.strip()[:limit] if isinstance(value, str) else ""


def normalise_snapshot(payload, host_key):
    if payload is None:
        return {"status": "missing", "complete": False, "coverage": "unknown", "completed_at": None,
                "source": "none", "containers": [], "fresh": False, "authoritative": False,
                "reason": "No scan supplied. Missing discovery data does not prove absence."}
    if not isinstance(payload, dict):
        raise ReconciliationError("Snapshot must be a JSON object")
    state = payload.get("data", payload)
    if isinstance(state, dict) and (state.get("type") in ("discover", "identify", "portscan", "probe_http") or (state.get("status") == "expired" and "scan_id" in state)):
        return network_snapshot(state)
    if normalize_identity(payload.get("host_key") or payload.get("host")) != host_key:
        raise ReconciliationError("Snapshot host must match the selected root hardware host")
    if type(payload.get("schema_version", 1)) is not int or payload.get("schema_version", 1) != 1:
        raise ReconciliationError("Unsupported snapshot schema_version")
    status = payload.get("status", "unknown")
    if status not in ("success", "failed", "unknown"):
        raise ReconciliationError("Snapshot status must be success, failed or unknown")
    complete = payload.get("complete", False)
    if not isinstance(complete, bool):
        raise ReconciliationError("complete must be a boolean")
    coverage = payload.get("coverage", "unknown")
    if coverage not in ("all_containers", "running_only", "unknown"):
        raise ReconciliationError("Invalid snapshot coverage")
    raw = payload.get("containers", [] if status == "failed" else None)
    if not isinstance(raw, list) or len(raw) > 5000:
        raise ReconciliationError("containers must be an array with at most 5000 entries")
    completed = timestamp(payload.get("completed_at"))
    age = (utc_now() - completed).total_seconds() if completed else None
    fresh = age is not None and 0 <= age <= MAX_AGE_SECONDS
    resources = []
    for row in raw:
        if not isinstance(row, dict):
            raise ReconciliationError("Each discovered container must be an object")
        # Accept the useful subset of Docker inspect without echoing environment,
        # mount paths, labels, credentials or arbitrary scanner payload fields.
        raw_name = row.get("container_name") or row.get("name") or row.get("Name")
        name = raw_name.strip().lstrip("/") if isinstance(raw_name, str) else ""
        if not name or len(name) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ReconciliationError("Each container requires a valid Docker name")
        config = row.get("Config") if isinstance(row.get("Config"), dict) else {}
        resources.append({"container_name": name, "container_key": normalize_identity(name),
                          "container_id": text(row.get("container_id") or row.get("Id")),
                          "image_id": text(row.get("image_id") or row.get("Image")),
                          "image": text(row.get("image") or config.get("Image")),
                          "observed_at": completed.isoformat() if completed else None})
    authoritative = status == "success" and complete and coverage == "all_containers" and fresh
    if authoritative:
        reason = "Successful complete all-container snapshot within 24 hours; absence is confirmed only for recorded Docker identities."
    elif status == "failed":
        reason = "Scan failed. No resource is confirmed absent and no changes can be applied."
    elif not fresh:
        reason = "Scan time is missing, future-dated or older than 24 hours; absence is unknown."
    else:
        reason = "Coverage is partial or not confirmed successful/complete; stopped or omitted containers may still exist."
    return {"status": status, "complete": complete, "coverage": coverage,
            "completed_at": completed.isoformat() if completed else None, "fresh": fresh,
            "authoritative": authoritative, "source": text(payload.get("source"), 80) or "operator snapshot",
            "reason": reason, "containers": resources}



def network_snapshot(state):
    """Read the actual /api/scanner/status/<scan_id> response, without polling it."""
    rows = state.get("results", [])
    if not isinstance(rows, list) or len(rows) > 5000 or not all(isinstance(row, dict) for row in rows):
        raise ReconciliationError("Scanner results must be an array of objects (maximum 5000)")
    kind = state.get("type", "unknown")
    if kind == "unknown" and rows:
        raise ReconciliationError("Expired scanner response cannot identify result types")
    status = state.get("status", "unknown")
    if status not in ("running", "completed", "failed", "expired", "unknown"):
        raise ReconciliationError("Unknown scanner job status")
    params = state.get("params") if isinstance(state.get("params"), dict) else {}
    clean = []
    for row in rows:
        item = {key: text(row.get(key), 200) for key in ("ip", "mac", "hostname", "mac_address", "os", "service_name", "service_version", "suggested_name")}
        if kind in ("portscan", "probe_http"):
            port = row.get("port", params.get("port"))
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ReconciliationError("Network service requires a valid TCP port")
            item["port"] = port
            probe = row.get("http_probe") if isinstance(row.get("http_probe"), dict) else row if kind == "probe_http" else {}
            item["suggested_name"] = text(probe.get("suggested_name"), 200)
            item["probe_failed"] = bool(probe.get("error"))
        clean.append(item)
    return {"status": "unknown", "complete": False, "coverage": "unknown", "completed_at": None,
            "source": "dpinna13/network-scanner@9feebd5", "containers": [], "fresh": False, "authoritative": False,
            "reason": "Network results contain hosts/ports, not Docker names or IDs. No container absence can be inferred. The status API also omits scan timestamps.",
            "network_scan": {"type": kind, "status": status, "target_ip": text(params.get("target_ip"), 64), "results": clean}}
