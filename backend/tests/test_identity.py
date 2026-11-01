from app.models import AppService, Hardware, VM, db
from app.services.group_identity import (
    app_identity,
    app_identities,
    display_identity,
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


def test_app_identity_uses_vm_name(app):
    hardware = Hardware(name="Betty")
    db.session.add(hardware)
    db.session.flush()
    vm = VM(name="Docker VM", hardware_id=hardware.id)
    db.session.add(vm)
    db.session.flush()
    app_row = AppService(name="Ollama", vm_id=vm.id)
    db.session.add(app_row)
    db.session.commit()

    assert app_identity(app_row) == ("docker vm", "Docker VM", "ollama", "Ollama")


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
