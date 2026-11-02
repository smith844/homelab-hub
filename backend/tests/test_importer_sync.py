import json

import pytest

from app.models import (
    AppService,
    ContainerGroup,
    ContainerGroupAssignment,
    ContainerGroupOverride,
    Hardware,
    VM,
    db,
)
from app.services.folderview_import import (
    FolderviewImportError,
    import_folderview,
    import_folderview_file,
)
from app.services.group_identity import normalize_identity
from app.services.group_resolution import effective_group, effective_group_map


def _group(session, external_id):
    return (
        session.query(ContainerGroup)
        .filter_by(source="folderview", external_id=external_id)
        .one()
    )


def test_import_creates_groups_and_host_scoped_assignments(app, folder_fixture):
    report = import_folderview(folder_fixture("simple.json"), host_key="Betty")

    assert report["dry_run"] is False
    assert report["groups"] == {
        "created": 3,
        "updated": 0,
        "reactivated": 0,
        "unchanged": 0,
        "archived": 0,
    }
    assert report["assignments"] == {
        "added": 4,
        "moved": 0,
        "removed": 0,
        "unchanged": 0,
    }
    assert report["overrides"] == {"untouched": 0}
    # No Betty hardware exists in the test database yet.
    assert report["host"]["matched"] == []
    assert report["host"]["candidates"] == []

    groups = {group.name: group for group in db.session.query(ContainerGroup).all()}
    assert set(groups) == {"AI", "Media", "Empty"}
    assert groups["AI"].host_key == "betty"
    assert groups["AI"].external_parent_id == ""
    assert groups["Empty"].external_parent_id == "folder-media"
    assert groups["AI"].active is True

    assignments = {
        (row.host_key, row.container_key, row.container_label)
        for row in db.session.query(ContainerGroupAssignment).all()
    }
    assert assignments == {
        ("betty", "open-webui", "open-webui"),
        ("betty", "ollama", "Ollama"),
        ("betty", "plex", "plex"),
        ("betty", "sonarr", "sonarr"),
    }


def test_import_is_case_insensitive_and_idempotent(app, folder_fixture):
    data = folder_fixture("simple.json")
    import_folderview(data, host_key="BETTY")

    report = import_folderview(data, host_key="betty")

    assert report["groups"]["created"] == 0
    assert report["groups"]["unchanged"] == 3
    assert report["assignments"] == {
        "added": 0,
        "moved": 0,
        "removed": 0,
        "unchanged": 4,
    }
    assert db.session.query(ContainerGroup).count() == 3
    assert db.session.query(ContainerGroupAssignment).count() == 4

    # Original display spelling is preserved separately from the identity key.
    ollama = (
        db.session.query(ContainerGroupAssignment)
        .filter_by(host_key="betty", container_key="ollama")
        .one()
    )
    assert ollama.container_label == "Ollama"
    assert ollama.host_key == normalize_identity("Betty")


def test_removing_a_container_removes_its_imported_assignment(app, folder_fixture):
    data = folder_fixture("simple.json")
    import_folderview(data, host_key="Betty")

    data["folder-ai"]["containers"].remove("Ollama")
    report = import_folderview(data, host_key="Betty")

    assert report["assignments"]["removed"] == 1
    remaining = [
        row.container_key
        for row in db.session.query(ContainerGroupAssignment).all()
    ]
    assert "ollama" not in remaining
    assert effective_group(db.session, "betty", "ollama") is None
    assert effective_group(db.session, "betty", "open-webui") is not None


def test_removed_folder_is_archived_with_history_but_has_no_effect(app, folder_fixture):
    data = folder_fixture("simple.json")
    import_folderview(data, host_key="Betty")
    media_id = _group(db.session, "folder-media").id

    del data["folder-media"]
    report = import_folderview(data, host_key="Betty")

    assert report["groups"]["archived"] == 1
    media = _group(db.session, "folder-media")
    assert media.id == media_id
    assert media.active is False
    # Historical membership is retained for the archived folder.
    retained = (
        db.session.query(ContainerGroupAssignment)
        .filter_by(group_id=media.id)
        .count()
    )
    assert retained == 2
    # Archived groups never produce effective assignments.
    assert effective_group(db.session, "betty", "plex") is None
    assert effective_group_map(db.session, "betty").get("plex") is None


def test_returning_folder_reuses_identity_and_reconciles_membership(app, folder_fixture):
    data = folder_fixture("simple.json")
    import_folderview(data, host_key="Betty")
    media_id = _group(db.session, "folder-media").id

    archived = folder_fixture("simple.json")
    del archived["folder-media"]
    import_folderview(archived, host_key="Betty")

    # While archived, "sonarr" was removed from the folder; "plex" remains.
    returning = folder_fixture("simple.json")
    returning["folder-media"]["containers"] = ["plex"]
    report = import_folderview(returning, host_key="Betty")

    assert report["groups"]["reactivated"] == 1
    assert report["assignments"]["removed"] == 1
    media = _group(db.session, "folder-media")
    assert media.id == media_id
    assert media.active is True
    assert effective_group(db.session, "betty", "plex") is not None
    assert effective_group(db.session, "betty", "sonarr") is None


def test_manual_overrides_survive_imports_and_take_precedence(app, folder_fixture):
    data = folder_fixture("simple.json")
    import_folderview(data, host_key="Betty")

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
    db.session.add(
        ContainerGroupOverride(
            group=None,
            host_key="betty",
            host_label="Betty",
            container_key="sonarr",
            container_label="sonarr",
            note="intentionally ungrouped",
        )
    )
    db.session.commit()

    report = import_folderview(data, host_key="Betty")

    assert report["overrides"] == {"untouched": 2}
    assert db.session.query(ContainerGroupOverride).count() == 2
    # The imported assignment is preserved underneath, but the override wins.
    assert effective_group(db.session, "betty", "plex").name == "My Manual Group"
    assert effective_group(db.session, "betty", "sonarr") is None

    # Archiving the imported folder does not disturb the manual choice.
    archived = folder_fixture("simple.json")
    del archived["folder-media"]
    import_folderview(archived, host_key="Betty")
    assert effective_group(db.session, "betty", "plex").name == "My Manual Group"
    assert effective_group(db.session, "betty", "sonarr") is None


def test_conflicting_memberships_are_deterministic(app, folder_fixture):
    data = folder_fixture("conflicts.json")

    first = import_folderview(data, host_key="Betty")
    assert first["conflicts"] == [
        {
            "container_key": "shared-app",
            "container_label": "shared-app",
            "kept_folder_id": "folder-a",
            "other_folder_id": "folder-b",
        }
    ]
    assignment = (
        db.session.query(ContainerGroupAssignment)
        .filter_by(host_key="betty", container_key="shared-app")
        .one()
    )
    assert assignment.group.external_id == "folder-a"

    second = import_folderview(data, host_key="Betty")
    assert second["assignments"]["unchanged"] == 3
    assert db.session.query(ContainerGroupAssignment).count() == 3


def test_dry_run_matches_real_import_and_writes_nothing(app, folder_fixture):
    data = folder_fixture("simple.json")

    dry = import_folderview(data, host_key="Betty", dry_run=True)

    assert dry["dry_run"] is True
    assert db.session.query(ContainerGroup).count() == 0
    assert db.session.query(ContainerGroupAssignment).count() == 0

    real = import_folderview(data, host_key="Betty")

    assert {key: value for key, value in dry.items() if key != "dry_run"} == {
        key: value for key, value in real.items() if key != "dry_run"
    }
    assert db.session.query(ContainerGroup).count() == 3
    assert db.session.query(ContainerGroupAssignment).count() == 4


def test_report_matches_hosts_unmatched_and_ungrouped_apps(app, folder_fixture):
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.flush()
    db.session.add(AppService(name="Open-WebUI", hardware_id=hardware.id))
    db.session.add(AppService(name="PLEX", hardware_id=hardware.id))
    db.session.add(AppService(name="Extra App", hardware_id=hardware.id))
    db.session.commit()

    report = import_folderview(folder_fixture("simple.json"), host_key="Betty")

    assert report["host"]["matched"] == [{"kind": "hardware", "name": "Betty"}]
    assert report["host"]["ambiguous"] is False
    assert report["unmatched_containers"] == ["ollama", "sonarr"]
    # "extra app" exists in inventory but is not in any imported folder.
    assert report["ungrouped_apps"] == ["extra app"]


def test_regex_is_preserved_but_never_expands_membership(app, folder_fixture):
    report = import_folderview(folder_fixture("metadata.json"), host_key="Betty")

    assert report["assignments"]["added"] == 1
    assert db.session.query(ContainerGroupAssignment).count() == 1
    group = _group(db.session, "folder-downloads")
    assert '"regex": "^arr-"' in group.metadata_json


def test_host_is_required(app, folder_fixture):
    with pytest.raises(FolderviewImportError):
        import_folderview(folder_fixture("simple.json"), host_key="   ")


def test_file_import_is_read_only(app, folder_fixture, tmp_path):
    source = tmp_path / "docker.json"
    source.write_text(
        json.dumps(folder_fixture("simple.json")),
        encoding="utf-8",
    )
    before = source.read_bytes()

    report = import_folderview_file(str(source), host_key="Betty", dry_run=True)

    assert report["dry_run"] is True
    assert source.read_bytes() == before


def test_vm_hosted_containers_match_imported_assignments(app):
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.flush()
    docker_vm = VM(name="Docker", hardware_id=hardware.id)
    db.session.add(docker_vm)
    db.session.flush()
    db.session.add(
        AppService(
            name="Home Lab Hub",
            vm_id=docker_vm.id,
            notes=(
                "## Docker configuration\n"
                "Collected: snapshot\n"
                "Container: homelab-hub\n"
                "Image: raidowl/homelab-hub:latest\n"
            ),
        )
    )
    db.session.add(
        AppService(
            name="Open-webui",
            vm_id=docker_vm.id,
            description="Docker container: open-webui",
        )
    )
    db.session.add(AppService(name="Ungrouped Tool", vm_id=docker_vm.id))
    db.session.commit()

    data = {
        "folder-tools": {
            "name": "Tools",
            "parentId": "",
            "containers": ["homelab-hub", "open-webui"],
            "regex": "",
            "settings": {},
            "actions": [],
            "updatedAt": "2026-01-01T00:00:00Z",
        }
    }

    dry = import_folderview(data, host_key="Betty", dry_run=True)

    assert dry["host"]["matched"] == [{"kind": "hardware", "name": "Betty"}]
    assert dry["unmatched_containers"] == []
    assert dry["ungrouped_apps"] == ["ungrouped tool"]
    assert db.session.query(ContainerGroup).count() == 0

    report = import_folderview(data, host_key="Betty")

    assert report["assignments"]["added"] == 2
    assert effective_group(db.session, "betty", "homelab-hub").name == "Tools"
    assert effective_group(db.session, "betty", "open-webui").name == "Tools"
    # The non-Docker app is not in the folder and stays ungrouped.
    assert effective_group(db.session, "betty", "ungrouped tool") is None


def test_non_docker_notes_do_not_match_container_assignments(app):
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.flush()
    db.session.add(
        AppService(
            name="Home Assistant",
            hardware_id=hardware.id,
            notes="Container: home-assistant\nUnrelated documentation, not a Docker snapshot.",
        )
    )
    db.session.commit()

    data = {
        "folder-x": {
            "name": "Automation",
            "parentId": "",
            "containers": ["home-assistant"],
            "regex": "",
            "settings": {},
            "actions": [],
            "updatedAt": "2026-01-01T00:00:00Z",
        }
    }

    report = import_folderview(data, host_key="Betty", dry_run=True)

    # Without a Docker configuration marker, the container-like note line is not
    # used; the app falls back to its display name and does not match.
    assert report["unmatched_containers"] == ["home-assistant"]
    assert report["ungrouped_apps"] == ["home assistant"]


def test_preview_identifies_exact_fields_and_matches_apply(app):
    source = {"a": {"name": "Tools", "icon": "https://example.org/old.png", "containers": [], "settings": {"expanded": False}}}
    import_folderview(source, "Betty")
    group = _group(db.session, "a")
    source["a"].update(name="Utilities", icon="https://example.org/new.png", updatedAt="today")
    source["a"]["settings"]["expanded"] = True
    preview = import_folderview(source, "Betty", dry_run=True)
    change = preview["group_changes"][0]
    fields = {entry["field"]: entry for entry in change["fields"]}
    assert change["external_id"] == "a"
    assert change["name"] == "Utilities"
    assert fields["name"] == {"field": "name", "before": "Tools", "after": "Utilities"}
    assert fields["source_metadata.settings.expanded"]["after"] is True
    assert fields["source_metadata.updatedAt"]["before"] is None
    assert group.name == "Tools"
    assert group.icon == "https://example.org/old.png"
    applied = import_folderview(source, "Betty")
    assert applied["group_changes"] == preview["group_changes"]
    assert group.name == "Utilities"
    assert group.icon == "https://example.org/new.png"
    assert import_folderview(source, "Betty")["group_changes"] == []


def test_legacy_customisations_survive_repeated_source_updates(app):
    source = {"a": {"name": "Tools", "icon": "https://example.org/old.png", "containers": []}}
    import_folderview(source, "Betty")
    group = _group(db.session, "a")
    group.customisations_json = None  # Simulate a pre-010 Phase 3 row.
    group.icon = "🔧"
    group.sort_order = 42
    group.color = "#123456"
    group.active = False
    db.session.commit()
    source["a"]["icon"] = "https://example.org/new.png"
    for _ in range(2):
        report = import_folderview(source, "Betty")
        assert report["groups"]["reactivated"] == 0
        assert {entry["field"] for entry in report["group_changes"][0]["preserved"]} == {"icon", "sort_order", "active"}
        assert (group.icon, group.sort_order, group.color, group.active) == ("🔧", 42, "#123456", False)
    assert json.loads(group.metadata_json)["icon"] == source["a"]["icon"]


def test_archive_changes_are_explained(app):
    import_folderview({"a": {"name": "Tools", "containers": []}}, "Betty")
    preview = import_folderview({}, "Betty", dry_run=True)
    assert preview["group_changes"] == [{"external_id": "a", "name": "Tools", "action": "archive", "fields": [{"field": "active", "before": True, "after": False}], "preserved": []}]
    assert _group(db.session, "a").active is True


def test_metadata_key_order_is_not_a_change_but_new_null_field_is(app):
    source = {"a": {"name": "Tools", "containers": []}}
    import_folderview(source, "Betty")
    reordered = {"a": {"containers": [], "name": "Tools"}}
    assert import_folderview(reordered, "Betty", dry_run=True)["groups"]["unchanged"] == 1
    source["a"]["optional"] = None
    report = import_folderview(source, "Betty", dry_run=True)
    assert report["groups"]["updated"] == 1
    assert any(field["field"] == "source_metadata.optional" for field in report["group_changes"][0]["fields"])
