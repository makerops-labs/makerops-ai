#!/bin/bash
# Tears down the alexa-bridge stack completely.
# Removes all containers, volumes, images, and networks created by this
# service. This is a stateless service (no data volumes) — the only real
# loss is having to re-set ALEXA_SKILL_APPLICATION_ID / APPROVALS_TOKEN in
# a fresh .env after re-running start.sh.
set -e

PROJECT=alexa-bridge
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONTAINERS=$(docker compose -p "$PROJECT" ps -a \
    --format "  {{.Name}}  ({{.Status}})" 2>/dev/null || true)
IMAGES=$(docker compose -p "$PROJECT" images 2>/dev/null \
    | awk 'NR>1 && $2!="<none>" {print "  "$2":"$3}' | sort -u || true)
NETWORKS=$(docker network ls \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --format "  {{.Name}}" 2>/dev/null || true)

echo "══════════════════════════════════════════"
echo "  alexa-bridge — teardown"
echo "══════════════════════════════════════════"
echo ""
echo "The following Docker resources will be permanently removed:"
echo ""
echo "Containers:"
[[ -n "$CONTAINERS" ]] && echo "$CONTAINERS" || echo "  (none)"
echo ""
echo "Images:"
[[ -n "$IMAGES" ]] && echo "$IMAGES" || echo "  (none)"
echo ""
echo "Networks:"
[[ -n "$NETWORKS" ]] && echo "$NETWORKS" || echo "  (none)"
echo ""
echo "NOTE: this stops Alexa voice control until start.sh is run again AND"
echo "the Cloudflare Tunnel (makerops-core/remote_access/cloudflared/) is"
echo "still pointed at this service's port."
echo "──────────────────────────────────────────"
echo ""
read -r -p "Proceed with teardown? [y/N] " REPLY
echo ""

if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo "Aborted — nothing was removed."
    exit 0
fi

echo "Removing containers, images, and networks..."
docker compose -p "$PROJECT" down --rmi all --remove-orphans

echo ""
echo "Done. Re-run start.sh to create a fresh installation."
