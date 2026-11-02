#!/usr/bin/env bash
# Deploy HomeLab-Hub's TEST instance on Unraid Betty (host port 8790).
# Never touches the original port-8000 instance.
set -Eeuo pipefail

SOURCE_DIR="/mnt/cache/appdata/homelab-hub-redesign-source"
DATA_DIR="/mnt/cache/appdata/homelab-hub-redesign-data"
CONFIG_DIR="/mnt/cache/appdata/homelab-hub-redesign-config"
FOLDERVIEW="/boot/config/plugins/folderview.plus/docker.json"
CONTAINER="homelab-hub-redesign"
BRANCH="feature/homelab-redesign"
PORT="8790"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
PREVIOUS=""
NEW_STARTED=0

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command -v git >/dev/null && command -v docker >/dev/null && command -v curl >/dev/null || fail "git, docker and curl are required"
[[ -d "$SOURCE_DIR/.git" ]] || fail "Missing Git checkout: $SOURCE_DIR"
[[ -d "$DATA_DIR" && -f "$DATA_DIR/homelab-hub.db" ]] || fail "Missing persistent database; refusing to create a fresh one"
[[ -r "$FOLDERVIEW" ]] || fail "FolderView file unavailable: $FOLDERVIEW"
[[ -r "$CONFIG_DIR/phase3.env" ]] || fail "Missing private admin token environment file: $CONFIG_DIR/phase3.env"
grep -q '^HLH_ADMIN_TOKEN=' "$CONFIG_DIR/phase3.env" || fail "Admin token missing from env file"
[[ "$(stat -c %a "$CONFIG_DIR/phase3.env")" == 600 ]] || fail "Use chmod 600 on the private env file"

cd "$SOURCE_DIR"
[[ "$(git branch --show-current)" == "$BRANCH" ]] || fail "Checkout must be on $BRANCH"
git diff --quiet && git diff --cached --quiet || fail "Tracked source changes exist. Commit/stash first"
printf 'Updating %s...\n' "$BRANCH"
git fetch origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"
SHA="$(git rev-parse --short=12 HEAD)"
IMAGE="homelab-hub-redesign:rev-$SHA"
printf 'Building %s...\n' "$IMAGE"
docker build -t "$IMAGE" .

# The running container has Python and SQLite's online-backup API.
[[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" == true ]] || fail "Expected running test container '$CONTAINER' not found"
[[ "$(docker inspect -f '{{.Config.Image}}' "$CONTAINER")" == homelab-hub-redesign:* ]] || fail "Unexpected container image"
[[ "$(docker inspect -f '{{(index .HostConfig.PortBindings "8000/tcp" 0).HostPort}}' "$CONTAINER")" == "$PORT" ]] || fail "Existing port differs from expected $PORT"
BACKUP="/data/homelab-hub-before-$SHA-$STAMP.db"
printf 'Creating SQLite backup...\n'
docker exec -i -e HLH_BACKUP_PATH="$BACKUP" "$CONTAINER" python - <<'PY'
import os, sqlite3
source = sqlite3.connect("/data/homelab-hub.db")
target = sqlite3.connect(os.environ["HLH_BACKUP_PATH"])
try:
    source.backup(target)
    row = target.execute("PRAGMA integrity_check").fetchone()
    if row != ("ok",):
        raise RuntimeError(f"Backup integrity_check failed: {row}")
finally:
    target.close()
    source.close()
print("SQLite backup verified:", os.environ["HLH_BACKUP_PATH"])
PY

# Use a unique rollback container name; do not delete earlier rollback containers.
PREVIOUS="$CONTAINER-before-$SHA-$STAMP"
printf 'Stopping existing test container; preserving it as %s...\n' "$PREVIOUS"
docker stop "$CONTAINER"
docker rename "$CONTAINER" "$PREVIOUS"
# Keep the prior container stopped, including across host restarts.
docker update --restart=no "$PREVIOUS" >/dev/null

printf 'Starting new test container...\n'
if ! docker run -d \
    --name "$CONTAINER" \
    --publish "$PORT:8000" \
    --volume "$DATA_DIR:/data" \
    --mount "type=bind,source=$FOLDERVIEW,target=/config/folderview-docker.json,readonly" \
    --env-file "$CONFIG_DIR/phase3.env" \
    --env DATABASE_URL=sqlite:////data/homelab-hub.db \
    --env FLASK_ENV=production \
    --env FOLDERVIEW_CONFIG_PATH=/config/folderview-docker.json \
    --restart unless-stopped \
    "$IMAGE"; then
    fail "New container failed to start. Old stopped container: $PREVIOUS. Database may already have migrated; restore matching backup before rollback."
fi
NEW_STARTED=1

printf 'Checking application health...\n'
healthy=0
for _ in $(seq 1 30); do
    if curl --max-time 2 --silent --fail "http://127.0.0.1:$PORT/api/health" | grep -q '"status":"ok"'; then
        healthy=1
        break
    fi
    sleep 2
done
if [[ "$healthy" != 1 ]]; then
    docker logs --tail 60 "$CONTAINER" >&2 || true
    fail "Health check failed. New container remains available for diagnosis. Do NOT restart old image against an upgraded database. Backup: $DATA_DIR/$(basename "$BACKUP"); old container: $PREVIOUS"
fi
printf '\nSUCCESS: %s at http://192.168.1.80:%s/\n' "$SHA" "$PORT"
printf 'Backup: %s/%s\n' "$DATA_DIR" "$(basename "$BACKUP")"
printf 'Previous stopped container: %s\n' "$PREVIOUS"
printf 'Image: %s\n' "$IMAGE"
