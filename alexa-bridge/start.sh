#!/bin/bash
# Starts the alexa-bridge service (Amazon Alexa custom-skill backend).
set -e

PROJECT=alexa-bridge

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo ""
    echo "Set ALEXA_SKILL_APPLICATION_ID (once the skill exists) and"
    echo "APPROVALS_TOKEN (same value as mcp-tools/.env) before going live."
    echo "See docs/alexa-voice-setup.md."
    echo ""
fi

docker compose -p "$PROJECT" up -d --build

PORT=$(grep "^ALEXA_BRIDGE_PORT_HOST=" .env | cut -d= -f2-)
PORT=${PORT:-8103}

echo ""
echo "alexa-bridge is starting."
echo "  Health: http://localhost:${PORT}/healthz"
echo ""
echo "Not reachable from Alexa yet until the Cloudflare Tunnel is set up"
echo "(makerops-core/remote_access/cloudflared/) and ALEXA_SKILL_APPLICATION_ID"
echo "is set — see docs/alexa-voice-setup.md."
