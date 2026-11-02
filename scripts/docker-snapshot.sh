#!/usr/bin/env bash
# Read-only Docker inventory snapshot exporter for HomeLab-Hub.
#
# Emits the Phase 4 container snapshot contract (schema_version 1) from the
# Docker CLI. It never imports or applies changes: the resulting JSON is loaded
# manually into the Reconciliation page by an operator.
#
# Requirements on the Docker host: bash 4+, docker, jq. No Python is required,
# and the Docker socket stays with this host-side script (never the web app).
#
# Exit codes:
#   0  complete all-container snapshot written
#   1  unexpected script failure
#   2  invalid usage/configuration or missing jq (no snapshot written)
#   3  Docker collection failed; an explicit status=failed snapshot was written
#   4  snapshot could not be written atomically (existing file left untouched)
set -Eeuo pipefail
umask 022

DEFAULT_SOURCE="docker-snapshot.sh v1 (docker ps --all + docker inspect)"
HOST_KEY="${HLH_HOST_KEY:-}"
OUTPUT="${HLH_SNAPSHOT_OUTPUT:-}"
DOCKER_BIN="${HLH_DOCKER_BIN:-docker}"
JQ_BIN="${HLH_JQ_BIN:-jq}"
SOURCE="${HLH_SNAPSHOT_SOURCE:-$DEFAULT_SOURCE}"
ERROR_FILE=""
TMP_FILE=""

usage() {
    cat <<'EOF'
Read-only Docker inventory snapshot exporter (HomeLab-Hub schema_version 1).

Usage:
  docker-snapshot.sh --host-key <root-hardware-host> [options]

Required:
  --host-key <name>   HomeLab-Hub root hardware host this Docker daemon belongs
                      to (for example "betty"). Must match the host selected on
                      the Reconciliation page; matching is case-insensitive.

Options:
  --output <path>     Snapshot file path. Default:
                      docker-snapshot-<host>-<UTC timestamp>.json
  --source <text>     Snapshot source label recorded in the file.
  --docker-bin <path> Docker CLI to run (default: docker, or $HLH_DOCKER_BIN).
  --jq-bin <path>     jq executable to use (default: jq, or $HLH_JQ_BIN).
  -h, --help          Show this help.

Environment alternatives: HLH_HOST_KEY, HLH_SNAPSHOT_OUTPUT,
HLH_DOCKER_BIN, HLH_JQ_BIN, HLH_SNAPSHOT_SOURCE.

The export contains only each container's name, container ID, image ID and
image reference. Environment variables, labels, mounts, ports and credentials
are never read into the output. Running and stopped containers are included.

On failure the script writes an explicit status=failed, complete=false,
coverage=unknown snapshot (empty container list) and exits 3, so a failed or
partial collection can never be mistaken for an authoritative complete scan.
EOF
}

cleanup() {
    [[ -n "$TMP_FILE" && -e "$TMP_FILE" ]] && rm -f -- "$TMP_FILE"
    [[ -n "$ERROR_FILE" && -e "$ERROR_FILE" ]] && rm -f -- "$ERROR_FILE"
    return 0
}
trap cleanup EXIT

usage_error() {
    printf 'ERROR: %s\n\n' "$*" >&2
    usage >&2
    exit 2
}

trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

first_line() {
    local value=""
    if [[ -r "$ERROR_FILE" ]]; then
        IFS= read -r value < "$ERROR_FILE" || true
    fi
    value="${value//$'\r'/ }"
    value="${value//$'\n'/ }"
    # Keep the diagnostic short and strip control characters.
    value="${value//[[:cntrl:]]/ }"
    [[ -n "$value" ]] || value="no diagnostic output"
    printf '%s' "${value:0:300}"
}

# Validate a candidate snapshot, then replace the destination atomically.
# The previous output file is preserved if the new payload is invalid.
write_snapshot() {
    local payload="$1"
    local out_dir
    out_dir="$(dirname -- "$OUTPUT")"
    [[ -d "$out_dir" ]] || { printf 'ERROR: output directory does not exist: %s\n' "$out_dir" >&2; exit 2; }

    TMP_FILE="$(mktemp "${OUTPUT}.tmp.XXXXXX")" || {
        printf 'ERROR: cannot create a temporary file next to %s\n' "$OUTPUT" >&2
        exit 4
    }
    printf '%s\n' "$payload" > "$TMP_FILE"

    if ! "$JQ_BIN" -e '
        type == "object" and
        (.schema_version == 1) and
        (.host_key | type == "string" and length > 0 and length <= 128) and
        (.source | type == "string" and length > 0) and
        (.status == "success" or .status == "failed" or .status == "unknown") and
        (.complete | type == "boolean") and
        (.coverage == "all_containers" or .coverage == "running_only" or .coverage == "unknown") and
        (.completed_at | type == "string" and
            test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
        (.containers | type == "array") and
        (if .status == "success"
         then (.complete == true and .coverage == "all_containers")
         else true end) and
        all(.containers[];
            (type == "object") and
            (.container_name | type == "string" and
                test("^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")) and
            (.container_id | type == "string" and length > 0) and
            (.image_id | type == "string" and length > 0) and
            (.image | type == "string" and length > 0))
    ' "$TMP_FILE" >/dev/null; then
        printf 'ERROR: generated snapshot failed validation; %s was left unchanged\n' "$OUTPUT" >&2
        exit 4
    fi

    mv -f -- "$TMP_FILE" "$OUTPUT" || {
        printf 'ERROR: could not replace %s atomically\n' "$OUTPUT" >&2
        exit 4
    }
    TMP_FILE=""
}

# Emit a failed snapshot. It deliberately reports no containers so that a
# stopped or otherwise uncollected container cannot be inferred as absent.
failed_snapshot() {
    local message="$1"
    local completed_at payload

    message="${message//[[:cntrl:]]/ }"
    completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    payload="$("$JQ_BIN" -n \
        --arg host "$HOST_KEY" \
        --arg source "$SOURCE" \
        --arg completed_at "$completed_at" \
        --arg error "${message:0:300}" \
        '{schema_version: 1,
          host_key: $host,
          source: $source,
          status: "failed",
          complete: false,
          coverage: "unknown",
          completed_at: $completed_at,
          containers: [],
          error: $error}')" || {
        printf 'ERROR: could not build the failed snapshot payload\n' >&2
        exit 1
    }
    write_snapshot "$payload"
    printf 'Collection failed: %s\nWrote explicit failed snapshot: %s\n' "$message" "$OUTPUT" >&2
    exit 3
}

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
while (( $# )); do
    case "$1" in
        --host-key)
            (( $# >= 2 )) || usage_error "--host-key requires a value"
            HOST_KEY="$2"; shift 2 ;;
        --host-key=*)
            HOST_KEY="${1#*=}"; shift ;;
        --output)
            (( $# >= 2 )) || usage_error "--output requires a value"
            OUTPUT="$2"; shift 2 ;;
        --output=*)
            OUTPUT="${1#*=}"; shift ;;
        --source)
            (( $# >= 2 )) || usage_error "--source requires a value"
            SOURCE="$2"; shift 2 ;;
        --source=*)
            SOURCE="${1#*=}"; shift ;;
        --docker-bin)
            (( $# >= 2 )) || usage_error "--docker-bin requires a value"
            DOCKER_BIN="$2"; shift 2 ;;
        --docker-bin=*)
            DOCKER_BIN="${1#*=}"; shift ;;
        --jq-bin)
            (( $# >= 2 )) || usage_error "--jq-bin requires a value"
            JQ_BIN="$2"; shift 2 ;;
        --jq-bin=*)
            JQ_BIN="${1#*=}"; shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            usage_error "Unknown argument: $1" ;;
    esac
done

HOST_KEY="$(trim "$HOST_KEY")"
SOURCE="$(trim "$SOURCE")"
[[ -n "$HOST_KEY" ]] || usage_error "--host-key is required (the HomeLab-Hub root hardware host)"
[[ ${#HOST_KEY} -le 128 ]] || usage_error "--host-key must be 128 characters or fewer"
host_pattern='^[A-Za-z0-9]([A-Za-z0-9._ -]*[A-Za-z0-9._-])?$'
[[ "$HOST_KEY" =~ $host_pattern ]] \
    || usage_error "--host-key must start and end with a letter, digit, dot, underscore or hyphen"
[[ -n "$SOURCE" ]] || usage_error "--source must not be empty"
[[ "${SOURCE//[[:cntrl:]]/}" == "$SOURCE" && ${#SOURCE} -le 200 ]] \
    || usage_error "--source must be printable and at most 200 characters"
command -v "$JQ_BIN" >/dev/null 2>&1 || {
    printf 'ERROR: jq not found (%s). Install jq (Unraid: NerdTools package) or pass --jq-bin.\n' "$JQ_BIN" >&2
    exit 2
}
if [[ -z "$OUTPUT" ]]; then
    safe_host="${HOST_KEY,,}"
    safe_host="${safe_host//[^a-z0-9._-]/-}"
    OUTPUT="docker-snapshot-${safe_host}-$(date -u +%Y%m%dT%H%M%SZ).json"
fi
[[ -d "$(dirname -- "$OUTPUT")" ]] || {
    printf 'ERROR: output directory does not exist: %s\n' "$(dirname -- "$OUTPUT")" >&2
    exit 2
}

ERROR_FILE="$(mktemp "${TMPDIR:-/tmp}/hlh-docker-snapshot.XXXXXX")"

# ---------------------------------------------------------------------------
# Collection: docker ps --all (running and stopped) then one docker inspect.
# ---------------------------------------------------------------------------
command -v "$DOCKER_BIN" >/dev/null 2>&1 \
    || failed_snapshot "Docker CLI not found: $DOCKER_BIN"

if ! ids_raw="$("$DOCKER_BIN" ps --all --quiet --no-trunc 2>"$ERROR_FILE")"; then
    failed_snapshot "docker ps failed: $(first_line)"
fi

ids=()
while IFS= read -r id; do
    id="${id//[[:space:]]/}"
    [[ -z "$id" ]] && continue
    [[ "$id" =~ ^[0-9a-fA-F]{12,64}$ ]] \
        || failed_snapshot "docker ps returned an unexpected container ID"
    ids+=("$id")
done <<< "$ids_raw"

if (( ${#ids[@]} == 0 )); then
    containers='[]'
else
    if ! inspect_raw="$("$DOCKER_BIN" inspect --type container "${ids[@]}" 2>"$ERROR_FILE")"; then
        failed_snapshot "docker inspect failed: $(first_line)"
    fi
    "$JQ_BIN" -e 'type == "array"' >/dev/null 2>&1 <<< "$inspect_raw" \
        || failed_snapshot "docker inspect returned malformed JSON"

    observed="$("$JQ_BIN" 'length' <<< "$inspect_raw")" \
        || failed_snapshot "could not read the docker inspect result"
    (( observed == ${#ids[@]} )) \
        || failed_snapshot "incomplete collection: listed ${#ids[@]} containers but inspected $observed"

    # Whitelist only stable identity and image metadata. Environment, labels,
    # mounts, ports and other Docker inspect fields are discarded here.
    containers="$("$JQ_BIN" -c '
        [ .[] | {
            container_name: ((.Name // "") | tostring | ltrimstr("/")),
            container_id: ((.Id // "") | tostring),
            image_id: ((.Image // "") | tostring),
            image: ((((.Config // {}).Image) // "") | tostring)
          } ]
    ' <<< "$inspect_raw")" || failed_snapshot "could not map docker inspect fields"

    "$JQ_BIN" -e '
        all(.[];
            (.container_name | type == "string" and
                test("^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")) and
            (.container_id | type == "string" and length > 0) and
            (.image_id | type == "string" and length > 0) and
            (.image | type == "string" and length > 0))
    ' >/dev/null <<< "$containers" \
        || failed_snapshot "docker inspect returned invalid container metadata"

    duplicate="$("$JQ_BIN" -r '
        [ .[].container_name ] | group_by(.) | map(select(length > 1) | .[0]) | .[0] // empty
    ' <<< "$containers")" || failed_snapshot "could not validate container names"
    [[ -z "$duplicate" ]] \
        || failed_snapshot "docker inspect returned a duplicate container name: $duplicate"
fi

completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
payload="$("$JQ_BIN" -n \
    --arg host "$HOST_KEY" \
    --arg source "$SOURCE" \
    --arg completed_at "$completed_at" \
    --argjson containers "$containers" \
    '{schema_version: 1,
      host_key: $host,
      source: $source,
      status: "success",
      complete: true,
      coverage: "all_containers",
      completed_at: $completed_at,
      containers: $containers}')" || failed_snapshot "could not build the snapshot payload"

write_snapshot "$payload"
printf 'Wrote %s\n%s containers, complete all_containers snapshot for host %s at %s\n' \
    "$OUTPUT" "${#ids[@]}" "$HOST_KEY" "$completed_at"
