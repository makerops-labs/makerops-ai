#!/bin/bash
# Starts the Open WebUI service.
# Auto-generates WEBUI_SECRET_KEY on first run.
# Requires ai/ollama to be running before this service can connect to models.
set -e

PROJECT=openwebui

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── First-run: create .env from template ──────────────────────────────────────
if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# ── Secret generation ─────────────────────────────────────────────────────────
generate_if_needed() {
    local var="$1"
    local len="${2:-32}"
    if grep -q "^${var}=GENERATE_ME" .env 2>/dev/null; then
        local val
        val=$(openssl rand -hex "$len")
        sed -i "s|^${var}=GENERATE_ME|${var}=${val}|" .env
        echo "  Generated ${var}." >&2
    fi
}

generate_if_needed WEBUI_SECRET_KEY 32

# ── Pull and start ─────────────────────────────────────────────────────────────
echo "Pulling latest image..."
docker compose -p "$PROJECT" pull

echo "Starting services..."
docker compose -p "$PROJECT" up -d

# ── Runtime patches ───────────────────────────────────────────────────────────
# In-place edits to the upstream image's Python source (no Dockerfile of our
# own). Lost on image recreate/pull, so re-applied on every start. Idempotent;
# restarts the container only if a patch actually changed something.
echo "Applying runtime patches..."
for _ in $(seq 1 30); do
    docker ps --format '{{.Names}}' | grep -qx "$PROJECT" && break
    sleep 1
done
"$SCRIPT_DIR/patches/apply.sh" || echo "  (patch step failed — see patches/README.md)" >&2

OPENWEBUI_PORT=$(grep "^OPENWEBUI_PORT_HOST=" .env | cut -d= -f2-)
OPENWEBUI_PORT=${OPENWEBUI_PORT:-8080}

echo ""
echo "Open WebUI is starting. Ready in ~15 seconds."
echo ""
echo "  UI:    http://localhost:${OPENWEBUI_PORT}"
echo "  Login: create your admin account on first visit"
echo ""
echo "To watch startup: docker compose -p $PROJECT logs -f openwebui"
