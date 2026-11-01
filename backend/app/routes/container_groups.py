"""Container group management endpoints.

Read endpoints (effective grouping, management view) are public like the rest of
the inventory API. Mutating endpoints require ``HLH_ADMIN_TOKEN``; when it is not
configured, writes are disabled. FolderView source files are only ever read.
"""

import re
from collections import Counter

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..models import (
    AppService,
    ContainerGroup,
    ContainerGroupAssignment,
    ContainerGroupOverride,
    Hardware,
    db,
)
from ..services.admin_auth import admin_required
from ..services.folderview_import import FolderviewImportError, import_folderview_file
from ..services.group_identity import (
    app_identity,
    app_identities,
    display_identity,
    normalize_identity,
)
from ..services.group_resolution import effective_group

bp = Blueprint("container_groups", __name__, url_prefix="/api/container-groups")

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_ICON_LENGTH = 100_000


class ValidationError(ValueError):
    """Raised for invalid management input."""


def _error(message, status=400):
    return jsonify(error=message), status


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("A JSON object body is required")
    return data


def _clean_name(value):
    if not isinstance(value, str):
        raise ValidationError("Group name must be a string")
    name = display_identity(value)
    if not name or len(name) > 80:
        raise ValidationError("Group name must be between 1 and 80 characters")
    return name


def _clean_color(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not COLOR_RE.match(value.strip()):
        raise ValidationError("Colour must be a #rrggbb value")
    return value.strip().lower()


def _clean_icon(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValidationError("Icon must be a string")
    icon = value.strip()
    if len(icon) > MAX_ICON_LENGTH:
        raise ValidationError("Icon value is too long")
    return icon or None


def _clean_sort_order(value):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("sort_order must be an integer")
    if value < -100000 or value > 100000:
        raise ValidationError("sort_order is out of range")
    return value


def _clean_bool(value, field):
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean")
    return value


def _host_labels(session):
    labels = {}
    for hardware in session.query(Hardware).all():
        key = normalize_identity(hardware.name)
        if key:
            labels[key] = display_identity(hardware.name)
    for app in app_identities(session):
        key = app["host_key"]
        if key and key not in labels:
            labels[key] = app["host_label"] or key
    for group in session.query(ContainerGroup).all():
        if group.host_key and group.host_key not in labels:
            labels[group.host_key] = group.host_key
    return labels


def _name_conflict(session, host_key, name, exclude_id=None):
    target = normalize_identity(name)
    for group in (
        session.query(ContainerGroup).filter_by(host_key=host_key).all()
    ):
        if group.id != exclude_id and normalize_identity(group.name) == target:
            return group
    return None


def _serialise_group(group, counts=None):
    data = {
        "id": group.id,
        "name": group.name,
        "source": group.source,
        "host_key": group.host_key,
        "external_id": group.external_id,
        "external_parent_id": group.external_parent_id,
        "color": group.color,
        "icon": group.icon,
        "sort_order": group.sort_order,
        "active": bool(group.active),
    }
    if counts:
        data.update(counts)
    return data


def _effective_map(session):
    """Return ``{(host_key, container_key): {group, match, labels}}``."""
    effective = {}
    for assignment in session.query(ContainerGroupAssignment).all():
        group = assignment.group
        if group is None or not group.active:
            continue
        effective[(assignment.host_key, assignment.container_key)] = {
            "group": group,
            "match": "assignment",
            "host_label": assignment.host_label,
            "container_label": assignment.container_label,
        }
    for override in session.query(ContainerGroupOverride).all():
        key = (override.host_key, override.container_key)
        if override.group_id is None:
            effective.pop(key, None)
            continue
        group = override.group
        if group is None or not group.active:
            effective.pop(key, None)
            continue
        effective[key] = {
            "group": group,
            "match": "override",
            "host_label": override.host_label,
            "container_label": override.container_label,
        }
    return effective


@bp.route("/effective", methods=["GET"])
def get_effective_groups():
    """Return active groups and their effective, host-scoped memberships."""
    apps = app_identities(db.session)
    app_index = {}
    for app in apps:
        app_index.setdefault((app["host_key"], app["container_key"]), app["app_id"])
    host_labels = {app["host_key"]: app["host_label"] for app in apps if app["host_label"]}

    groups = (
        db.session.query(ContainerGroup)
        .filter(ContainerGroup.active.is_(True))
        .order_by(ContainerGroup.sort_order, ContainerGroup.name, ContainerGroup.id)
        .all()
    )
    effective = _effective_map(db.session)

    memberships = []
    unmatched = []
    for (host_key, container_key), info in sorted(effective.items()):
        app_id = app_index.get((host_key, container_key))
        entry = {
            "group_id": info["group"].id,
            "host_key": host_key,
            "host_label": info["host_label"] or host_labels.get(host_key, ""),
            "container_key": container_key,
            "container_label": info["container_label"] or container_key,
            "app_id": app_id,
            "match": info["match"],
        }
        (memberships if app_id is not None else unmatched).append(entry)

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


@bp.route("/management", methods=["GET"])
def get_management_view():
    """Read-only data used by the Container Groups management page."""
    session = db.session
    apps = app_identities(session)
    app_index = {}
    for app in apps:
        app_index.setdefault((app["host_key"], app["container_key"]), app["app_id"])

    assignments = {
        (item.host_key, item.container_key): item
        for item in session.query(ContainerGroupAssignment).all()
    }
    overrides = {
        (item.host_key, item.container_key): item
        for item in session.query(ContainerGroupOverride).all()
    }
    effective = _effective_map(session)
    groups = session.query(ContainerGroup).all()

    assignment_counts = Counter(item.group_id for item in assignments.values())
    override_counts = Counter(
        item.group_id for item in overrides.values() if item.group_id is not None
    )
    unmatched_counts = Counter(
        info["group"].id
        for key, info in effective.items()
        if key not in app_index
    )

    group_rows = [
        _serialise_group(
            group,
            {
                "assignment_count": assignment_counts.get(group.id, 0),
                "override_count": override_counts.get(group.id, 0),
                "unmatched_count": unmatched_counts.get(group.id, 0),
            },
        )
        for group in sorted(
            groups,
            key=lambda item: (
                item.host_key or "",
                item.source,
                item.sort_order or 0,
                normalize_identity(item.name),
                item.id,
            ),
        )
    ]

    app_rows = []
    for app in sorted(
        apps,
        key=lambda item: (
            item["host_key"],
            normalize_identity(item["name"]),
            item["container_key"],
            item["app_id"],
        ),
    ):
        key = (app["host_key"], app["container_key"])
        info = effective.get(key)
        assignment = assignments.get(key)
        override = overrides.get(key)
        app_rows.append(
            {
                "app_id": app["app_id"],
                "name": app["name"],
                "host_key": app["host_key"],
                "host_label": app["host_label"],
                "container_key": app["container_key"],
                "container_label": app["container_label"],
                "group_id": info["group"].id if info else None,
                "group_name": info["group"].name if info else None,
                "match": info["match"] if info else ("override" if override else None),
                "override": override is not None,
                "explicit_ungrouped": bool(override is not None and override.group_id is None),
                "imported_group_id": assignment.group_id if assignment else None,
                "imported_group_name": assignment.group.name if assignment else None,
            }
        )

    unmatched_rows = [
        {
            "group_id": info["group"].id,
            "group_name": info["group"].name,
            "host_key": key[0],
            "host_label": info["host_label"] or "",
            "container_key": key[1],
            "container_label": info["container_label"] or key[1],
            "match": info["match"],
        }
        for key, info in sorted(effective.items())
        if key not in app_index
    ]

    labels = _host_labels(session)
    hosts = [{"key": key, "label": label} for key, label in labels.items()]
    if any(app["host_key"] == "" for app in apps):
        hosts.append({"key": "", "label": "No host"})
    hosts.sort(key=lambda item: item["label"].casefold())

    return jsonify(
        {
            "hosts": hosts,
            "groups": group_rows,
            "apps": app_rows,
            "unmatched": unmatched_rows,
        }
    )


@bp.route("", methods=["POST"])
@admin_required
def create_group():
    try:
        data = _json_body()
        session = db.session
        host_key = normalize_identity(data.get("host_key"))
        labels = _host_labels(session)
        if not host_key or host_key not in labels:
            raise ValidationError("host_key must reference a known host")
        name = _clean_name(data.get("name"))
        if _name_conflict(session, host_key, name):
            return _error("A group with this name already exists for this host", 409)
        group = ContainerGroup(
            name=name,
            source="manual",
            host_key=host_key,
            color=_clean_color(data.get("color")),
            icon=_clean_icon(data.get("icon")),
            sort_order=_clean_sort_order(data.get("sort_order")),
            active=True,
        )
        session.add(group)
        session.commit()
    except ValidationError as exc:
        session.rollback()
        return _error(str(exc))
    except IntegrityError:
        session.rollback()
        return _error("Could not create the group", 409)
    return jsonify(data=_serialise_group(group)), 201


@bp.route("/<int:group_id>", methods=["PUT"])
@admin_required
def update_group(group_id):
    session = db.session
    group = session.get(ContainerGroup, group_id)
    if group is None:
        return _error("Group not found", 404)
    try:
        data = _json_body()
        if "name" in data:
            name = _clean_name(data.get("name"))
            if group.source != "manual" and normalize_identity(name) != normalize_identity(group.name):
                return _error("Imported group names are managed by FolderView", 400)
            if _name_conflict(session, group.host_key, name, exclude_id=group.id):
                return _error("A group with this name already exists for this host", 409)
            group.name = name
        if "color" in data:
            group.color = _clean_color(data.get("color"))
        if "icon" in data:
            group.icon = _clean_icon(data.get("icon"))
        if "sort_order" in data:
            group.sort_order = _clean_sort_order(data.get("sort_order"))
        if "active" in data:
            group.active = _clean_bool(data.get("active"), "active")
        session.commit()
    except ValidationError as exc:
        session.rollback()
        return _error(str(exc))
    except IntegrityError:
        session.rollback()
        return _error("Could not update the group", 409)
    return jsonify(data=_serialise_group(group))


@bp.route("/<int:group_id>", methods=["DELETE"])
@admin_required
def delete_group(group_id):
    session = db.session
    group = session.get(ContainerGroup, group_id)
    if group is None:
        return _error("Group not found", 404)
    if group.source != "manual":
        return _error("Imported groups can be archived but not deleted", 409)
    assignments = (
        session.query(ContainerGroupAssignment)
        .filter_by(group_id=group.id)
        .count()
    )
    overrides = (
        session.query(ContainerGroupOverride)
        .filter_by(group_id=group.id)
        .count()
    )
    if assignments or overrides:
        return _error("Group has assignments; archive it instead", 409)
    session.delete(group)
    session.commit()
    return jsonify(message="Group deleted")


def _resolve_assignment_identity(session, data):
    app_id = data.get("app_id")
    if app_id is not None:
        if isinstance(app_id, bool) or not isinstance(app_id, int):
            raise ValidationError("app_id must be an integer")
        app = session.get(AppService, app_id)
        if app is None:
            raise ValidationError("Application not found")
        host_key, host_label, container_key, container_label = app_identity(app)
        return {
            "app_id": app.id,
            "host_key": host_key,
            "host_label": host_label,
            "container_key": container_key,
            "container_label": container_label,
            "name": display_identity(app.name),
        }

    host_key = normalize_identity(data.get("host_key"))
    container_key = normalize_identity(data.get("container_key"))
    if not host_key or not container_key:
        raise ValidationError("app_id or host_key and container_key are required")
    host_label = display_identity(data.get("host_label")) or _host_labels(session).get(host_key, "")
    container_label = display_identity(data.get("container_label")) or container_key
    app_id = None
    for app in app_identities(session):
        if app["host_key"] == host_key and app["container_key"] == container_key:
            app_id = app["app_id"]
            host_label = app["host_label"] or host_label
            container_label = app["container_label"] or container_label
            break
    return {
        "app_id": app_id,
        "host_key": host_key,
        "host_label": host_label,
        "container_key": container_key,
        "container_label": container_label,
        "name": container_label,
    }


@bp.route("/assignments", methods=["PUT"])
@admin_required
def set_assignment():
    session = db.session
    try:
        data = _json_body()
        identity = _resolve_assignment_identity(session, data)
        group_id = data.get("group_id")
        group = None
        if group_id is not None:
            if isinstance(group_id, bool) or not isinstance(group_id, int):
                raise ValidationError("group_id must be an integer or null")
            group = session.get(ContainerGroup, group_id)
            if group is None:
                raise ValidationError("Group not found")
            if not group.active:
                raise ValidationError("Cannot assign to an archived group")
            if group.host_key and group.host_key != identity["host_key"]:
                raise ValidationError("Group belongs to a different host")

        override = (
            session.query(ContainerGroupOverride)
            .filter_by(
                host_key=identity["host_key"],
                container_key=identity["container_key"],
            )
            .first()
        )
        if override is None:
            override = ContainerGroupOverride(
                host_key=identity["host_key"],
                container_key=identity["container_key"],
            )
            session.add(override)
        override.host_label = identity["host_label"] or None
        override.container_label = identity["container_label"] or None
        override.group = group
        session.commit()
    except ValidationError as exc:
        session.rollback()
        return _error(str(exc))
    except IntegrityError:
        session.rollback()
        return _error("Could not save the assignment", 409)

    effective = effective_group(
        session, identity["host_key"], identity["container_key"]
    )
    return jsonify(
        message="Assignment saved",
        data={
            "host_key": identity["host_key"],
            "host_label": identity["host_label"],
            "container_key": identity["container_key"],
            "container_label": identity["container_label"],
            "group_id": effective.id if effective else None,
            "group_name": effective.name if effective else None,
            "match": "ungrouped" if group is None else "override",
        },
    )


@bp.route("/assignments", methods=["DELETE"])
@admin_required
def revert_assignment():
    session = db.session
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    data = {
        **data,
        **{
            key: request.args.get(key)
            for key in ("app_id", "host_key", "container_key")
            if request.args.get(key) is not None
        },
    }
    try:
        identity = _resolve_assignment_identity(session, data)
    except ValidationError as exc:
        return _error(str(exc))

    override = (
        session.query(ContainerGroupOverride)
        .filter_by(
            host_key=identity["host_key"],
            container_key=identity["container_key"],
        )
        .first()
    )
    reverted = override is not None
    if reverted:
        session.delete(override)
        session.commit()

    effective = effective_group(
        session, identity["host_key"], identity["container_key"]
    )
    return jsonify(
        message="Reverted to imported assignment" if reverted else "No manual override to revert",
        reverted=reverted,
        data={
            "host_key": identity["host_key"],
            "container_key": identity["container_key"],
            "group_id": effective.id if effective else None,
            "group_name": effective.name if effective else None,
        },
    )


@bp.route("/sync", methods=["POST"])
@admin_required
def sync_folderview():
    session = db.session
    try:
        data = _json_body()
        host_key = normalize_identity(data.get("host_key"))
        labels = _host_labels(session)
        if not host_key or host_key not in labels:
            raise ValidationError("host_key must reference a known host")
        dry_run = data.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise ValidationError("dry_run must be a boolean")
        path = current_app.config.get("FOLDERVIEW_CONFIG_PATH")
        if not path:
            return _error(
                "FOLDERVIEW_CONFIG_PATH is not configured; mount the FolderView "
                "configuration read-only and set the environment variable",
                503,
            )
        report = import_folderview_file(
            path,
            host_key=host_key,
            host_label=labels[host_key],
            dry_run=dry_run,
        )
    except ValidationError as exc:
        return _error(str(exc))
    except FolderviewImportError as exc:
        return _error(str(exc))
    return jsonify(report)
