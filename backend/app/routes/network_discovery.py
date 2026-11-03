"""Authenticated start/status bridge for the separate network scanner."""
from flask import Blueprint, jsonify, request

from ..services.admin_auth import admin_required
from ..services.network_discovery import (
    NetworkDiscoveryBusy,
    NetworkDiscoveryError,
    NetworkDiscoveryNotFound,
    NetworkDiscoveryUnavailable,
    config_payload,
    scan_status,
    start_scan,
)
from ..services.network_wide_reconciliation import NetworkWideError, compare_network_wide
from ..services.unifi import (
    UnifiAuthError,
    UnifiError,
    UnifiResponseError,
    UnifiUnavailable,
    unifi_store,
)

bp = Blueprint("network_discovery", __name__, url_prefix="/api/network-discovery")


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise NetworkDiscoveryError("JSON object required")
    return data


@bp.get("/config")
def get_config():
    return jsonify(config_payload())


@bp.post("/scan")
@admin_required
def create_scan():
    try:
        data = _body()
        scan = start_scan(data.get("target"), data.get("scan_type"), data.get("ports"))
        return jsonify(scan=scan), 202
    except NetworkDiscoveryBusy as exc:
        return jsonify(error=str(exc)), 429
    except NetworkDiscoveryUnavailable as exc:
        return jsonify(error=str(exc)), 503
    except NetworkDiscoveryError as exc:
        return jsonify(error=str(exc)), 400


@bp.get("/scan/<scan_id>")
def get_scan(scan_id):
    try:
        return jsonify(scan=scan_status(scan_id))
    except NetworkDiscoveryNotFound as exc:
        return jsonify(error=str(exc)), 404
    except NetworkDiscoveryUnavailable as exc:
        return jsonify(error=str(exc)), 503
    except NetworkDiscoveryError as exc:
        return jsonify(error=str(exc)), 400


@bp.post("/reconcile")
@admin_required
def reconcile_network():
    """Read-only network-wide comparison; no root-host scope and no writes."""
    try:
        data = _body()
        scan = data.get("scan") if data.get("scan") is not None else data.get("snapshot")
        status = unifi_store.status()
        observations = unifi_store.observations() if status.get("configured") else []
        return jsonify(compare_network_wide(
            scan,
            unifi_observations=observations,
            unifi_status=status,
        ))
    except NetworkWideError as exc:
        return jsonify(error=str(exc)), 400
    except NetworkDiscoveryError as exc:
        return jsonify(error=str(exc)), 400


@bp.get("/unifi/status")
def unifi_status():
    """Expose only cache/status metadata; never controller credentials or raw responses."""
    return jsonify(unifi=unifi_store.status())


@bp.post("/unifi/refresh")
@admin_required
def unifi_refresh():
    """Explicit, admin-only read-only refresh of the UniFi observation cache."""
    try:
        return jsonify(unifi=unifi_store.refresh())
    except UnifiAuthError as exc:
        return jsonify(error=str(exc), unifi=unifi_store.status()), 502
    except UnifiUnavailable as exc:
        return jsonify(error=str(exc), unifi=unifi_store.status()), 503
    except UnifiResponseError as exc:
        return jsonify(error=str(exc), unifi=unifi_store.status()), 502
    except UnifiError as exc:
        return jsonify(error=str(exc), unifi=unifi_store.status()), 502
