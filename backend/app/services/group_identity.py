"""Host-scoped container identity helpers.

Identity keys are case-insensitive and whitespace-normalised so that the same
value is used for storage, SQLite uniqueness constraints and resolution.
Original spelling is preserved separately for display.
"""

import re

STANDALONE_HOST_KEY = ""

_WHITESPACE_RE = re.compile(r"\s+")


def display_identity(value):
    """Original spelling, trimmed with internal whitespace collapsed."""
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value).strip())


def normalize_identity(value):
    """Case-insensitive identity key used for storage and resolution."""
    return display_identity(value).casefold()


def identity_pair(value):
    """Return ``(normalized_key, display_label)`` for a raw value."""
    return normalize_identity(value), display_identity(value)


def app_identity(app):
    """Return ``(host_key, host_label, container_key, container_label)`` for an app.

    The host is the app's direct parent: ``Hardware.name`` when the app runs on
    hardware, otherwise ``VM.name`` when it runs on a VM. Apps without a parent
    use ``STANDALONE_HOST_KEY``.
    """
    host_label = ""
    if getattr(app, "hardware_id", None) and app.hardware is not None:
        host_label = app.hardware.name or ""
    elif getattr(app, "vm_id", None) and app.vm is not None:
        host_label = app.vm.name or ""
    return (
        normalize_identity(host_label),
        display_identity(host_label),
        normalize_identity(app.name),
        display_identity(app.name),
    )


def app_identities(session):
    """Return every app's host-scoped identity, without relying on database ids."""
    from ..models import AppService

    result = []
    for app in session.query(AppService).all():
        host_key, host_label, container_key, container_label = app_identity(app)
        result.append(
            {
                "app_id": app.id,
                "host_key": host_key,
                "host_label": host_label,
                "container_key": container_key,
                "container_label": container_label,
            }
        )
    return result


def matching_hosts(session, host_key):
    """Find Hardware/VM rows whose ``name`` matches a normalized host key."""
    from ..models import Hardware, VM

    matches = []
    for hardware in session.query(Hardware).all():
        if normalize_identity(hardware.name) == host_key:
            matches.append({"kind": "hardware", "name": display_identity(hardware.name)})
    for vm in session.query(VM).all():
        if normalize_identity(vm.name) == host_key:
            matches.append({"kind": "vm", "name": display_identity(vm.name)})
    return matches


def host_candidates(session):
    """Display names available for host resolution (used in import reports)."""
    from ..models import Hardware, VM

    names = [display_identity(hardware.name) for hardware in session.query(Hardware).all()]
    names += [display_identity(vm.name) for vm in session.query(VM).all()]
    return sorted({name for name in names if name})
