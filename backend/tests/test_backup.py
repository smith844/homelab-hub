from app.models import ContainerGroup, ContainerGroupAssignment, ContainerGroupOverride, Hardware, db
from app.services.folderview_import import import_folderview
from app.services.group_backup import (
    export_group_data,
    group_natural_key,
    has_group_backup_data,
    import_group_data,
)


def test_export_uses_natural_keys_without_database_ids(app, folder_fixture):
    import_folderview(folder_fixture("simple.json"), host_key="Betty")
    manual = ContainerGroup(name="My Manual Group", source="manual")
    db.session.add(manual)
    db.session.flush()
    db.session.add(
        ContainerGroupOverride(
            group=manual,
            host_key="betty",
            host_label="Betty",
            container_key="plex",
            container_label="plex",
        )
    )
    db.session.commit()

    exported = export_group_data(db.session)

    assert [group["key"] for group in exported["container_groups"]] == [
        "folderview:betty:folder-ai",
        "folderview:betty:folder-empty",
        "folderview:betty:folder-media",
        "manual:my manual group",
    ]
    for entry in exported["container_groups"]:
        assert "id" not in entry
    for entry in exported["container_group_assignments"]:
        assert "id" not in entry
        assert entry["group_key"].startswith("folderview:betty:")
    for entry in exported["container_group_overrides"]:
        assert "id" not in entry
        assert entry["group_key"] == "manual:my manual group"


def test_group_backup_round_trips_without_ids(app, folder_fixture):
    import_folderview(folder_fixture("simple.json"), host_key="Betty")
    first = export_group_data(db.session)

    import_group_data(db.session, first)
    db.session.commit()
    second = export_group_data(db.session)

    assert second == first
    assert db.session.query(ContainerGroup).count() == 3
    assert db.session.query(ContainerGroupAssignment).count() == 4


def test_manual_group_natural_key_uses_normalised_name(app):
    group = ContainerGroup(name="My  Group", source="manual")
    assert group_natural_key(group) == "manual:my group"


def test_export_rejects_duplicate_manual_group_keys(app):
    db.session.add(ContainerGroup(name="My Group", source="manual"))
    db.session.add(ContainerGroup(name="my group", source="manual"))
    db.session.commit()

    try:
        export_group_data(db.session)
    except ValueError as exc:
        assert "Duplicate container group natural key" in str(exc)
    else:  # pragma: no cover - assertion helper
        raise AssertionError("expected a duplicate natural key error")


def test_import_group_data_rejects_unknown_group_key(app, folder_fixture):
    import_folderview(folder_fixture("simple.json"), host_key="Betty")
    payload = {
        "container_groups": [],
        "container_group_assignments": [
            {
                "group_key": "missing",
                "host_key": "betty",
                "container_key": "plex",
            }
        ],
        "container_group_overrides": [],
    }

    try:
        import_group_data(db.session, payload)
    except ValueError as exc:
        assert "unknown group key" in str(exc)
    else:  # pragma: no cover - assertion helper
        raise AssertionError("expected an unknown group key error")

    db.session.rollback()
    assert db.session.query(ContainerGroup).count() == 3


def test_legacy_inventory_import_leaves_grouping_untouched(app, folder_fixture, client):
    import_folderview(folder_fixture("simple.json"), host_key="Betty")
    before = export_group_data(db.session)

    response = client.post(
        "/inventory/import",
        json={
            "hardware": [],
            "vms": [],
            "apps": [],
            "storage": [],
            "networks": [],
            "misc": [],
            "documents": [],
        },
    )

    assert response.status_code == 200
    assert export_group_data(db.session) == before
    assert has_group_backup_data({"hardware": []}) is False


def test_inventory_backup_round_trip_restores_groups(app, folder_fixture, client):
    import_folderview(folder_fixture("simple.json"), host_key="Betty")
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.commit()
    before_keys = [group["key"] for group in export_group_data(db.session)["container_groups"]]

    exported = client.get("/inventory/export").get_json()
    assert "container_groups" in exported
    assert "container_group_assignments" in exported
    assert "container_group_overrides" in exported

    db.session.query(ContainerGroupAssignment).delete()
    db.session.query(ContainerGroup).delete()
    db.session.commit()
    assert db.session.query(ContainerGroup).count() == 0

    response = client.post("/inventory/import", json=exported)

    assert response.status_code == 200
    restored = export_group_data(db.session)
    assert [group["key"] for group in restored["container_groups"]] == before_keys
    assert len(restored["container_group_assignments"]) == 4
