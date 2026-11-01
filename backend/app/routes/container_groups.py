"""Read-only container grouping endpoints for map/inventory presentation."""

from flask import Blueprint, jsonify

from ..models import (
    ContainerGroup,
    ContainerGroupAssignment,
    ContainerGroupOverride,
    db,
)
from ..services.group_identity import app_identities

bp = Blueprint("container_groups", __name__, url_prefix="/api/container-groups")


def _serialise_group(group):
    return {
        "id": group.id,
        "name": group.name,
        "source": group.source,
        "host_key": group.host_key,
        "color": group.color,
        "icon": group.icon,
        "sort_order": group.sort_order,
    }


@bp.route("/effective", methods=["GET"])
def get_effective_groups():
    """Return active groups and their effective, host-scoped memberships.

    Read-only: overrides win over imported assignments, archived groups never
    produce a membership, and unmatched assignments are reported separately.
    """
    apps = app_identities(db.session)
    app_index = {}
    for app in apps:
        app_index.setdefault(
            (app["host_key"], app["container_key"]), app["app_id"]
        )
    host_labels = {app["host_key"]: app["host_label"] for app in apps if app["host_label"]}

    groups = (
        db.session.query(ContainerGroup)
        .filter(ContainerGroup.active.is_(True))
        .order_by(ContainerGroup.sort_order, ContainerGroup.name, ContainerGroup.id)
        .all()
    )

    # Effective membership: imported assignment, then manual override.
    effective = {}
    for assignment in db.session.query(ContainerGroupAssignment).all():
        group = assignment.group
        if group is None or not group.active:
            continue
        effective[(assignment.host_key, assignment.container_key)] = {
            "group_id": group.id,
            "match": "assignment",
            "host_label": assignment.host_label,
            "container_label": assignment.container_label,
        }
    for override in db.session.query(ContainerGroupOverride).all():
        key = (override.host_key, override.container_key)
        if override.group_id is None:
            effective.pop(key, None)
            continue
        group = override.group
        if group is None or not group.active:
            effective.pop(key, None)
            continue
        effective[key] = {
            "group_id": group.id,
            "match": "override",
            "host_label": override.host_label,
            "container_label": override.container_label,
        }

    memberships = []
    unmatched = []
    for (host_key, container_key), info in sorted(effective.items()):
        app_id = app_index.get((host_key, container_key))
        entry = {
            "group_id": info["group_id"],
            "host_key": host_key,
            "host_label": info["host_label"] or host_labels.get(host_key, ""),
            "container_key": container_key,
            "container_label": info["container_label"] or container_key,
            "app_id": app_id,
            "match": info["match"],
        }
        if app_id is None:
            unmatched.append(entry)
        else:
            memberships.append(entry)

    ungrouped_apps = []
    for app in sorted(apps, key=lambda item: (item["host_key"], item["app_id"])):
        key = (app["host_key"], app["container_key"])
        if key in effective:
            continue
        ungrouped_apps.append(
            {
                "app_id": app["app_id"],
                "host_key": app["host_key"],
                "host_label": app["host_label"],
            }
        )

    return jsonify(
        {
            "groups": [_serialise_group(group) for group in groups],
            "memberships": memberships,
            "unmatched": unmatched,
            "ungrouped_apps": ungrouped_apps,
            "unmatched_count": len(unmatched),
        }
    )
