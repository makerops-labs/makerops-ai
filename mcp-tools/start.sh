#!/bin/bash
# Builds and starts the mcp-tools service.
# Auto-generates APPROVALS_TOKEN on first run.
# Requires ai/searxng for web search; service tool domains additionally need
# API tokens in .env (domains without a token are skipped, not fatal).
set -e

PROJECT=mcp-tools

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

generate_if_needed APPROVALS_TOKEN 16

# ── Build and start ────────────────────────────────────────────────────────────
echo "Building image..."
docker compose -p "$PROJECT" build

echo "Starting services..."
docker compose -p "$PROJECT" up -d

MCPTOOLS_PORT=$(grep "^MCPTOOLS_PORT_HOST=" .env | cut -d= -f2-)
MCPTOOLS_PORT=${MCPTOOLS_PORT:-8099}
APPROVALS_TOKEN=$(grep "^APPROVALS_TOKEN=" .env | cut -d= -f2-)

echo ""
echo "mcp-tools is starting. Ready in ~5 seconds."
echo ""
echo "  MCP endpoint (all domains): http://localhost:${MCPTOOLS_PORT}/mcp"
echo "  Per-domain endpoints:       http://localhost:${MCPTOOLS_PORT}/mcp/<domain>"
echo "  Approvals UI:               http://localhost:${MCPTOOLS_PORT}/approvals?token=${APPROVALS_TOKEN}"
echo "  Health / mounted domains:   http://localhost:${MCPTOOLS_PORT}/healthz"
echo ""
sleep 5
echo "Mounted domains:"
docker logs mcp-tools 2>&1 | grep "\[mcp-tools\]" | tail -20 || true
echo ""
echo "To watch startup: docker compose -p $PROJECT logs -f mcp-tools"
