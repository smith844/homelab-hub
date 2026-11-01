"""Effective container grouping resolution.

Manual overrides always win over imported assignments, and archived groups
(``active = False``) never produce an effective assignment.
"""

from ..models import ContainerGroup, ContainerGroupAssignment, ContainerGroupOverride


def _active_group(session, group_id):
    if group_id is None:
        return None
    group = session.get(ContainerGroup, group_id)
    if group is None or not group.active:
        return None
    return group


def effective_group(session, host_key, container_key):
    """Return the effective ``ContainerGroup`` for a host-scoped container.

    Returns ``None`` when the container is ungrouped, explicitly ungrouped by an
    override, or pointed at an archived group.
    """
    override = (
        session.query(ContainerGroupOverride)
        .filter_by(host_key=host_key, container_key=container_key)
        .first()
    )
    if override is not None:
        return _active_group(session, override.group_id)

    assignment = (
        session.query(ContainerGroupAssignment)
        .filter_by(host_key=host_key, container_key=container_key)
        .first()
    )
    if assignment is None:
        return None
    return _active_group(session, assignment.group_id)


def effective_group_map(session, host_key):
    """Return ``{container_key: group}`` for containers that are effectively grouped."""
    result = {}
    for assignment in (
        session.query(ContainerGroupAssignment).filter_by(host_key=host_key).all()
    ):
        group = _active_group(session, assignment.group_id)
        if group is not None:
            result[assignment.container_key] = group
    for override in (
        session.query(ContainerGroupOverride).filter_by(host_key=host_key).all()
    ):
        group = _active_group(session, override.group_id)
        if group is None:
            result.pop(override.container_key, None)
        else:
            result[override.container_key] = group
    return result
