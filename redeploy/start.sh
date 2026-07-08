#!/bin/bash
# Starts the redeploy service (Docker-socket-scoped restart proxy).
set -e

PROJECT=redeploy

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── First-run: create .env from template, generate the shared token ──────────
if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    TOKEN=$(openssl rand -hex 24)
    sed -i "s/^REDEPLOY_TOKEN=.*/REDEPLOY_TOKEN=${TOKEN}/" .env
    echo ""
    echo "Generated REDEPLOY_TOKEN. Copy it into mcp-tools/.env as REDEPLOY_TOKEN"
    echo "(both sides must match) — then recreate mcp-tools:"
    echo "  grep REDEPLOY_TOKEN .env"
    echo "  cd ../mcp-tools && docker compose -p mcp-tools up -d"
    echo ""
fi

docker compose -p "$PROJECT" up -d --build

PORT=$(grep "^REDEPLOY_PORT_HOST=" .env | cut -d= -f2-)
PORT=${PORT:-8101}

echo ""
echo "redeploy is starting."
echo "  Health: http://localhost:${PORT}/healthz"
echo ""
echo "This service has Docker socket access, scoped to restarting only"
echo "smolagents and mcp-tools (ALLOWED_SERVICES in main.py). See"
echo "docs/ai-setup-checklist.md 'Self-improvement loop' for the full flow."
