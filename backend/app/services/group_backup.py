"""Natural-key backup/restore for container grouping data.

Backups use stable identities (source + host + FolderView folder id, or the
normalised manual group name) rather than database ids, so they restore cleanly
into a database whose primary keys have changed.
"""

import json

from ..models import (
    ContainerGroup,
    ContainerGroupAssignment,
    ContainerGroupOverride,
)
from .group_identity import display_identity, normalize_identity

GROUP_BACKUP_KEYS = (
    "container_groups",
    "container_group_assignments",
    "container_group_overrides",
)


def group_natural_key(group):
    if group.external_id:
        return f"{group.source}:{group.host_key or ''}:{group.external_id}"
    return f"manual:{normalize_identity(group.name)}"


def has_group_backup_data(payload):
    return isinstance(payload, dict) and any(key in payload for key in GROUP_BACKUP_KEYS)


def _metadata_to_json(value):
    return None if value is None else json.loads(value)


def _metadata_from_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def export_group_data(session):
    """Return group data serialised with natural keys (no database ids)."""
    groups = (
        session.query(ContainerGroup)
        .order_by(
            ContainerGroup.source,
            ContainerGroup.host_key,
            ContainerGroup.external_id,
            ContainerGroup.name,
        )
        .all()
    )

    key_by_id = {}
    seen_keys = set()
    exported_groups = []
    for group in groups:
        key = group_natural_key(group)
        if key in seen_keys:
            raise ValueError(
                f"Duplicate container group natural key {key!r}; "
                "rename manual groups so their names are unique"
            )
        seen_keys.add(key)
        key_by_id[group.id] = key
        exported_groups.append(
            {
                "key": key,
                "name": group.name,
                "source": group.source,
                "host_key": group.host_key,
                "external_id": group.external_id,
                "external_parent_id": group.external_parent_id,
                "icon": group.icon,
                "color": group.color,
                "sort_order": group.sort_order,
                "active": bool(group.active),
                "metadata": _metadata_to_json(group.metadata_json),
            }
        )

    exported_assignments = [
        {
            "group_key": key_by_id.get(assignment.group_id),
            "host_key": assignment.host_key,
            "host_label": assignment.host_label,
            "container_key": assignment.container_key,
            "container_label": assignment.container_label,
            "metadata": _metadata_to_json(assignment.metadata_json),
        }
        for assignment in session.query(ContainerGroupAssignment)
        .order_by(
            ContainerGroupAssignment.host_key,
            ContainerGroupAssignment.container_key,
        )
        .all()
    ]

    exported_overrides = [
        {
            "group_key": key_by_id.get(override.group_id),
            "host_key": override.host_key,
            "host_label": override.host_label,
            "container_key": override.container_key,
            "container_label": override.container_label,
            "note": override.note,
        }
        for override in session.query(ContainerGroupOverride)
        .order_by(
            ContainerGroupOverride.host_key,
            ContainerGroupOverride.container_key,
        )
        .all()
    ]

    return {
        "container_groups": exported_groups,
        "container_group_assignments": exported_assignments,
        "container_group_overrides": exported_overrides,
    }


def import_group_data(session, payload):
    """Replace all grouping data from a natural-key backup payload.

    Raises ``ValueError`` for malformed payloads. The caller owns the
    transaction; SQLite foreign keys are not enforced so rows are removed in
    dependency order explicitly.
    """
    if not isinstance(payload, dict):
        raise ValueError("Container group backup data must be an object")

    groups_payload = payload.get("container_groups") or []
    assignments_payload = payload.get("container_group_assignments") or []
    overrides_payload = payload.get("container_group_overrides") or []
    if not isinstance(groups_payload, list) or not isinstance(assignments_payload, list) or not isinstance(overrides_payload, list):
        raise ValueError("Container group backup lists must be arrays")

    session.query(ContainerGroupOverride).delete()
    session.query(ContainerGroupAssignment).delete()
    session.query(ContainerGroup).delete()
    session.flush()

    key_to_group = {}
    for entry in groups_payload:
        if not isinstance(entry, dict):
            raise ValueError("Container group entries must be objects")
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError("Container group entries require a non-empty string 'key'")
        if key in key_to_group:
            raise ValueError(f"Duplicate container group key {key!r}")
        name = display_identity(entry.get("name"))
        if not name:
            raise ValueError(f"Container group {key!r} requires a name")
        group = ContainerGroup(
            name=name,
            source=entry.get("source") or "manual",
            host_key=normalize_identity(entry.get("host_key")),
            external_id=entry.get("external_id"),
            external_parent_id=entry.get("external_parent_id"),
            icon=entry.get("icon"),
            color=entry.get("color"),
            sort_order=entry.get("sort_order") or 0,
            active=bool(entry.get("active", True)),
            metadata_json=_metadata_from_json(entry.get("metadata")),
        )
        session.add(group)
        key_to_group[key] = group
    session.flush()

    seen_containers = set()
    for entry in assignments_payload:
        if not isinstance(entry, dict):
            raise ValueError("Container group assignment entries must be objects")
        group_key = entry.get("group_key")
        group = key_to_group.get(group_key)
        if group is None:
            raise ValueError(
                f"Container group assignment references unknown group key {group_key!r}"
            )
        host_key = normalize_identity(entry.get("host_key"))
        container_key = normalize_identity(entry.get("container_key"))
        if not host_key or not container_key:
            raise ValueError("Container group assignments require host_key and container_key")
        identity = (host_key, container_key)
        if identity in seen_containers:
            raise ValueError(
                f"Duplicate container group assignment for {host_key!r}/{container_key!r}"
            )
        seen_containers.add(identity)
        session.add(
            ContainerGroupAssignment(
                group=group,
                host_key=host_key,
                host_label=display_identity(entry.get("host_label")) or None,
                container_key=container_key,
                container_label=display_identity(entry.get("container_label")) or None,
                metadata_json=_metadata_from_json(entry.get("metadata")),
            )
        )

    seen_overrides = set()
    for entry in overrides_payload:
        if not isinstance(entry, dict):
            raise ValueError("Container group override entries must be objects")
        group_key = entry.get("group_key")
        group = key_to_group.get(group_key) if group_key is not None else None
        if group_key is not None and group is None:
            raise ValueError(
                f"Container group override references unknown group key {group_key!r}"
            )
        host_key = normalize_identity(entry.get("host_key"))
        container_key = normalize_identity(entry.get("container_key"))
        if not host_key or not container_key:
            raise ValueError("Container group overrides require host_key and container_key")
        identity = (host_key, container_key)
        if identity in seen_overrides:
            raise ValueError(
                f"Duplicate container group override for {host_key!r}/{container_key!r}"
            )
        seen_overrides.add(identity)
        session.add(
            ContainerGroupOverride(
                group=group,
                host_key=host_key,
                host_label=display_identity(entry.get("host_label")) or None,
                container_key=container_key,
                container_label=display_identity(entry.get("container_label")) or None,
                note=entry.get("note"),
            )
        )

    session.flush()
    return {
        "groups": len(key_to_group),
        "assignments": len(assignments_payload),
        "overrides": len(overrides_payload),
    }
