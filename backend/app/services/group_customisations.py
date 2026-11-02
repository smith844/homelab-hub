"""Local choices are independent of the last imported source object."""
import json


def group_customisations(group):
    if group.customisations_json is not None:
        return set(json.loads(group.customisations_json))
    # Phase 3 did not track edits. Preserve uncertain legacy ordering and archive
    # choices rather than silently losing them. Icon edits can be inferred from
    # the last source snapshot. Once recorded, these choices survive every sync.
    fields = {"sort_order"}
    try:
        metadata = json.loads(group.metadata_json or "{}")
        source_icon = metadata.get("icon")
        source_icon = " ".join(source_icon.split()) if isinstance(source_icon, str) else None
        if (group.icon or None) != (source_icon or None):
            fields.add("icon")
    except (ValueError, AttributeError):
        fields.add("icon")
    if not group.active:
        fields.add("active")
    return fields
