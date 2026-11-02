import json

from app.models import (
    AppService,
    ContainerGroup,
    ContainerGroupAssignment,
    ContainerGroupOverride,
    Hardware,
    VM,
    db,
)
from app.services.folderview_import import import_folderview

ADMIN_HEADERS = {"X-Admin-Token": "test-token"}


def _folder(name, containers):
    return {
        "name": name,
        "parentId": "",
        "containers": containers,
        "regex": "",
        "settings": {},
        "actions": [],
        "updatedAt": "2026-01-01T00:00:00Z",
    }


def _seed(app):
    betty = Hardware(name="Betty")
    blackbox = Hardware(name="Blackbox")
    db.session.add_all([betty, blackbox])
    db.session.flush()
    betty_docker = VM(name="Docker", hardware_id=betty.id)
    blackbox_docker = VM(name="Docker", hardware_id=blackbox.id)
    db.session.add_all([betty_docker, blackbox_docker])
    db.session.flush()
    db.session.add_all(
        [
            AppService(
                name="Open-webui",
                vm_id=betty_docker.id,
                notes="## Docker configuration\nContainer: open-webui\n",
            ),
            AppService(
                name="Plex",
                vm_id=betty_docker.id,
                description="Docker container: plex",
            ),
            AppService(name="Extra App", vm_id=betty_docker.id),
            AppService(
                name="EmonCMS",
                vm_id=blackbox_docker.id,
                description="Docker container: emoncms",
            ),
        ]
    )
    db.session.commit()
    import_folderview(
        {
            "folder-ai": _folder("AI", ["open-webui", "missing-one"]),
            "folder-media": _folder("Media", ["plex"]),
        },
        host_key="Betty",
    )
    import_folderview(
        {"folder-monitoring": _folder("Monitoring", ["emoncms"])},
        host_key="Blackbox",
    )
    app.config["ADMIN_TOKEN"] = "test-token"


def _group(name):
    return db.session.query(ContainerGroup).filter_by(name=name).one()


def _app(name):
    return db.session.query(AppService).filter_by(name=name).one()


def test_management_read_endpoint_is_public_and_host_scoped(app, client):
    _seed(app)

    response = client.get("/api/container-groups/management")

    assert response.status_code == 200
    payload = response.get_json()
    hosts = {host["key"]: host["label"] for host in payload["hosts"]}
    assert hosts["betty"] == "Betty"
    assert hosts["blackbox"] == "Blackbox"

    groups = {(group["name"], group["host_key"]): group for group in payload["groups"]}
    assert groups[("AI", "betty")]["source"] == "folderview"
    assert groups[("AI", "betty")]["assignment_count"] == 2
    assert groups[("AI", "betty")]["unmatched_count"] == 1

    apps = {(app["name"], app["host_key"]): app for app in payload["apps"]}
    assert apps[("Open-webui", "betty")]["group_name"] == "AI"
    assert apps[("Extra App", "betty")]["group_id"] is None
    assert payload["unmatched"][0]["container_key"] == "missing-one"


def test_management_writes_are_disabled_without_a_configured_token(app, client):
    _seed(app)
    app.config["ADMIN_TOKEN"] = ""

    response = client.post(
        "/api/container-groups",
        json={"name": "New", "host_key": "betty"},
    )

    assert response.status_code == 503
    assert "disabled" in response.get_json()["error"].lower()


def test_management_writes_require_a_valid_token(app, client):
    _seed(app)

    assert client.post(
        "/api/container-groups",
        json={"name": "New", "host_key": "betty"},
    ).status_code == 401
    assert client.post(
        "/api/container-groups",
        json={"name": "New", "host_key": "betty"},
        headers={"X-Admin-Token": "wrong"},
    ).status_code == 401
    assert client.post(
        "/api/container-groups",
        json={"name": "New", "host_key": "betty"},
        headers={"Authorization": "Bearer test-token"},
    ).status_code == 201


def test_create_edit_archive_and_restore_manual_group(app, client):
    _seed(app)

    created = client.post(
        "/api/container-groups",
        json={
            "name": "  My Group ",
            "host_key": "Betty",
            "color": "#12AB34",
            "icon": "🚀",
            "sort_order": 4,
        },
        headers=ADMIN_HEADERS,
    )
    assert created.status_code == 201
    group = created.get_json()["data"]
    assert group["name"] == "My Group"
    assert group["source"] == "manual"
    assert group["host_key"] == "betty"
    assert group["color"] == "#12ab34"

    updated = client.put(
        f"/api/container-groups/{group['id']}",
        json={"name": "Renamed", "color": "#000000", "icon": "📦", "active": False},
        headers=ADMIN_HEADERS,
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["name"] == "Renamed"
    assert updated.get_json()["data"]["active"] is False

    restored = client.put(
        f"/api/container-groups/{group['id']}",
        json={"active": True},
        headers=ADMIN_HEADERS,
    )
    assert restored.status_code == 200
    assert restored.get_json()["data"]["active"] is True


def test_group_validation_and_name_conflicts(app, client):
    _seed(app)

    assert client.post(
        "/api/container-groups",
        json={"name": "", "host_key": "betty"},
        headers=ADMIN_HEADERS,
    ).status_code == 400
    assert client.post(
        "/api/container-groups",
        json={"name": "X", "host_key": "unknown"},
        headers=ADMIN_HEADERS,
    ).status_code == 400
    assert client.post(
        "/api/container-groups",
        json={"name": "X", "host_key": "betty", "color": "red"},
        headers=ADMIN_HEADERS,
    ).status_code == 400
    # Conflicts with an imported group on the same host, case-insensitively.
    assert client.post(
        "/api/container-groups",
        json={"name": "ai", "host_key": "betty"},
        headers=ADMIN_HEADERS,
    ).status_code == 409
    # The same name on another host is allowed.
    assert client.post(
        "/api/container-groups",
        json={"name": "AI", "host_key": "blackbox"},
        headers=ADMIN_HEADERS,
    ).status_code == 201


def test_imported_groups_allow_colour_and_icon_but_not_rename(app, client):
    _seed(app)
    ai = _group("AI")

    response = client.put(
        f"/api/container-groups/{ai.id}",
        json={"color": "#abcdef", "icon": "🤖", "name": "Renamed"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 400

    response = client.put(
        f"/api/container-groups/{ai.id}",
        json={"color": "#abcdef", "icon": "🤖"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["name"] == "AI"
    assert response.get_json()["data"]["color"] == "#abcdef"


def test_group_archival_hides_effective_memberships_and_restores(app, client):
    _seed(app)
    ai = _group("AI")
    open_webui = _app("Open-webui")

    assert client.put(
        f"/api/container-groups/{ai.id}",
        json={"active": False},
        headers=ADMIN_HEADERS,
    ).status_code == 200

    effective = client.get("/api/container-groups/effective").get_json()
    assert not any(group["id"] == ai.id for group in effective["groups"])
    assert not any(m["app_id"] == open_webui.id for m in effective["memberships"])

    assert client.put(
        f"/api/container-groups/{ai.id}",
        json={"active": True},
        headers=ADMIN_HEADERS,
    ).status_code == 200
    effective = client.get("/api/container-groups/effective").get_json()
    assert any(m["app_id"] == open_webui.id for m in effective["memberships"])


def test_delete_group_guards(app, client):
    _seed(app)
    ai = _group("AI")

    # Imported groups cannot be deleted.
    assert client.delete(
        f"/api/container-groups/{ai.id}", headers=ADMIN_HEADERS
    ).status_code == 409

    manual = client.post(
        "/api/container-groups",
        json={"name": "Temporary", "host_key": "betty"},
        headers=ADMIN_HEADERS,
    ).get_json()["data"]

    # Giving it an override makes it non-deletable.
    assert client.put(
        "/api/container-groups/assignments",
        json={"app_id": _app("Extra App").id, "group_id": manual["id"]},
        headers=ADMIN_HEADERS,
    ).status_code == 200
    assert client.delete(
        f"/api/container-groups/{manual['id']}", headers=ADMIN_HEADERS
    ).status_code == 409

    # Reverting the override allows deletion.
    assert client.delete(
        "/api/container-groups/assignments",
        json={"app_id": _app("Extra App").id},
        headers=ADMIN_HEADERS,
    ).status_code == 200
    assert client.delete(
        f"/api/container-groups/{manual['id']}", headers=ADMIN_HEADERS
    ).status_code == 200


def test_manual_override_precedence_and_revert(app, client):
    _seed(app)
    ai = _group("AI")
    media = _group("Media")
    plex = _app("Plex")

    response = client.put(
        "/api/container-groups/assignments",
        json={"app_id": plex.id, "group_id": ai.id},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["group_id"] == ai.id

    # The imported assignment itself is untouched.
    imported = (
        db.session.query(ContainerGroupAssignment)
        .filter_by(host_key="betty", container_key="plex")
        .one()
    )
    assert imported.group_id == media.id
    override = (
        db.session.query(ContainerGroupOverride)
        .filter_by(host_key="betty", container_key="plex")
        .one()
    )
    assert override.group_id == ai.id

    effective = client.get("/api/container-groups/effective").get_json()
    membership = next(m for m in effective["memberships"] if m["app_id"] == plex.id)
    assert membership["group_id"] == ai.id
    assert membership["match"] == "override"

    reverted = client.delete(
        "/api/container-groups/assignments",
        json={"app_id": plex.id},
        headers=ADMIN_HEADERS,
    )
    assert reverted.status_code == 200
    assert reverted.get_json()["reverted"] is True
    assert reverted.get_json()["data"]["group_id"] == media.id
    assert db.session.query(ContainerGroupOverride).filter_by(container_key="plex").count() == 0


def test_explicit_ungrouped_override(app, client):
    _seed(app)
    plex = _app("Plex")

    response = client.put(
        "/api/container-groups/assignments",
        json={"app_id": plex.id, "group_id": None},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["match"] == "ungrouped"
    assert response.get_json()["data"]["group_id"] is None

    management = client.get("/api/container-groups/management").get_json()
    row = next(item for item in management["apps"] if item["app_id"] == plex.id)
    assert row["override"] is True
    assert row["explicit_ungrouped"] is True
    assert row["group_id"] is None


def test_assignment_host_and_archive_validation(app, client):
    _seed(app)
    extra = _app("Extra App")
    archived = client.post(
        "/api/container-groups",
        json={"name": "Archive Me", "host_key": "betty"},
        headers=ADMIN_HEADERS,
    ).get_json()["data"]
    client.put(
        f"/api/container-groups/{archived['id']}",
        json={"active": False},
        headers=ADMIN_HEADERS,
    )
    blackbox_group = client.post(
        "/api/container-groups",
        json={"name": "Blackbox Only", "host_key": "blackbox"},
        headers=ADMIN_HEADERS,
    ).get_json()["data"]

    assert client.put(
        "/api/container-groups/assignments",
        json={"app_id": extra.id, "group_id": archived["id"]},
        headers=ADMIN_HEADERS,
    ).status_code == 400
    assert client.put(
        "/api/container-groups/assignments",
        json={"app_id": extra.id, "group_id": blackbox_group["id"]},
        headers=ADMIN_HEADERS,
    ).status_code == 400
    assert client.put(
        "/api/container-groups/assignments",
        json={"app_id": 99999, "group_id": None},
        headers=ADMIN_HEADERS,
    ).status_code == 400


def test_container_recreation_keeps_override_identity(app, client):
    _seed(app)
    manual = client.post(
        "/api/container-groups",
        json={"name": "Keep Me", "host_key": "betty"},
        headers=ADMIN_HEADERS,
    ).get_json()["data"]
    plex = _app("Plex")
    client.put(
        "/api/container-groups/assignments",
        json={"app_id": plex.id, "group_id": manual["id"]},
        headers=ADMIN_HEADERS,
    )

    # Recreate the app with the same host-scoped name and a new database id.
    db.session.delete(plex)
    db.session.commit()
    docker = db.session.query(VM).filter_by(name="Docker", hardware_id=_hardware_id("Betty")).one()
    replacement = AppService(name="Plex", vm_id=docker.id)
    db.session.add(replacement)
    db.session.commit()

    effective = client.get("/api/container-groups/effective").get_json()
    membership = next(
        item for item in effective["memberships"] if item["app_id"] == replacement.id
    )
    assert membership["group_id"] == manual["id"]


def _hardware_id(name):
    return db.session.query(Hardware).filter_by(name=name).one().id


def test_reimport_preserves_manual_override(app, client):
    _seed(app)
    ai = _group("AI")
    plex = _app("Plex")
    client.put(
        "/api/container-groups/assignments",
        json={"app_id": plex.id, "group_id": ai.id},
        headers=ADMIN_HEADERS,
    )

    import_folderview(
        {
            "folder-ai": _folder("AI", ["open-webui", "missing-one"]),
            "folder-media": _folder("Media", ["plex", "extra-app"]),
        },
        host_key="Betty",
    )

    override = (
        db.session.query(ContainerGroupOverride)
        .filter_by(host_key="betty", container_key="plex")
        .one()
    )
    assert override.group_id == ai.id
    effective = client.get("/api/container-groups/effective").get_json()
    membership = next(m for m in effective["memberships"] if m["app_id"] == plex.id)
    assert membership["group_id"] == ai.id
    assert membership["match"] == "override"


def test_sync_dry_run_and_apply(app, client, folder_fixture, tmp_path):
    _seed(app)
    db.session.query(ContainerGroupOverride).delete()
    db.session.query(ContainerGroupAssignment).delete()
    db.session.query(ContainerGroup).delete()
    db.session.commit()
    source = tmp_path / "docker.json"
    source.write_text(json.dumps(folder_fixture("simple.json")), encoding="utf-8")
    app.config["FOLDERVIEW_CONFIG_PATH"] = str(source)

    preview = client.post(
        "/api/container-groups/sync",
        json={"host_key": "Betty", "dry_run": True},
        headers=ADMIN_HEADERS,
    )
    assert preview.status_code == 200
    assert preview.get_json()["dry_run"] is True
    assert preview.get_json()["groups"]["created"] == 3
    assert db.session.query(ContainerGroup).count() == 0

    applied = client.post(
        "/api/container-groups/sync",
        json={"host_key": "Betty", "dry_run": False},
        headers=ADMIN_HEADERS,
    )
    assert applied.status_code == 200
    assert applied.get_json()["dry_run"] is False
    assert db.session.query(ContainerGroup).count() == 3

    repeat = client.post(
        "/api/container-groups/sync",
        json={"host_key": "Betty", "dry_run": True},
        headers=ADMIN_HEADERS,
    )
    assert repeat.get_json()["groups"]["created"] == 0
    assert repeat.get_json()["groups"]["unchanged"] == 3


def test_sync_is_protected_and_requires_a_configured_path(app, client):
    _seed(app)
    assert client.post(
        "/api/container-groups/sync",
        json={"host_key": "Betty", "dry_run": True},
    ).status_code == 401
    app.config["FOLDERVIEW_CONFIG_PATH"] = None
    assert client.post(
        "/api/container-groups/sync",
        json={"host_key": "Betty", "dry_run": True},
        headers=ADMIN_HEADERS,
    ).status_code == 503


def test_sync_preserves_explicit_local_choices_and_backup(app, client):
    from app.services.group_backup import export_group_data, import_group_data
    _seed(app)
    group = _group("AI")
    response = client.put(f"/api/container-groups/{group.id}", headers=ADMIN_HEADERS,
                          json={"icon": None, "sort_order": 0, "active": False, "color": "#abcdef"})
    assert response.status_code == 200
    backup = export_group_data(db.session)
    import_group_data(db.session, backup)
    db.session.commit()
    group = _group("AI")
    source = {"folder-ai": {"name": "AI renamed", "icon": "https://example.org/image.png", "containers": ["open-webui"]}}
    report = import_folderview(source, "Betty", dry_run=True)
    assert "open-webui" in report["ungrouped_apps"]
    import_folderview(source, "Betty")
    assert group.icon is None
    assert group.sort_order == 0
    assert group.active is False
    assert group.color == "#abcdef"
    assert group.name == "AI renamed"
    assert set(json.loads(group.customisations_json)) == {"icon", "sort_order", "active"}
