#!/bin/bash
# Starts the sandbox service (Docker-socket-scoped command execution).
set -e

PROJECT=sandbox

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── First-run: create .env from template, generate the shared token ──────────
if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    TOKEN=$(openssl rand -hex 24)
    sed -i "s/^SANDBOX_TOKEN=.*/SANDBOX_TOKEN=${TOKEN}/" .env
    echo ""
    echo "Generated SANDBOX_TOKEN. Copy it into mcp-tools/.env as SANDBOX_TOKEN"
    echo "(both sides must match) — then recreate mcp-tools:"
    echo "  grep SANDBOX_TOKEN .env"
    echo "  cd ../mcp-tools && docker compose -p mcp-tools up -d"
    echo ""
    echo "Also set WORKSPACES_ROOT in this directory's .env to the SAME"
    echo "absolute host path as mcp-tools/.env's WORKSPACES_ROOT."
    echo ""
fi

# Build the ephemeral-container runtime image (not rebuilt per request).
# --network host: same WSL2 quirk as every other build in this repo — the
# host resolver is unreachable from bridge networks during build, which
# breaks apt/package downloads without it.
docker build --network host -f runtime.Dockerfile -t makerops-sandbox-runtime:latest .

docker compose -p "$PROJECT" up -d --build

PORT=$(grep "^SANDBOX_PORT_HOST=" .env | cut -d= -f2-)
PORT=${PORT:-8102}

echo ""
echo "sandbox is starting."
echo "  Health: http://localhost:${PORT}/healthz"
echo ""
echo "This service has Docker socket access, scoped to launching throwaway"
echo "resource-capped containers with exactly one registered project"
echo "directory mounted — the ephemeral containers themselves never get the"
echo "socket. See docs/ai-setup-checklist.md 'Sandboxed command execution'."
