"""Read-only comparisons and short-lived, admin-protected reviewed changes."""
import secrets
from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ..models import Hardware, db
from ..services.admin_auth import admin_required
from ..services.group_identity import normalize_identity
from ..services.reconciliation import ReconciliationError, compare, execute_action, fingerprint, plan_action
from ..services.discovery_adapters import MAX_AGE_SECONDS, timestamp, utc_now

bp = Blueprint("reconciliation", __name__, url_prefix="/api/reconciliation")


def signer():
    # Process-local key: previews intentionally expire on restart, not inventory data.
    if "reconciliation_signer" not in current_app.extensions:
        current_app.extensions["reconciliation_signer"] = URLSafeTimedSerializer(secrets.token_bytes(32), salt="hlh-reconciliation-v1")
    return current_app.extensions["reconciliation_signer"]


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ReconciliationError("JSON object required")
    return data


@bp.get("")
def index():
    hosts = [{"key": normalize_identity(h.name), "name": h.name} for h in Hardware.query.order_by(Hardware.name)]
    key = normalize_identity(request.args.get("host_key"))
    try:
        return jsonify(hosts=hosts, report=compare(key) if key else None)
    except ReconciliationError as exc:
        return jsonify(error=str(exc)), 400


@bp.post("/compare")
def comparison():
    try:
        data = body()
        return jsonify(compare(normalize_identity(data.get("host_key")), data.get("snapshot")))
    except ReconciliationError as exc:
        return jsonify(error=str(exc)), 400


@bp.post("/preview")
def preview():
    try:
        data = body()
        plan = plan_action(normalize_identity(data.get("host_key")), data.get("snapshot"), data.get("action"))
        return jsonify(plan=plan, token=signer().dumps(plan), expires_in=600)
    except ReconciliationError as exc:
        return jsonify(error=str(exc)), 400


@bp.post("/apply")
@admin_required
def apply():
    try:
        data = body()
        if not isinstance(data.get("token"), str):
            raise ReconciliationError("A reviewed preview token is required")
        plan = signer().loads(data["token"], max_age=600)
        # Serialize SQLite writes so the state check and mutation cannot race.
        if db.engine.dialect.name == "sqlite":
            db.session.execute(text("BEGIN IMMEDIATE"))
        if fingerprint(plan["host_key"]) != plan["fingerprint"]:
            db.session.rollback()
            return jsonify(error="Inventory or grouping changed; compare and preview again"), 409
        completed = timestamp(plan["resource"].get("observed_at"))
        if completed is None or not 0 <= (utc_now() - completed).total_seconds() <= MAX_AGE_SECONDS:
            raise ReconciliationError("Snapshot is no longer recent; compare again")
        app_id = execute_action(plan)
        db.session.commit()
        return jsonify(app_id=app_id, message="Reviewed change applied; no inventory records deleted")
    except BadData:
        db.session.rollback()
        return jsonify(error="Preview is invalid, expired or from a previous server session; preview again"), 409
    except ReconciliationError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    except OperationalError:
        db.session.rollback()
        return jsonify(error="Inventory is busy; retry comparison and preview"), 409
