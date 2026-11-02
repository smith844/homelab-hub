"""Authenticated start/status bridge for the separate network scanner."""
from flask import Blueprint, jsonify, request

from ..services.admin_auth import admin_required
from ..services.network_discovery import (
    NetworkDiscoveryBusy,
    NetworkDiscoveryError,
    NetworkDiscoveryUnavailable,
    config_payload,
    scan_status,
    start_scan,
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
    except NetworkDiscoveryUnavailable as exc:
        return jsonify(error=str(exc)), 503
    except NetworkDiscoveryError as exc:
        return jsonify(error=str(exc)), 400
