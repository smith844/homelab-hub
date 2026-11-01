"""Host-scoped container identity helpers.

Identity keys are case-insensitive and whitespace-normalised so that the same
value is used for storage, SQLite uniqueness constraints and resolution.
Original spelling is preserved separately for display.

The host identity always comes from the app's root Hardware ancestor (an app may
run on a VM whose parent is the physical/Unraid host), and the container identity
uses the Docker container name recorded in the scanner snapshot when available.
"""

import re

STANDALONE_HOST_KEY = ""

_WHITESPACE_RE = re.compile(r"\s+")
_DOCKER_SECTION_RE = re.compile(r"docker configuration", re.IGNORECASE)
_CONTAINER_LINE_RE = re.compile(r"(?m)^\s*Container:\s*(\S+)\s*$")
_DOCKER_DESCRIPTION_RE = re.compile(r"^Docker container:\s*(\S+)\s*$")


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


def docker_container_name(app):
    """Return the recorded Docker container name, or ``None`` for non-Docker apps.

    Only the scanner's structured Docker snapshot is trusted: a notes block that
    identifies itself as Docker configuration (``## Docker configuration``) with
    a ``Container: <name>`` entry, or an explicit ``Docker container: <name>``
    description. Unrelated notes/descriptions fall through to ``None`` so
    ordinary apps are not mistaken for Docker containers.
    """
    notes = app.notes or ""
    if _DOCKER_SECTION_RE.search(notes):
        match = _CONTAINER_LINE_RE.search(notes)
        if match:
            return match.group(1).strip()

    description = (app.description or "").strip()
    match = _DOCKER_DESCRIPTION_RE.match(description)
    if match:
        return match.group(1).strip()

    return None


def root_hardware(app):
    """Return the Hardware a container ultimately runs on (app → VM → Hardware)."""
    if getattr(app, "hardware_id", None) and app.hardware is not None:
        return app.hardware
    if getattr(app, "vm_id", None) and app.vm is not None:
        return app.vm.hardware
    return None


def app_identity(app):
    """Return ``(host_key, host_label, container_key, container_label)`` for an app.

    Host identity is scoped to the root Hardware (so containers under a VM named
    "Docker" on Betty resolve to ``betty``, not ``docker``). Container identity
    prefers the recorded Docker container name, then falls back to the app's
    display name.
    """
    hardware = root_hardware(app)
    host_label = hardware.name if hardware is not None else ""
    recorded_name = docker_container_name(app)
    container_label = display_identity(recorded_name or app.name)
    return (
        normalize_identity(host_label),
        display_identity(host_label),
        normalize_identity(recorded_name or app.name),
        container_label,
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
