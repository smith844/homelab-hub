import pytest

from app.services.folderview_import import FolderviewImportError, parse_folderview_config


def test_parse_preserves_folder_identity_membership_and_metadata(folder_fixture):
    parsed = parse_folderview_config(folder_fixture("simple.json"))

    assert [folder["external_id"] for folder in parsed["folders"]] == [
        "folder-ai",
        "folder-empty",
        "folder-media",
    ]

    ai, empty, media = parsed["folders"]
    assert ai["name"] == "AI"
    assert ai["parent_id"] == ""
    assert ai["containers"] == [
        {"key": "open-webui", "label": "open-webui"},
        {"key": "ollama", "label": "Ollama"},
    ]
    assert ai["metadata"]["memberIdentities"][0]["template"] == "my-open-webui.xml"
    assert ai["metadata"]["settings"] == {"color": "#123456"}

    assert empty["parent_id"] == "folder-media"
    assert empty["containers"] == []
    assert empty["metadata"]["hiddenPreviewMembers"] == ["plex"]

    assert media["name"] == "Media"
    assert parsed["conflicts"] == []


def test_parse_keeps_regex_as_metadata_without_executing_it(folder_fixture):
    parsed = parse_folderview_config(folder_fixture("metadata.json"))
    folder = parsed["folders"][0]

    assert folder["name"] == "Download Clients"
    assert folder["icon"] == "https://example.invalid/icons/downloads.png"
    assert folder["metadata"]["regex"] == "^arr-"
    assert folder["metadata"]["settings"] == {"color": "#654321", "order": 4}
    assert folder["metadata"]["actions"][0]["type"] == "start"
    assert folder["metadata"]["memberIdentities"][0]["composeProject"] == "downloads"
    assert folder["metadata"]["hiddenPreviewMembers"] == ["arr-extra"]
    # The regex is metadata only: it never adds members.
    assert [container["key"] for container in folder["containers"]] == ["sabnzbd"]


def test_parse_reports_conflicting_memberships_and_warnings(folder_fixture):
    parsed = parse_folderview_config(folder_fixture("conflicts.json"))

    assert parsed["conflicts"] == [
        {
            "container_key": "shared-app",
            "container_label": "shared-app",
            "kept_folder_id": "folder-a",
            "other_folder_id": "folder-b",
        }
    ]
    assert any("non-string container entry" in warning for warning in parsed["warnings"])
    assert [folder["name"] for folder in parsed["folders"]] == ["Alpha", "Beta"]


@pytest.mark.parametrize(
    "fixture",
    ["invalid_root.json", "invalid_folder.json", "invalid_containers.json"],
)
def test_parse_rejects_invalid_structures(folder_fixture, fixture):
    with pytest.raises(FolderviewImportError):
        parse_folderview_config(folder_fixture(fixture))


def test_parse_accepts_an_empty_configuration(folder_fixture):
    parsed = parse_folderview_config(folder_fixture("empty.json"))
    assert parsed == {"folders": [], "warnings": [], "conflicts": []}
