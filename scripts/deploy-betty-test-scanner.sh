#!/usr/bin/env bash
# Build and run ONLY the HomeLab-Hub TEST Nmap scanner.
# Never touches the original port-8000 installation or the existing
# homelab-hub-scanner container. No host port is published.
set -Eeuo pipefail

SOURCE_DIR="/mnt/cache/appdata/homelab-hub-redesign-source"
CONFIG_DIR="/mnt/cache/appdata/homelab-hub-redesign-config"
SCANNER_ENV="$CONFIG_DIR/scanner-test.env"
NETWORK="homelab-hub-nmap-test-net"
CONTAINER="homelab-hub-nmap-test"
BRANCH="feature/homelab-redesign"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

ensure_network() {
    if docker network inspect "$NETWORK" >/dev/null 2>&1; then
        [[ "$(docker network inspect -f '{{.Driver}}' "$NETWORK")" == "bridge" ]] \
            || fail "Docker network '$NETWORK' exists but is not a bridge network"
    else
        printf 'Creating private scanner network %s...\n' "$NETWORK"
        docker network create --driver bridge "$NETWORK" >/dev/null \
            || fail "Could not create private scanner network '$NETWORK'"
    fi
}

command -v git >/dev/null && command -v docker >/dev/null || fail "git and docker are required"
[[ -d "$SOURCE_DIR/.git" ]] || fail "Missing Git checkout: $SOURCE_DIR"
[[ -r "$SCANNER_ENV" ]] || fail "Missing private scanner environment file: $SCANNER_ENV"
[[ "$(stat -c %a "$SCANNER_ENV")" == 600 ]] || fail "Use chmod 600 on $SCANNER_ENV"
grep -q '^HLH_SCANNER_TOKEN=..*' "$SCANNER_ENV" || fail "Scanner token missing from $SCANNER_ENV"
grep -q '^HLH_SCANNER_APPROVED_RANGES=..*' "$SCANNER_ENV" || fail "Approved ranges missing from $SCANNER_ENV"

ensure_network
cd "$SOURCE_DIR"
[[ "$(git branch --show-current)" == "$BRANCH" ]] || fail "Checkout must be on $BRANCH"
git diff --quiet && git diff --cached --quiet || fail "Tracked source changes exist. Commit/stash first"
printf 'Updating %s...\n' "$BRANCH"
git fetch origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"
SHA="$(git rev-parse --short=12 HEAD)"
IMAGE="homelab-hub-nmap-test:rev-$SHA"
printf 'Building scanner image %s...\n' "$IMAGE"
docker build -t "$IMAGE" "$SOURCE_DIR/scanner"

if docker inspect "$CONTAINER" >/dev/null 2>&1; then
    printf 'Replacing existing test scanner container %s...\n' "$CONTAINER"
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    docker rm "$CONTAINER" >/dev/null || fail "Could not remove existing scanner container"
fi

printf 'Starting %s on private network %s (no published host port)...\n' "$CONTAINER" "$NETWORK"
docker run -d \
    --name "$CONTAINER" \
    --network "$NETWORK" \
    --cap-drop ALL \
    --cap-add NET_RAW \
    --read-only \
    --tmpfs /tmp \
    --security-opt no-new-privileges \
    --env-file "$SCANNER_ENV" \
    --env HLH_SCANNER_BIND=0.0.0.0 \
    --env HLH_SCANNER_PORT=8791 \
    --restart unless-stopped \
    "$IMAGE" >/dev/null \
    || fail "Scanner container failed to start; inspect docker logs $CONTAINER"

printf 'Checking scanner health...\n'
healthy=0
for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" python -c \
        'import json,urllib.request; print(json.load(urllib.request.urlopen("http://127.0.0.1:8791/health", timeout=3))["status"])' \
        >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 1
done
if [[ "$healthy" != 1 ]]; then
    docker logs --tail 80 "$CONTAINER" >&2 || true
    fail "Scanner health check failed. Container retained for diagnosis; do not expose it publicly."
fi
[[ -z "$(docker port "$CONTAINER")" ]] || fail "Scanner unexpectedly publishes a host port; remove and fix the deployment"
docker inspect -f '{{json .NetworkSettings.Networks}}' "$CONTAINER" | grep -q "\"$NETWORK\"" \
    || fail "Scanner is not attached to $NETWORK"

printf '\nSUCCESS: test scanner %s is running on private network %s\n' "$CONTAINER" "$NETWORK"
printf 'Image: %s\n' "$IMAGE"
printf 'No host port is published. Health is available only from the Docker network.\n'
printf 'Next: deploy the web test instance with scripts/deploy-betty-test.sh\n'
