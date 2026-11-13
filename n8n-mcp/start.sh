#!/bin/bash
# Starts the n8n-mcp service. Auto-generates N8NMCP_AUTH_TOKEN on first run.
#
# Requires the makerops-core n8n instance running with its public REST API
# enabled and N8N_API_KEY set in .env (reuse the value from ../mcp-tools/.env,
# minted at n8n → Settings → n8n API).
set -e

PROJECT=n8n-mcp

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── First-run: create .env from template ──────────────────────────────────────
if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# ── Secret generation (base64, per n8n-mcp docs) ──────────────────────────────
if grep -q "^N8NMCP_AUTH_TOKEN=GENERATE_ME" .env 2>/dev/null; then
    val=$(openssl rand -base64 32)
    # base64 has no '|' so it is a safe sed delimiter; escape '&' in the value.
    esc=${val//&/\\&}
    sed -i "s|^N8NMCP_AUTH_TOKEN=GENERATE_ME|N8NMCP_AUTH_TOKEN=${esc}|" .env
    echo "  Generated N8NMCP_AUTH_TOKEN." >&2
fi

if ! grep -q "^N8N_API_KEY=.\+" .env; then
    echo "" >&2
    echo "WARNING: N8N_API_KEY is empty in .env — copy it from ../mcp-tools/.env" >&2
    echo "         (or mint one at n8n → Settings → n8n API). n8n-mcp will start" >&2
    echo "         but every n8n_* workflow tool fails until it is set, then" >&2
    echo "         re-run: docker compose -p $PROJECT up -d" >&2
    echo "" >&2
fi

# ── Pull and start ───────────────────────────────────────────────────────────
echo "Pulling latest image..."
docker compose -p "$PROJECT" pull

echo "Starting services..."
docker compose -p "$PROJECT" up -d

PORT=$(grep "^N8NMCP_PORT_HOST=" .env | cut -d= -f2-); PORT=${PORT:-8104}

echo ""
echo "n8n-mcp is starting. Ready in ~15 seconds."
echo ""
echo "  MCP endpoint:  http://localhost:${PORT}/mcp   (Authorization: Bearer <N8NMCP_AUTH_TOKEN>)"
echo "  Health:        http://localhost:${PORT}/health"
echo "  Proxy route:   http://n8n-mcp.localhost   (after the name-proxy drop-in)"
echo ""
sleep 15

echo "Health:"
curl -s "http://localhost:${PORT}/health" || echo "  (not up yet — docker compose -p $PROJECT logs -f)"
echo ""
echo ""
echo "The MCP endpoint needs an initialize handshake, so 'curl .../mcp' can't"
echo "list tools directly. After wiring the mcp-tools 'n8nmcp' proxy domain:"
echo "  curl -s http://localhost:8099/context/n8nmcp   # 18-tool list"
echo "Or list + test n8n reachability now — see n8n-mcp/README.md \"Verify\"."
echo ""
echo "To watch startup: docker compose -p $PROJECT logs -f"
