#!/bin/bash
# Tears down the TRELLIS stack completely.
# Removes all containers, volumes, images, and networks created by this service.
#
# WARNING: the gitignored data/ dir (model caches ~5 GB, generated job outputs)
# is bind-mounted and NOT removed — delete it by hand if you want a clean slate.
# GLBs already copied into mcp-tools/data/generated/models/ are unaffected.
set -e

PROJECT=trellis
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Enumerate what exists ──────────────────────────────────────────────────────
CONTAINERS=$(docker compose -p "$PROJECT" ps -a \
    --format "  {{.Name}}  ({{.Status}})" 2>/dev/null || true)
VOLUMES=$(docker volume ls \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --format "  {{.Name}}" 2>/dev/null || true)
IMAGES=$(docker compose -p "$PROJECT" images 2>/dev/null \
    | awk 'NR>1 && $2!="<none>" {print "  "$2":"$3}' | sort -u || true)
NETWORKS=$(docker network ls \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --format "  {{.Name}}" 2>/dev/null || true)

# ── Show what will be removed ──────────────────────────────────────────────────
echo "══════════════════════════════════════════"
echo "  trellis — teardown"
echo "══════════════════════════════════════════"
echo ""
echo "The following Docker resources will be permanently removed:"
echo ""
echo "Containers:"
[[ -n "$CONTAINERS" ]] && echo "$CONTAINERS" || echo "  (none)"
echo ""
echo "Volumes:"
[[ -n "$VOLUMES" ]] && echo "$VOLUMES" || echo "  (none)"
echo ""
echo "Images  (the built image is ~15-20 GB):"
[[ -n "$IMAGES" ]] && echo "$IMAGES" || echo "  (none)"
echo ""
echo "Networks:"
[[ -n "$NETWORKS" ]] && echo "$NETWORKS" || echo "  (none)"
echo ""
echo "The ./data dir (model caches, job outputs) is kept — remove by hand."
echo "──────────────────────────────────────────"
echo ""
read -r -p "Proceed with teardown? [y/N] " REPLY
echo ""

if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo "Aborted — nothing was removed."
    exit 0
fi

# ── Remove everything ──────────────────────────────────────────────────────────
echo "Removing containers, volumes, images, and networks..."
docker compose -p "$PROJECT" down --volumes --rmi all --remove-orphans

echo ""
echo "Done. Re-run start.sh to create a fresh installation."
