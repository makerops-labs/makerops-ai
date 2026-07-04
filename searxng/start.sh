#!/bin/bash
# Starts the SearXNG service.
# Auto-generates SEARXNG_SECRET on first run.
set -e

PROJECT=searxng

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

generate_if_needed SEARXNG_SECRET 32

# ── Pull and start ─────────────────────────────────────────────────────────────
echo "Pulling latest image..."
docker compose -p "$PROJECT" pull

echo "Starting services..."
docker compose -p "$PROJECT" up -d

SEARXNG_PORT=$(grep "^SEARXNG_PORT_HOST=" .env | cut -d= -f2-)
SEARXNG_PORT=${SEARXNG_PORT:-8098}

echo ""
echo "SearXNG is starting. Ready in ~10 seconds."
echo ""
echo "  UI:  http://localhost:${SEARXNG_PORT}"
echo "  API: http://localhost:${SEARXNG_PORT}/search?q=<query>&format=json"
echo ""
echo "To watch startup: docker compose -p $PROJECT logs -f searxng"
