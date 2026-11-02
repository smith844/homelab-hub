"""Read-only host-scoped comparison and explicitly reviewed inventory mutations.

No collector, Docker socket, network probing or persistent scan history lives here.
Snapshots are supplied by the operator/scanner and whitelisted before reporting.
"""
from collections import Counter, defaultdict
import hashlib
import json
import re

from ..models import AppService, ContainerGroup, ContainerGroupAssignment, ContainerGroupOverride, Hardware, db
from .discovery_identity import discovery_metadata, with_discovery_metadata
from .group_identity import app_identity, docker_container_name, normalize_identity
from .group_resolution import effective_group

from .discovery_adapters import ReconciliationError, normalise_snapshot, timestamp
from .network_reconciliation import compare_network_scan


def host_record(host_key):
    matches = [h for h in db.session.query(Hardware).all() if normalize_identity(h.name) == host_key]
    if len(matches) != 1:
        raise ReconciliationError("Choose a unique root hardware host; missing or duplicate host names cannot be reconciled safely")
    return matches[0]


def apps_for_host(host_key):
    return [app for app in db.session.query(AppService).all() if app_identity(app)[0] == host_key]


def fingerprint(host_key):
    # Guard against inventory, parent, imported-assignment or override changes
    # between preview and apply. Include metadata without returning it to callers.
    from ..models import VM
    data = {
        "apps": [a.to_dict() for a in db.session.query(AppService).order_by(AppService.id)],
        "hosts": [h.to_dict() for h in db.session.query(Hardware).order_by(Hardware.id)],
        "vms": [v.to_dict() for v in db.session.query(VM).order_by(VM.id)],
        "assignments": [a.to_dict() for a in db.session.query(ContainerGroupAssignment).filter_by(host_key=host_key).order_by(ContainerGroupAssignment.id)],
        "groups": [g.to_dict() for g in db.session.query(ContainerGroup).order_by(ContainerGroup.id)],
        "overrides": [o.to_dict() for o in db.session.query(ContainerGroupOverride).filter_by(host_key=host_key).order_by(ContainerGroupOverride.id)],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def observed_ids(app):
    linked = discovery_metadata(app.notes)
    result = {key: linked.get(key) or "" for key in ("container_id", "image_id", "image")}
    if docker_container_name(app):
        for key, label in (("container_id", "Container ID"), ("image_id", "Image ID"), ("image", "Image")):
            if not result[key]:
                match = re.search(r"(?im)^\s*" + label + r":\s*(\S+)\s*$", app.notes or "")
                if match:
                    result[key] = match.group(1)
    return result


def last_observation(app):
    return timestamp(discovery_metadata(app.notes).get("observed_at"))


def compare(host_key, snapshot=None):
    host = host_record(host_key)
    scan = normalise_snapshot(snapshot, host_key)
    apps = apps_for_host(host_key)
    index = defaultdict(list)
    for app in apps:
        index[app_identity(app)[2]].append(app)
    seen = Counter(r["container_key"] for r in scan["containers"])
    rows = []
    for resource in scan["containers"]:
        matches = index[resource["container_key"]]
        duplicate = seen[resource["container_key"]] > 1 or len(matches) > 1
        changes = []
        older = (len(matches) == 1 and last_observation(matches[0]) is not None
                 and timestamp(resource["observed_at"]) is not None
                 and last_observation(matches[0]) > timestamp(resource["observed_at"]))
        if len(matches) == 1:
            old = observed_ids(matches[0])
            changes = [{"field": key, "before": old[key] or None, "after": resource[key]}
                       for key in old if resource[key] and resource[key] != old[key]]
        rows.append({**resource, "classification": "duplicate" if duplicate else "older_observation" if older else "matched" if matches else "missing_inventory",
                     "reason": "Ambiguous host-scoped identity; resolve duplicates before applying." if duplicate else
                               "Inventory has a newer recorded observation; this older snapshot cannot replace it." if older else
                               "Root host and stable container name match; Docker IDs are observations, not identity." if matches else
                               "No application on this host has this recorded container name or display-name fallback.",
                     "app_id": matches[0].id if len(matches) == 1 else None,
                     "app_name": matches[0].name if len(matches) == 1 else None, "changes": changes,
                     "candidate_ids": [a.id for a in matches]})
    inventory = []
    for app in apps:
        key = app_identity(app)[2]
        if key in seen:
            continue
        docker = bool(docker_container_name(app))
        newer = (last_observation(app) is not None and timestamp(scan["completed_at"]) is not None
                 and last_observation(app) > timestamp(scan["completed_at"]))
        absent = docker and scan["authoritative"] and not newer
        inventory.append({"app_id": app.id, "name": app.name, "container_key": key,
                          "classification": "confirmed_absent" if absent else "unknown",
                          "reason": "Recorded Docker identity was absent from this complete recent successful snapshot. Review only; never automatically deleted." if absent else
                                    "Inventory has a newer recorded observation; absence in an older snapshot does not confirm current absence." if newer else
                                    "Application has no recorded Docker identity; it may be a non-container service." if not docker else scan["reason"]})
    unmatched = []
    for assignment in db.session.query(ContainerGroupAssignment).filter_by(host_key=host_key):
        if not index.get(assignment.container_key):
            unmatched.append({"container_key": assignment.container_key, "group_name": assignment.group.name,
                              "group_active": bool(assignment.group.active),
                              "reason": "FolderView membership has no inventory identity on this host; this alone does not prove a running container exists."})
    ungrouped = []
    for app in apps:
        key = app_identity(app)[2]
        if effective_group(db.session, host_key, key) is None:
            override = db.session.query(ContainerGroupOverride).filter_by(host_key=host_key, container_key=key).first()
            ungrouped.append({"app_id": app.id, "name": app.name, "container_key": key,
                              "reason": "Explicit manual Ungrouped choice." if override and override.group_id is None else
                                        "Manual override points to an archived group." if override else
                                        "No active imported or manual assignment; this can be intentional."})
    duplicates = [{"container_key": key, "inventory_ids": [a.id for a in index[key]], "discovered_count": seen[key]}
                  for key in sorted(index.keys() | seen.keys()) if len(index[key]) > 1 or seen[key] > 1]
    return {"host": {"key": host_key, "name": host.name}, "scan": scan,
            "network": compare_network_scan(scan.get("network_scan"), host, apps), "containers": rows,
            "inventory": inventory, "folderview_unmatched": unmatched, "ungrouped": ungrouped,
            "duplicates": duplicates,
            "applications": [{"id": a.id, "name": a.name, "container_key": app_identity(a)[2]} for a in apps]}


def plan_action(host_key, snapshot, action):
    report = compare(host_key, snapshot)
    scan = report["scan"]
    if scan["status"] != "success" or not scan["fresh"]:
        raise ReconciliationError("Changes require a successful snapshot completed within the last 24 hours")
    if not isinstance(action, dict) or action.get("kind") not in ("add", "update", "match"):
        raise ReconciliationError("Choose add, update or match")
    key = normalize_identity(action.get("container_key"))
    rows = [r for r in report["containers"] if r["container_key"] == key]
    if len(rows) != 1:
        raise ReconciliationError("Select one unambiguous discovered container")
    row = rows[0]
    if row["classification"] not in ("matched", "missing_inventory"):
        raise ReconciliationError(row["reason"])
    if action["kind"] == "add":
        if row["classification"] != "missing_inventory":
            raise ReconciliationError("A matching inventory application already exists")
        target = None
    else:
        app_id = action.get("app_id")
        if isinstance(app_id, bool) or not isinstance(app_id, int):
            raise ReconciliationError("app_id must be an inventory application id")
        target = db.session.get(AppService, app_id)
        if target is None or app_identity(target)[0] != host_key:
            raise ReconciliationError("Target application must belong to this root host")
        if row["app_id"] not in (None, target.id):
            raise ReconciliationError("Container already matches another application")
        if last_observation(target) and last_observation(target) > timestamp(row["observed_at"]):
            raise ReconciliationError("Target has newer discovery metadata; use a newer snapshot")
        old_key = app_identity(target)[2]
        if sum(a["container_key"] == old_key for a in report["applications"]) > 1:
            raise ReconciliationError("Target has a duplicate inventory identity")
        if old_key != key and any(r["container_key"] == old_key for r in report["containers"]):
            raise ReconciliationError("Target already represents another resource present in this snapshot")
        if action["kind"] == "update" and row["app_id"] != target.id:
            raise ReconciliationError("Update requires an existing identity match; use manual match instead")
        if old_key != key:
            overrides = db.session.query(ContainerGroupOverride).filter_by(host_key=host_key).all()
            if any(o.container_key == old_key for o in overrides) and any(o.container_key == key for o in overrides):
                raise ReconciliationError("Both identities have manual overrides; resolve the conflicting choices in Container groups first")
    resource = {k: row[k] for k in ("container_name", "container_id", "image_id", "image", "observed_at")}
    previous = observed_ids(target) if target else {}
    fields = [{"field": k, "before": previous.get(k) or None, "after": resource[k]}
              for k in ("container_id", "image_id", "image") if resource[k]]
    fields.insert(0, {"field": "logical identity", "before": app_identity(target)[2] if target else None, "after": key})
    fields.append({"field": "observed_at", "before": discovery_metadata(target.notes).get("observed_at") if target else None, "after": resource["observed_at"]})
    if target is None:
        host = host_record(host_key)
        fields.extend([{"field": "name", "before": None, "after": row["container_name"]},
                       {"field": "parent host", "before": None, "after": host.name},
                       {"field": "hostname", "before": None, "after": host.hostname},
                       {"field": "description", "before": None, "after": "Docker container: " + row["container_name"]}])
    if target is not None and app_identity(target)[2] != key:
        old_key = app_identity(target)[2]
        override = db.session.query(ContainerGroupOverride).filter_by(host_key=host_key, container_key=old_key).first()
        if override:
            choice = override.group.name if override.group else "Explicit Ungrouped"
            fields.append({"field": "manual group override", "before": f"{choice} for {old_key}", "after": f"{choice} for {key}"})
    return {"kind": action["kind"], "host_key": host_key, "app_id": target.id if target else None,
            "name": target.name if target else row["container_name"], "resource": resource, "fields": fields,
            "group_override": "Existing manual override follows the logical identity; imported assignments and map anchors are not modified.",
            "fingerprint": fingerprint(host_key)}


def execute_action(plan):
    host = host_record(plan["host_key"])
    resource = plan["resource"]
    app = db.session.get(AppService, plan["app_id"]) if plan["app_id"] else None
    if app:
        old_key = app_identity(app)[2]
        new_key = normalize_identity(resource["container_name"])
        if old_key != new_key:
            override = db.session.query(ContainerGroupOverride).filter_by(host_key=plan["host_key"], container_key=old_key).first()
            if override:
                override.container_key = new_key
                override.container_label = resource["container_name"]
    else:
        app = AppService(name=plan["name"], hardware_id=host.id, hostname=host.hostname,
                         description="Docker container: " + resource["container_name"])
        db.session.add(app)
    known = observed_ids(app)
    metadata = {**resource, **{key: resource.get(key) or known[key] for key in known}}
    app.notes = with_discovery_metadata(app.notes, metadata)
    db.session.flush()
    return app.id
