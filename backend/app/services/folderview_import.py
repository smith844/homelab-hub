"""Read-only FolderView Plus (Unraid) import.

The parser and sync planner operate on a normalised in-memory representation of
``/boot/config/plugins/folderview.plus/docker.json``. Nothing here writes to the
source file: ``import_folderview_file`` only ever opens it for reading.
"""

import json

from ..models import (
    db,
    ContainerGroup,
    ContainerGroupAssignment,
    ContainerGroupOverride,
)
from .group_identity import (
    app_identities,
    display_identity,
    host_candidates,
    matching_hosts,
    normalize_identity,
)

SOURCE = "folderview"
MAX_CONFIG_BYTES = 5 * 1024 * 1024

_GROUP_ACTION_COUNTS = {
    "create": "created",
    "update": "updated",
    "reactivate": "reactivated",
    "unchanged": "unchanged",
}
_ASSIGNMENT_ACTION_COUNTS = {
    "add": "added",
    "move": "moved",
    "remove": "removed",
    "unchanged": "unchanged",
}


class FolderviewImportError(ValueError):
    """Raised when a FolderView Plus configuration cannot be imported."""


def _normalise_icon(value):
    if not isinstance(value, str):
        return None
    return display_identity(value) or None


def parse_folderview_config(data):
    """Validate and normalise a FolderView Plus ``docker.json`` payload.

    Returns a dict with ``folders``, ``warnings`` and ``conflicts``. Folder ids
    are iterated in sorted order for deterministic results.
    """
    if not isinstance(data, dict):
        raise FolderviewImportError(
            "FolderView configuration must be a JSON object keyed by folder id"
        )

    warnings = []
    folders = []
    folder_ids = sorted(data.keys(), key=lambda value: str(value))

    for sort_order, raw_folder_id in enumerate(folder_ids):
        external_id = str(raw_folder_id)
        raw_folder = data[raw_folder_id]
        if not isinstance(raw_folder, dict):
            raise FolderviewImportError(f"Folder {external_id!r} must be an object")

        name = raw_folder.get("name")
        if name is None or not str(name).strip():
            warnings.append(f"Folder {external_id!r} has no name; using the folder id")
            name = external_id
        elif not isinstance(name, str):
            warnings.append(f"Folder {external_id!r} name is not a string; using its text form")
            name = display_identity(name) or external_id
        else:
            name = display_identity(name) or external_id

        parent_id = raw_folder.get("parentId", "")
        if parent_id is None:
            parent_id = ""
        elif not isinstance(parent_id, str):
            warnings.append(f"Folder {external_id!r} parentId is not a string; using its text form")
            parent_id = str(parent_id)

        raw_containers = raw_folder.get("containers", [])
        if raw_containers is None:
            raw_containers = []
            warnings.append(f"Folder {external_id!r} has no containers array")
        if not isinstance(raw_containers, list):
            raise FolderviewImportError(
                f"Folder {external_id!r} containers must be an array"
            )

        containers = []
        seen_keys = set()
        for raw_container in raw_containers:
            if not isinstance(raw_container, str):
                warnings.append(
                    f"Folder {external_id!r} has a non-string container entry; skipping it"
                )
                continue
            container_key = normalize_identity(raw_container)
            container_label = display_identity(raw_container)
            if not container_key:
                warnings.append(
                    f"Folder {external_id!r} has an empty container name; skipping it"
                )
                continue
            if container_key in seen_keys:
                warnings.append(
                    f"Folder {external_id!r} lists {container_label!r} more than once"
                )
                continue
            seen_keys.add(container_key)
            containers.append({"key": container_key, "label": container_label})

        folders.append(
            {
                "external_id": external_id,
                "name": name,
                "parent_id": parent_id,
                "icon": _normalise_icon(raw_folder.get("icon")),
                "sort_order": sort_order,
                # Preserve the source object exactly (regex, settings, actions,
                # memberIdentities, timestamps, ...). Regex rules are never run.
                "metadata": raw_folder,
                "containers": containers,
            }
        )

    # A container listed in more than one folder keeps the first folder in sorted
    # id order; the conflict is reported instead of silently dropping entries.
    owner = {}
    conflicts = []
    for folder in folders:
        for container in folder["containers"]:
            key = container["key"]
            if key in owner:
                conflicts.append(
                    {
                        "container_key": key,
                        "container_label": container["label"],
                        "kept_folder_id": owner[key],
                        "other_folder_id": folder["external_id"],
                    }
                )
            else:
                owner[key] = folder["external_id"]

    return {"folders": folders, "warnings": warnings, "conflicts": conflicts}


def normalize_host(host_key=None, host_label=None):
    """Return ``(normalized_host_key, display_label)`` for an import request."""
    key_source = host_key if host_key is not None else host_label
    label_source = host_label if host_label is not None else host_key
    key = normalize_identity(key_source)
    if not key:
        raise FolderviewImportError("A host name is required to scope imported containers")
    return key, display_identity(label_source) or display_identity(key_source)


def _folder_payload(folder):
    return {
        "name": folder["name"],
        "external_parent_id": folder["parent_id"],
        "icon": folder["icon"],
        "sort_order": folder["sort_order"],
        "metadata_json": json.dumps(folder["metadata"], sort_keys=True),
    }


def _group_matches(group, folder):
    payload = _folder_payload(folder)
    return (
        group.name == payload["name"]
        and (group.external_parent_id or "") == (payload["external_parent_id"] or "")
        and (group.icon or None) == payload["icon"]
        and group.sort_order == payload["sort_order"]
        and (group.metadata_json or "") == payload["metadata_json"]
    )


def build_import_plan(session, parsed, host_key, host_label):
    """Read current state and build the exact change set for an import."""
    folders = parsed["folders"]
    incoming_ids = {folder["external_id"] for folder in folders}

    imported_groups = (
        session.query(ContainerGroup)
        .filter_by(source=SOURCE, host_key=host_key)
        .all()
    )
    existing_by_external = {
        group.external_id: group
        for group in imported_groups
        if group.external_id is not None
    }

    group_changes = []
    for folder in folders:
        group = existing_by_external.get(folder["external_id"])
        if group is None:
            action = "create"
        elif not group.active:
            action = "reactivate"
        elif _group_matches(group, folder):
            action = "unchanged"
        else:
            action = "update"
        group_changes.append({"action": action, "folder": folder, "group": group})

    archive_changes = [
        {"action": "archive", "group": group}
        for external_id, group in existing_by_external.items()
        if external_id not in incoming_ids and group.active
    ]

    # Desired membership: first folder in sorted order wins (parser order).
    desired = {}
    for folder in folders:
        for container in folder["containers"]:
            desired.setdefault(
                container["key"],
                {"folder_id": folder["external_id"], "label": container["label"]},
            )

    existing_assignments = {
        assignment.container_key: assignment
        for assignment in session.query(ContainerGroupAssignment)
        .filter_by(host_key=host_key)
        .all()
    }
    group_by_id = {group.id: group for group in imported_groups}

    assignment_changes = []
    for container_key, wanted in desired.items():
        assignment = existing_assignments.get(container_key)
        if assignment is None:
            assignment_changes.append(
                {
                    "action": "add",
                    "container_key": container_key,
                    "folder_id": wanted["folder_id"],
                    "label": wanted["label"],
                }
            )
            continue
        current_group = group_by_id.get(assignment.group_id)
        current_external = current_group.external_id if current_group is not None else None
        if current_external == wanted["folder_id"]:
            assignment_changes.append(
                {"action": "unchanged", "assignment": assignment, "label": wanted["label"]}
            )
        else:
            assignment_changes.append(
                {
                    "action": "move",
                    "assignment": assignment,
                    "folder_id": wanted["folder_id"],
                    "label": wanted["label"],
                }
            )

    for container_key, assignment in existing_assignments.items():
        if container_key in desired:
            continue
        current_group = group_by_id.get(assignment.group_id)
        # Keep history for groups that are being archived (folder removed from
        # the source). Active imported groups lose members that were removed.
        if current_group is None or current_group.external_id in incoming_ids:
            assignment_changes.append({"action": "remove", "assignment": assignment})

    overrides = (
        session.query(ContainerGroupOverride).filter_by(host_key=host_key).all()
    )

    return {
        "host_key": host_key,
        "host_label": host_label,
        "incoming_ids": incoming_ids,
        "group_changes": group_changes,
        "archive_changes": archive_changes,
        "assignment_changes": assignment_changes,
        "desired": desired,
        "overrides": overrides,
        "group_by_id": group_by_id,
    }


def execute_import_plan(session, plan):
    """Apply a previously built plan. The caller owns the transaction."""
    folder_to_group = {}

    for change in plan["group_changes"]:
        folder = change["folder"]
        payload = _folder_payload(folder)
        action = change["action"]
        group = change["group"]
        if action == "create":
            group = ContainerGroup(
                source=SOURCE,
                host_key=plan["host_key"],
                external_id=folder["external_id"],
                active=True,
                **payload,
            )
            session.add(group)
        elif action in ("update", "reactivate"):
            group.name = payload["name"]
            group.external_parent_id = payload["external_parent_id"]
            group.icon = payload["icon"]
            group.sort_order = payload["sort_order"]
            group.metadata_json = payload["metadata_json"]
            group.active = True
        if group is not None:
            folder_to_group[folder["external_id"]] = group

    for change in plan["archive_changes"]:
        change["group"].active = False

    session.flush()

    for change in plan["assignment_changes"]:
        action = change["action"]
        if action == "add":
            session.add(
                ContainerGroupAssignment(
                    group=folder_to_group[change["folder_id"]],
                    host_key=plan["host_key"],
                    host_label=plan["host_label"],
                    container_key=change["container_key"],
                    container_label=change["label"],
                )
            )
        elif action == "move":
            assignment = change["assignment"]
            assignment.group = folder_to_group[change["folder_id"]]
            assignment.host_label = plan["host_label"]
            assignment.container_label = change["label"]
        elif action == "unchanged":
            assignment = change["assignment"]
            assignment.host_label = plan["host_label"]
            assignment.container_label = change["label"]
        elif action == "remove":
            session.delete(change["assignment"])

    session.flush()


def build_import_report(session, parsed, plan, dry_run):
    """Build a report from the plan only, so dry runs and real imports match."""
    groups = {"created": 0, "updated": 0, "reactivated": 0, "unchanged": 0, "archived": 0}
    for change in plan["group_changes"]:
        groups[_GROUP_ACTION_COUNTS[change["action"]]] += 1
    groups["archived"] = len(plan["archive_changes"])

    assignments = {"added": 0, "moved": 0, "removed": 0, "unchanged": 0}
    for change in plan["assignment_changes"]:
        assignments[_ASSIGNMENT_ACTION_COUNTS[change["action"]]] += 1

    apps = app_identities(session)
    app_keys = {(entry["host_key"], entry["container_key"]) for entry in apps}
    unmatched = sorted(
        container_key
        for container_key in plan["desired"]
        if (plan["host_key"], container_key) not in app_keys
    )

    # Simulate the post-import state for effective groups: imported groups are
    # active exactly when their folder is present in this import; manual groups
    # keep their current state; overrides always win.
    active_after = {}
    for group in session.query(ContainerGroup).all():
        if group.source == SOURCE and group.host_key == plan["host_key"]:
            active_after[group.id] = group.external_id in plan["incoming_ids"]
        else:
            active_after[group.id] = bool(group.active)

    effective = set(plan["desired"].keys())
    for override in plan["overrides"]:
        if override.group_id is None:
            effective.discard(override.container_key)
        elif active_after.get(override.group_id, False):
            effective.add(override.container_key)
        else:
            effective.discard(override.container_key)

    host_apps = [entry for entry in apps if entry["host_key"] == plan["host_key"]]
    ungrouped_apps = sorted(
        entry["container_key"]
        for entry in host_apps
        if entry["container_key"] not in effective
    )

    matched_hosts = matching_hosts(session, plan["host_key"])
    host = {
        "key": plan["host_key"],
        "label": plan["host_label"],
        "matched": matched_hosts,
        "ambiguous": len(matched_hosts) > 1,
    }
    if not matched_hosts:
        host["candidates"] = host_candidates(session)

    return {
        "dry_run": dry_run,
        "source": SOURCE,
        "host": host,
        "folders": {"total": len(parsed["folders"])},
        "groups": groups,
        "assignments": assignments,
        "overrides": {"untouched": len(plan["overrides"])},
        "conflicts": parsed["conflicts"],
        "warnings": parsed["warnings"],
        "unmatched_containers": unmatched,
        "ungrouped_apps": ungrouped_apps,
    }


def import_folderview(data, host_key, host_label=None, dry_run=False):
    """Import a parsed FolderView payload. Returns the import report."""
    parsed = parse_folderview_config(data)
    key, label = normalize_host(host_key=host_key, host_label=host_label)
    plan = build_import_plan(db.session, parsed, key, label)
    report = build_import_report(db.session, parsed, plan, dry_run=dry_run)
    if dry_run:
        return report
    try:
        execute_import_plan(db.session, plan)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return report


def import_folderview_file(
    path,
    host_key,
    host_label=None,
    dry_run=False,
    max_bytes=MAX_CONFIG_BYTES,
):
    """Read a FolderView config file (read-only) and import it."""
    if not path:
        raise FolderviewImportError("No FolderView configuration path was provided")
    try:
        with open(path, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise FolderviewImportError(f"Could not read FolderView configuration: {exc}") from exc
    if len(raw) > max_bytes:
        raise FolderviewImportError(
            "FolderView configuration is larger than the allowed limit"
        )
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FolderviewImportError(
            f"FolderView configuration is not valid JSON: {exc}"
        ) from exc
    return import_folderview(
        data,
        host_key=host_key,
        host_label=host_label,
        dry_run=dry_run,
    )
