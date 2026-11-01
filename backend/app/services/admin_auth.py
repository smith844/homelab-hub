"""Configurable administrative access for management endpoints.

HomeLab-Hub's inventory APIs are read-mostly and currently unauthenticated. Any
database-mutating management endpoint is protected by a token configured with
``HLH_ADMIN_TOKEN`` (or ``ADMIN_TOKEN``) and sent as ``X-Admin-Token`` (or a
Bearer token). When no token is configured, management writes are disabled.
"""

import hmac
from functools import wraps

from flask import current_app, jsonify, request


def configured_token():
    value = current_app.config.get("ADMIN_TOKEN")
    if value is None:
        value = current_app.config.get("HLH_ADMIN_TOKEN")
    return (value or "").strip()


def request_token():
    token = request.headers.get("X-Admin-Token", "").strip()
    if token:
        return token
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        token = configured_token()
        if not token:
            return (
                jsonify(
                    error=(
                        "Administrative management is disabled; configure "
                        "HLH_ADMIN_TOKEN to enable writes"
                    )
                ),
                503,
            )
        provided = request_token()
        if not provided or not hmac.compare_digest(provided, token):
            return jsonify(error="A valid administrative token is required"), 401
        return view(*args, **kwargs)

    return wrapped
