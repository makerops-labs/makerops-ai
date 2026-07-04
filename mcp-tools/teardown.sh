#!/bin/bash
# Tears down the mcp-tools stack completely.
# Removes all containers, volumes, images, and networks created by this service.
#
# WARNING: data volumes are permanently deleted. This cannot be undone.
# The approvals history, audit log, provenance registry, and saved diagrams
# will be lost. (Custom agents live in ai/smolagents/agents/custom/ and are
# NOT touched.)
set -e

PROJECT=mcp-tools
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
echo "  mcp-tools — teardown"
echo "══════════════════════════════════════════"
echo ""
echo "The following Docker resources will be permanently removed:"
echo ""
echo "Containers:"
[[ -n "$CONTAINERS" ]] && echo "$CONTAINERS" || echo "  (none)"
echo ""
echo "Volumes  (ALL DATA WILL BE LOST — approvals, audit log, provenance):"
[[ -n "$VOLUMES" ]] && echo "$VOLUMES" || echo "  (none)"
echo ""
echo "Images:"
[[ -n "$IMAGES" ]] && echo "$IMAGES" || echo "  (none)"
echo ""
echo "Networks:"
[[ -n "$NETWORKS" ]] && echo "$NETWORKS" || echo "  (none)"
echo ""
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
