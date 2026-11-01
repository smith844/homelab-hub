from app.models import AppService, Hardware, VM, db
from app.services.group_identity import (
    app_identity,
    app_identities,
    display_identity,
    docker_container_name,
    host_candidates,
    matching_hosts,
    normalize_identity,
)


def test_normalize_identity_is_case_and_whitespace_insensitive():
    assert normalize_identity("  Betty  ") == "betty"
    assert normalize_identity("Open-WebUI") == normalize_identity("open-webui")
    assert normalize_identity("My   Host") == "my host"
    assert normalize_identity(None) == ""
    assert display_identity("  Open-WebUI  ") == "Open-WebUI"


def test_app_identity_uses_hardware_name(app):
    hardware = Hardware(name="Betty", hostname="betty.local")
    db.session.add(hardware)
    db.session.flush()
    app_row = AppService(name="Open-WebUI", hardware_id=hardware.id)
    db.session.add(app_row)
    db.session.commit()

    assert app_identity(app_row) == ("betty", "Betty", "open-webui", "Open-WebUI")


def test_app_identity_uses_root_hardware_for_vm_hosted_app(app):
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.flush()
    vm = VM(name="Docker", hardware_id=hardware.id)
    db.session.add(vm)
    db.session.flush()
    app_row = AppService(name="Ollama", vm_id=vm.id)
    db.session.add(app_row)
    db.session.commit()

    # The VM is called "Docker"; the host is still the physical host Betty.
    assert app_identity(app_row) == ("betty", "Betty", "ollama", "Ollama")


def test_docker_vms_on_different_hardware_are_scoped_by_hardware(app):
    betty = Hardware(name="Betty")
    blackbox = Hardware(name="Blackbox")
    db.session.add_all([betty, blackbox])
    db.session.flush()
    betty_docker = VM(name="Docker", hardware_id=betty.id)
    blackbox_docker = VM(name="Docker", hardware_id=blackbox.id)
    db.session.add_all([betty_docker, blackbox_docker])
    db.session.flush()
    betty_app = AppService(name="Plex", vm_id=betty_docker.id)
    blackbox_app = AppService(name="Portainer CE", vm_id=blackbox_docker.id)
    db.session.add_all([betty_app, blackbox_app])
    db.session.commit()

    assert app_identity(betty_app)[0] == "betty"
    assert app_identity(blackbox_app)[0] == "blackbox"
    assert app_identity(betty_app)[0] != app_identity(blackbox_app)[0]


def test_container_name_is_read_from_structured_notes(app):
    app_row = AppService(
        name="Home Lab Hub",
        notes=(
            "## Docker configuration\n"
            "Collected: snapshot\n"
            "Container: homelab-hub\n"
            "Image: raidowl/homelab-hub:latest\n"
        ),
    )

    assert docker_container_name(app_row) == "homelab-hub"
    assert app_identity(app_row)[2:] == ("homelab-hub", "homelab-hub")


def test_container_name_falls_back_to_docker_description(app):
    app_row = AppService(
        name="Docker Socket Proxy",
        description="Docker container: dockersocket",
    )

    assert docker_container_name(app_row) == "dockersocket"
    assert app_identity(app_row)[2:] == ("dockersocket", "dockersocket")


def test_container_name_falls_back_to_display_name(app):
    app_row = AppService(
        name="My Service",
        description="Just a description",
        notes="Unrelated notes",
    )

    assert docker_container_name(app_row) is None
    assert app_identity(app_row)[2:] == ("my service", "My Service")


def test_docker_section_without_container_line_uses_description(app):
    app_row = AppService(
        name="Display Name",
        notes="## Docker configuration\nImage: example/image:latest\n",
        description="Docker container: explicit-name",
    )

    assert docker_container_name(app_row) == "explicit-name"


def test_notes_without_docker_section_are_not_container_metadata(app):
    app_row = AppService(
        name="Home Assistant",
        description="nginx",
        notes="Container: not-a-docker-container\nSome unrelated notes",
    )

    # No Docker configuration marker and no explicit Docker description, so the
    # app is treated as an ordinary app using its display name.
    assert docker_container_name(app_row) is None
    assert app_identity(app_row)[2:] == ("home assistant", "Home Assistant")


def test_container_name_normalisation_is_case_insensitive(app):
    app_row = AppService(
        name="Display Name",
        notes="## DOCKER CONFIGURATION\nContainer: Homelab-Hub\n",
    )

    assert app_identity(app_row)[2:] == ("homelab-hub", "Homelab-Hub")


def test_standalone_app_identity_uses_empty_host(app):
    app_row = AppService(name="Standalone")
    db.session.add(app_row)
    db.session.commit()

    assert app_identity(app_row) == ("", "", "standalone", "Standalone")


def test_app_identities_covers_every_app(app):
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.flush()
    db.session.add(AppService(name="Plex", hardware_id=hardware.id))
    db.session.add(AppService(name="Loose"))
    db.session.commit()

    identities = app_identities(db.session)
    assert {(entry["host_key"], entry["container_key"]) for entry in identities} == {
        ("betty", "plex"),
        ("", "loose"),
    }


def test_matching_hosts_is_case_insensitive_and_includes_vms(app):
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.flush()
    db.session.add(VM(name="BETTY", hardware_id=hardware.id))
    db.session.commit()

    matches = matching_hosts(db.session, normalize_identity("betty"))
    assert matches == [
        {"kind": "hardware", "name": "Betty"},
        {"kind": "vm", "name": "BETTY"},
    ]
    assert host_candidates(db.session) == ["BETTY", "Betty"]
