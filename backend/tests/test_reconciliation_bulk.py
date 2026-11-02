"""Bulk metadata reconciliation, exclusions and reviewed transaction safety."""
from datetime import datetime, timedelta, timezone
import time

import pytest

from app.models import (
    AppService,
    ContainerGroup,
    ContainerGroupAssignment,
    ContainerGroupOverride,
    Hardware,
    ReconciliationExclusion,
    VM,
    db,
)
from app.services.discovery_identity import discovery_metadata, with_discovery_metadata
from app.services.group_identity import app_identity
from app.services.group_resolution import effective_group

HEADERS = {"X-Admin-Token": "bulk-reconciliation-test"}


def now():
    return datetime.now(timezone.utc)


@pytest.fixture()
def inventory(app):
    betty = Hardware(name="Betty", ip_address="192.0.2.10", hostname="betty.example")
    blackbox = Hardware(name="Blackbox", ip_address="192.0.2.20")
    db.session.add_all([betty, blackbox])
    db.session.flush()
    docker = VM(name="Docker", hardware_id=betty.id, ip_address="192.0.2.10")
    remote = VM(name="Docker", hardware_id=blackbox.id)
    db.session.add_all([docker, remote])
    db.session.flush()
    plex = AppService(
        name="Media Server",
        vm_id=docker.id,
        description="Plex description",
        icon="🎬",
        notes=(
            "User notes.  \n## Docker configuration\nContainer: plex\n"
            "Container ID: old-container\nImage ID: old-image\nImage: plex:old\n"
        ),
    )
    web = AppService(
        name="Open WebUI",
        vm_id=docker.id,
        description="Docker container: open-webui",
        icon="★",
        notes="Keep my notes.",
    )
    plain = AppService(name="Router admin", hardware_id=betty.id)
    foreign = AppService(name="Remote Plex", vm_id=remote.id, port=443,
                         description="Docker container: plex")
    group = ContainerGroup(name="Manual choice", source="manual", host_key="betty")
    imported = ContainerGroup(name="Tools", source="folderview", host_key="betty",
                              external_id="tools")
    db.session.add_all([plex, web, plain, foreign, group, imported])
    db.session.flush()
    db.session.add(ContainerGroupOverride(group_id=group.id, host_key="betty",
                                         container_key="open-webui"))
    db.session.add(ContainerGroupAssignment(group_id=imported.id, host_key="betty",
                                            container_key="tools"))
    db.session.commit()
    app.config["ADMIN_TOKEN"] = "bulk-reconciliation-test"
    return {"host": betty, "plain": plain, "plex": plex, "web": web,
            "foreign": foreign, "group": group, "imported": imported}


DEFAULT_CONTAINERS = [
    {"container_name": "plex", "container_id": "new-plex",
     "image_id": "sha256:new-plex", "image": "plex:new"},
    {"container_name": "open-webui", "container_id": "new-webui",
     "image_id": "sha256:new-webui", "image": "open-webui:2"},
]


def snapshot(containers=None, **changes):
    data = {
        "schema_version": 1,
        "host_key": "Betty",
        "source": "bulk test snapshot",
        "status": "success",
        "complete": True,
        "coverage": "all_containers",
        "completed_at": now().isoformat(),
        "containers": DEFAULT_CONTAINERS if containers is None else containers,
    }
    data.update(changes)
    return data


def bulk_preview(client, payload=None, keys=None, host="betty"):
    return client.post("/api/reconciliation/preview-bulk", json={
        "host_key": host,
        "snapshot": payload if payload is not None else snapshot(),
        "container_keys": keys,
    })


def bulk_apply(client, response, headers=HEADERS):
    assert response.status_code == 200, response.get_json()
    return client.post("/api/reconciliation/apply-bulk",
                       json={"token": response.get_json()["token"]}, headers=headers)


def add_exclusion(client, name="old-backup", host="betty", reason="Retained rollback container",
                  headers=HEADERS):
    return client.post("/api/reconciliation/exclusions", headers=headers,
                       json={"host_key": host, "container_name": name, "reason": reason})


def test_bulk_preview_and_apply_update_only_allowed_metadata(inventory, client):
    before = AppService.query.count()
    reviewed = bulk_preview(client, snapshot([
        *DEFAULT_CONTAINERS,
        {"container_name": "old-backup", "container_id": "backup-id"},
    ]))
    assert reviewed.status_code == 200, reviewed.get_json()
    plan = reviewed.get_json()["plan"]

    assert plan["kind"] == "bulk_update"
    assert plan["app_count"] == 2
    assert {item["app_id"] for item in plan["applications"]} == {
        inventory["plex"].id, inventory["web"].id}
    assert {field["field"] for item in plan["applications"] for field in item["fields"]} == {
        "container_id", "image_id", "image", "observed_at"}
    assert plan["skipped"][0]["container_key"] == "old-backup"
    assert plan["skipped"][0]["classification"] == "missing_inventory"
    assert AppService.query.count() == before
    assert discovery_metadata(inventory["plex"].notes) == {}

    plex_before = inventory["plex"].notes
    result = bulk_apply(client, reviewed)
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["updated"] == 2
    assert bulk_apply(client, reviewed).status_code == 409  # Replay cannot rewrite observations.
    assert AppService.query.count() == before

    plex = inventory["plex"]
    web = inventory["web"]
    assert plex.name == "Media Server" and plex.description == "Plex description"
    assert plex.vm_id is not None and plex.icon == "🎬"
    assert plex.notes.startswith(plex_before)
    assert discovery_metadata(plex.notes)["container_id"] == "new-plex"
    assert discovery_metadata(plex.notes)["image_id"] == "sha256:new-plex"
    assert discovery_metadata(plex.notes)["image"] == "plex:new"
    assert discovery_metadata(plex.notes)["observed_at"] == plan["completed_at"]
    assert web.name == "Open WebUI" and web.description == "Docker container: open-webui"
    assert discovery_metadata(web.notes)["container_id"] == "new-webui"
    assert not AppService.query.filter_by(name="old-backup").first()


def test_bulk_apply_preserves_group_overrides_assignments_and_map_data(inventory, client):
    before_override = ContainerGroupOverride.query.one().to_dict()
    before_assignments = [row.to_dict() for row in ContainerGroupAssignment.query.all()]
    before_effective = effective_group(db.session, "betty", "open-webui").id
    before_graph = client.get("/api/map/graph").get_json()
    before_links = (inventory["web"].name, inventory["web"].description, inventory["web"].vm_id)

    reviewed = bulk_preview(client)
    assert bulk_apply(client, reviewed).status_code == 200

    assert ContainerGroupOverride.query.one().to_dict() == before_override
    assert [row.to_dict() for row in ContainerGroupAssignment.query.all()] == before_assignments
    assert effective_group(db.session, "betty", "open-webui").id == before_effective
    assert client.get("/api/map/graph").get_json() == before_graph
    assert (inventory["web"].name, inventory["web"].description,
            inventory["web"].vm_id) == before_links


def test_bulk_preview_rejects_stale_partial_and_failed_scans(inventory, client):
    changes = [
        {"status": "failed"},
        {"complete": False},
        {"coverage": "running_only"},
        {"completed_at": (now() - timedelta(days=2)).isoformat()},
        {"completed_at": None},
        {"completed_at": "invalid"},
        {"completed_at": (now() + timedelta(hours=1)).isoformat()},
    ]
    before = [(app.id, app.notes) for app in AppService.query.order_by(AppService.id)]
    for change in changes:
        response = bulk_preview(client, snapshot(**change))
        assert response.status_code == 400, change
    assert [(app.id, app.notes) for app in AppService.query.order_by(AppService.id)] == before


def test_bulk_apply_requires_admin_and_rejects_single_action_tokens(inventory, client, app):
    reviewed = bulk_preview(client)
    assert bulk_apply(client, reviewed, {}).status_code == 401

    app.config["ADMIN_TOKEN"] = ""
    assert bulk_apply(client, reviewed).status_code == 503
    app.config["ADMIN_TOKEN"] = "bulk-reconciliation-test"

    single = client.post("/api/reconciliation/preview", json={
        "host_key": "betty", "snapshot": snapshot(), "action": {
            "kind": "update", "container_key": "plex", "app_id": inventory["plex"].id}})
    assert client.post("/api/reconciliation/apply-bulk",
                       json={"token": single.get_json()["token"]},
                       headers=HEADERS).status_code == 400
    assert bulk_apply(client, reviewed).status_code == 200


def test_bulk_apply_is_one_transaction_and_rolls_back_every_application(inventory, client, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.routes import reconciliation as routes

    reviewed = bulk_preview(client)
    before = {app.id: app.notes for app in AppService.query.all()}
    original = routes.execute_bulk_update

    def fail_after_flush(plan):
        original(plan)
        raise OperationalError("simulated storage failure", {}, Exception("fixture failure"))

    monkeypatch.setattr(routes, "execute_bulk_update", fail_after_flush)
    response = bulk_apply(client, reviewed)
    assert response.status_code == 409
    assert {app.id: app.notes for app in AppService.query.all()} == before
    assert AppService.query.count() == 4


def test_concurrent_inventory_changes_and_expired_previews_are_rejected(inventory, client, monkeypatch):
    reviewed = bulk_preview(client)
    inventory["plain"].name = "Changed concurrently"
    db.session.commit()
    assert bulk_apply(client, reviewed).status_code == 409
    assert discovery_metadata(inventory["plex"].notes) == {}

    inventory["plain"].name = "Router admin"
    db.session.commit()
    actual = time.time
    with monkeypatch.context() as context:
        context.setattr("itsdangerous.timed.time.time", lambda: actual() - 700)
        expired = bulk_preview(client)
    assert bulk_apply(client, expired).status_code == 409
    assert discovery_metadata(inventory["plex"].notes) == {}


def test_older_duplicate_and_unmatched_rows_are_not_bulk_updated(inventory, client):
    future = (now() + timedelta(hours=1)).isoformat()
    inventory["plex"].notes = with_discovery_metadata(inventory["plex"].notes, {
        "container_name": "plex", "container_id": "future-id",
        "image_id": "future-image", "image": "plex:future", "observed_at": future})
    db.session.commit()

    plan = bulk_preview(client).get_json()["plan"]
    assert plan["app_count"] == 1
    assert plan["applications"][0]["container_key"] == "open-webui"
    assert {row["container_key"]: row["classification"] for row in plan["skipped"]} == {
        "plex": "older_observation"}
    assert bulk_preview(client, keys=["plex"]).status_code == 400
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": snapshot()}).get_json()
    assert report["summary"]["uncertain"] == 1

    db.session.add(AppService(name="PLEX", hardware_id=inventory["host"].id))
    db.session.commit()
    plan = bulk_preview(client).get_json()["plan"]
    assert plan["app_count"] == 1
    assert bulk_preview(client, keys=["plex"]).status_code == 400

    duplicate_discovery = snapshot([
        {"container_name": "plex"}, {"container_name": "PLEX"},
        {"container_name": "open-webui"}])
    plan = bulk_preview(client, duplicate_discovery).get_json()["plan"]
    assert plan["app_count"] == 1
    assert bulk_preview(client, duplicate_discovery, keys=["plex"]).status_code == 400
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": duplicate_discovery}).get_json()
    assert report["summary"]["matched"] == 1
    assert report["summary"]["uncertain"] == 2


def test_bulk_update_requires_eligible_matches_and_known_selection(inventory, client):
    assert bulk_preview(client, snapshot([])).status_code == 400
    assert bulk_preview(client, keys=["not-in-snapshot"]).status_code == 400
    assert bulk_preview(client, keys=["old-backup"]).status_code == 400
    assert bulk_preview(client, keys=[]).status_code == 400
    assert bulk_preview(client, keys="plex").status_code == 400
    assert AppService.query.count() == 4


def test_bulk_update_does_not_clear_known_metadata_when_snapshot_omits_ids(inventory, client):
    reviewed = bulk_preview(client, snapshot([{"container_name": "plex"}]))
    assert reviewed.status_code == 200
    fields = {field["field"]: field["after"] for field in reviewed.get_json()["plan"]["applications"][0]["fields"]}
    assert fields["container_id"] == "old-container"
    assert fields["image_id"] == "old-image"
    assert fields["image"] == "plex:old"
    assert bulk_apply(client, reviewed).status_code == 200
    metadata = discovery_metadata(inventory["plex"].notes)
    assert metadata["container_id"] == "old-container"
    assert metadata["image_id"] == "old-image"
    assert metadata["image"] == "plex:old"


def test_bulk_update_keeps_the_application_docker_label_casing(inventory, client):
    reviewed = bulk_preview(client, snapshot([
        {"container_name": "PLEX", "container_id": "new-plex",
         "image_id": "sha256:new-plex", "image": "plex:new"}]))
    assert reviewed.status_code == 200
    plan = reviewed.get_json()["plan"]
    assert plan["applications"][0]["resource"]["container_name"] == "plex"
    assert bulk_apply(client, reviewed).status_code == 200
    assert discovery_metadata(inventory["plex"].notes)["container_name"] == "plex"


def test_exclusions_require_admin_are_host_scoped_and_persist(inventory, client, app):
    assert add_exclusion(client, headers={}).status_code == 401
    app.config["ADMIN_TOKEN"] = ""
    assert add_exclusion(client).status_code == 503
    app.config["ADMIN_TOKEN"] = "bulk-reconciliation-test"

    created = add_exclusion(client)
    assert created.status_code == 201, created.get_json()
    exclusion_id = created.get_json()["exclusion"]["id"]
    assert created.get_json()["exclusion"]["container_key"] == "old-backup"
    assert created.get_json()["exclusion"]["container_name"] == "old-backup"

    assert add_exclusion(client, "old-backup").status_code == 409
    assert add_exclusion(client, "bad name").status_code == 400
    assert add_exclusion(client, host="missing").status_code == 400

    listed = client.get("/api/reconciliation/exclusions?host_key=betty")
    assert listed.status_code == 200
    assert [item["container_key"] for item in listed.get_json()["exclusions"]] == ["old-backup"]
    assert client.get("/api/reconciliation/exclusions").status_code == 400
    assert client.get("/api/reconciliation/exclusions?host_key=missing").status_code == 400

    db.session.remove()  # Persistence is database-backed, not page/session state.
    assert client.get("/api/reconciliation/exclusions?host_key=betty").get_json()["exclusions"]

    assert client.delete(f"/api/reconciliation/exclusions/{exclusion_id}",
                         headers={}).status_code == 401
    assert client.delete("/api/reconciliation/exclusions/9999", headers=HEADERS).status_code == 404
    removed = client.delete(f"/api/reconciliation/exclusions/{exclusion_id}", headers=HEADERS)
    assert removed.status_code == 200
    assert client.get("/api/reconciliation/exclusions?host_key=betty").get_json()["exclusions"] == []
    assert AppService.query.count() == 4


def test_exclusion_moves_unmatched_container_out_of_warnings_but_keeps_it_visible(inventory, client):
    payload = snapshot([
        *DEFAULT_CONTAINERS,
        {"container_name": "old-backup", "container_id": "backup-id"},
    ])
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": payload}).get_json()
    assert report["summary"]["matched"] == 2
    assert report["summary"]["unmatched"] == 1
    assert report["summary"]["excluded"] == 0

    created = add_exclusion(client)
    assert created.status_code == 201
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": payload}).get_json()
    row = next(item for item in report["containers"] if item["container_key"] == "old-backup")
    assert row["classification"] == "excluded" and row["excluded"] is True
    assert "Retained rollback container" in row["reason"]
    assert report["summary"] == {"matched": 2, "unmatched": 0, "excluded": 1,
                                 "uncertain": 0, "not_seen": 1}
    assert report["exclusions"][0]["observed"] is True
    assert report["exclusions"][0]["inventory_ids"] == []
    assert AppService.query.count() == 4

    excluded_id = created.get_json()["exclusion"]["id"]
    client.delete(f"/api/reconciliation/exclusions/{excluded_id}", headers=HEADERS)
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": payload}).get_json()
    assert next(item for item in report["containers"]
                if item["container_key"] == "old-backup")["classification"] == "missing_inventory"
    assert report["summary"]["unmatched"] == 1


def test_exclusions_are_scoped_to_the_selected_root_host(inventory, client):
    assert add_exclusion(client).status_code == 201
    betty = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": snapshot([{"container_name": "old-backup"}])}).get_json()
    blackbox = client.post("/api/reconciliation/compare", json={
        "host_key": "blackbox", "snapshot": snapshot([{"container_name": "old-backup"}],
                                                     host_key="Blackbox")}).get_json()
    assert next(row for row in betty["containers"] if row["container_key"] == "old-backup")["classification"] == "excluded"
    assert next(row for row in blackbox["containers"] if row["container_key"] == "old-backup")["classification"] == "missing_inventory"


def test_exclusion_suppresses_confirmed_absent_inventory_without_deleting(inventory, client):
    inventory["plex"].notes = with_discovery_metadata(inventory["plex"].notes, {
        "container_name": "plex", "container_id": "old-container",
        "image_id": "old-image", "image": "plex:old",
        "observed_at": (now() - timedelta(minutes=5)).isoformat()})
    db.session.commit()
    payload = snapshot([])
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": payload}).get_json()
    assert next(row for row in report["inventory"]
                if row["app_id"] == inventory["plex"].id)["classification"] == "confirmed_absent"

    assert add_exclusion(client, "plex").status_code == 201
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": payload}).get_json()
    row = next(row for row in report["inventory"] if row["app_id"] == inventory["plex"].id)
    assert row["classification"] == "excluded" and row["excluded"] is True
    assert report["summary"]["excluded"] == 1
    assert AppService.query.count() == 4
    assert discovery_metadata(inventory["plex"].notes)["container_id"] == "old-container"


def test_exclusion_of_a_matched_container_does_not_block_bulk_metadata(inventory, client):
    assert add_exclusion(client, "plex").status_code == 201
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": snapshot()}).get_json()
    row = next(item for item in report["containers"] if item["container_key"] == "plex")
    assert row["classification"] == "matched" and row["excluded"] is True

    reviewed = bulk_preview(client)
    assert reviewed.get_json()["plan"]["app_count"] == 2
    assert bulk_apply(client, reviewed).status_code == 200
    assert ReconciliationExclusion.query.filter_by(host_key="betty", container_key="plex").count() == 1
    assert discovery_metadata(inventory["plex"].notes)["container_id"] == "new-plex"
