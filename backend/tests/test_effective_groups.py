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

    open_webui = AppService(
        name="Open-webui",
        vm_id=betty_docker.id,
        notes="## Docker configuration\nContainer: open-webui\nImage: example/open-webui:latest\n",
    )
    plex = AppService(
        name="Plex",
        vm_id=betty_docker.id,
        description="Docker container: plex",
    )
    extra = AppService(name="Extra App", vm_id=betty_docker.id)
    emoncms = AppService(
        name="EmonCMS",
        vm_id=blackbox_docker.id,
        description="Docker container: emoncms",
    )
    db.session.add_all([open_webui, plex, extra, emoncms])
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


def test_effective_endpoint_reports_groups_memberships_and_unmatched(app, client):
    _seed(app)

    response = client.get("/api/container-groups/effective")
    assert response.status_code == 200
    payload = response.get_json()

    group_names = {(group["name"], group["host_key"]) for group in payload["groups"]}
    assert ("AI", "betty") in group_names
    assert ("Media", "betty") in group_names
    assert ("Monitoring", "blackbox") in group_names

    memberships = {
        (m["host_key"], m["container_key"]): m for m in payload["memberships"]
    }
    assert memberships[("betty", "open-webui")]["group_id"] == next(
        group["id"] for group in payload["groups"] if group["name"] == "AI"
    )
    assert memberships[("betty", "plex")]["app_id"] is not None
    assert memberships[("blackbox", "emoncms")]["app_id"] is not None

    unmatched = {(u["host_key"], u["container_key"]) for u in payload["unmatched"]}
    assert unmatched == {("betty", "missing-one")}
    assert payload["unmatched_count"] == 1

    ungrouped = {
        (entry["host_key"], entry["app_id"]) for entry in payload["ungrouped_apps"]
    }
    extra = (
        db.session.query(AppService).filter_by(name="Extra App").one()
    )
    assert ("betty", extra.id) in ungrouped
    # Betty's memberships never leak into Blackbox's host scope.
    assert all(m["host_key"] != "blackbox" for m in payload["memberships"] if m["container_key"] == "plex")


def test_effective_endpoint_honours_overrides_and_explicit_ungrouped(app, client):
    _seed(app)
    media = db.session.query(ContainerGroup).filter_by(name="Media").one()
    manual = ContainerGroup(name="Manual", source="manual")
    db.session.add(manual)
    db.session.flush()

    open_webui = db.session.query(AppService).filter_by(name="Open-webui").one()
    plex = db.session.query(AppService).filter_by(name="Plex").one()
    db.session.add(
        ContainerGroupOverride(
            group=manual,
            host_key="betty",
            host_label="Betty",
            container_key="open-webui",
            container_label="open-webui",
        )
    )
    db.session.add(
        ContainerGroupOverride(
            group=None,
            host_key="betty",
            host_label="Betty",
            container_key="plex",
            container_label="plex",
        )
    )
    db.session.commit()

    payload = client.get("/api/container-groups/effective").get_json()
    membership = next(
        m for m in payload["memberships"] if m["container_key"] == "open-webui"
    )
    assert membership["group_id"] == manual.id
    assert membership["match"] == "override"
    assert membership["app_id"] == open_webui.id

    assert not any(m["container_key"] == "plex" for m in payload["memberships"])
    assert any(entry["app_id"] == plex.id for entry in payload["ungrouped_apps"])


def test_effective_endpoint_excludes_archived_groups(app, client):
    _seed(app)

    import_folderview(
        {"folder-ai": _folder("AI", ["open-webui", "missing-one"])},
        host_key="Betty",
    )

    payload = client.get("/api/container-groups/effective").get_json()
    assert not any(group["name"] == "Media" for group in payload["groups"])
    # The archived folder's membership is retained in the database, but it is not
    # an effective membership and the app becomes ungrouped.
    plex = db.session.query(AppService).filter_by(name="Plex").one()
    assert not any(m["container_key"] == "plex" for m in payload["memberships"])
    assert any(entry["app_id"] == plex.id for entry in payload["ungrouped_apps"])
    assert db.session.query(ContainerGroupAssignment).filter_by(container_key="plex").count() == 1


def test_effective_endpoint_is_read_only(app, client):
    _seed(app)
    before = {
        "groups": db.session.query(ContainerGroup).count(),
        "assignments": db.session.query(ContainerGroupAssignment).count(),
        "overrides": db.session.query(ContainerGroupOverride).count(),
    }

    assert client.get("/api/container-groups/effective").status_code == 200

    after = {
        "groups": db.session.query(ContainerGroup).count(),
        "assignments": db.session.query(ContainerGroupAssignment).count(),
        "overrides": db.session.query(ContainerGroupOverride).count(),
    }
    assert after == before


def test_map_graph_endpoint_is_unchanged(app, client):
    _seed(app)

    payload = client.get("/api/map/graph").get_json()

    assert set(payload.keys()) == {"nodes", "edges"}
    for node in payload["nodes"]:
        assert "group" not in node["data"]
        assert "group_id" not in node["data"]
