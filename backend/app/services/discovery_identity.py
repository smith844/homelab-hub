"""Discovery metadata embedded in the existing, backup-compatible notes field."""
import json
import re

MARKER = re.compile(r"<!-- hlh-discovery:v1 (\{[^\n]*\}) -->")


def discovery_metadata(notes):
    match = MARKER.search(notes or "")
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and isinstance(data.get("container_name"), str):
                return data
        except ValueError:
            pass
    return {}


def with_discovery_metadata(notes, resource):
    # Only replace our generated marker; never replace scanner/user notes.
    clean = MARKER.sub("", notes or "")
    metadata = {key: resource.get(key) for key in ("container_name", "container_id", "image_id", "image", "observed_at")}
    return clean + ("" if not clean or clean.endswith("\n") else "\n") + "<!-- hlh-discovery:v1 " + json.dumps(metadata, ensure_ascii=True, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e") + " -->"
