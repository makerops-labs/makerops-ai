#!/bin/bash
# Apply the makerops runtime patches to the running Open WebUI container.
#
# Open WebUI is the upstream `main` image with no Dockerfile of our own, so
# these are in-place edits to the container's Python source. They do NOT
# survive `docker compose ... up -d` (image recreate) — only `restart`. Re-run
# this after any pull / recreate. `start.sh` calls it automatically.
#
# Idempotent: each patch script no-ops if already applied. The container is
# restarted only if something actually changed.
set -euo pipefail

CONTAINER=openwebui
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "apply.sh: '$CONTAINER' is not running — start it first." >&2
    exit 1
fi

changed=0
for patch in "$SCRIPT_DIR"/*.py; do
    [[ -e "$patch" ]] || continue
    name="$(basename "$patch")"
    docker cp "$patch" "$CONTAINER:/tmp/$name"
    out="$(docker exec "$CONTAINER" python3 "/tmp/$name")"
    echo "  $name: $out"
    [[ "$out" == CHANGED:* ]] && changed=1
done

if [[ "$changed" == 1 ]]; then
    echo "apply.sh: restarting $CONTAINER to load patched source..."
    docker restart "$CONTAINER" >/dev/null
    echo "apply.sh: done."
else
    echo "apply.sh: nothing to do (all patches already present)."
fi
