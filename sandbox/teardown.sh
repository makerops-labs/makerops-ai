#!/bin/bash
# Tears down the sandbox stack completely.
# Removes the service container, its image, and the ephemeral-container
# runtime image. Host paths (WORKSPACES_ROOT) are never touched.
set -e

PROJECT=sandbox
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONTAINERS=$(docker compose -p "$PROJECT" ps -a \
    --format "  {{.Name}}  ({{.Status}})" 2>/dev/null || true)
IMAGES=$(docker compose -p "$PROJECT" images 2>/dev/null \
    | awk 'NR>1 && $2!="<none>" {print "  "$2":"$3}' | sort -u || true)
NETWORKS=$(docker network ls \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --format "  {{.Name}}" 2>/dev/null || true)
LEAKED=$(docker ps -a --filter "label=managed-by=makerops-sandbox" \
    --format "  {{.Names}}  ({{.Status}})" 2>/dev/null || true)

echo "══════════════════════════════════════════"
echo "  sandbox — teardown"
echo "══════════════════════════════════════════"
echo ""
echo "The following Docker resources will be permanently removed:"
echo ""
echo "Containers:"
[[ -n "$CONTAINERS" ]] && echo "$CONTAINERS" || echo "  (none)"
echo ""
echo "Images (service + runtime.Dockerfile):"
[[ -n "$IMAGES" ]] && echo "$IMAGES" || echo "  (none)"
echo "  makerops-sandbox-runtime:latest"
echo ""
echo "Networks:"
[[ -n "$NETWORKS" ]] && echo "$NETWORKS" || echo "  (none)"
echo ""
if [[ -n "$LEAKED" ]]; then
    echo "Ephemeral sandbox-run-* containers still present (should not"
    echo "normally happen — every request removes its own container):"
    echo "$LEAKED"
    echo ""
fi
echo "NOTE: this removes the second (and only other) service with Docker"
echo "socket access. project_run_command will fail until start.sh is run"
echo "again."
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
docker rmi makerops-sandbox-runtime:latest 2>/dev/null || true
if [[ -n "$LEAKED" ]]; then
    docker rm -f $(docker ps -aq --filter "label=managed-by=makerops-sandbox") 2>/dev/null || true
fi

echo ""
echo "Done. Re-run start.sh to create a fresh installation."
