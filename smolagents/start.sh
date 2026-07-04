#!/bin/bash
# Builds and starts the smolagents service.
# Requires ai/ollama to be running with the models in SMOLAGENTS_CODING_MODEL_ID
# and SMOLAGENTS_GENERAL_MODEL_ID pulled before agents can run.
set -e

PROJECT=smolagents

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── First-run: create .env from template ──────────────────────────────────────
if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# ── Build and start ────────────────────────────────────────────────────────────
echo "Building image..."
docker compose -p "$PROJECT" build

echo "Starting services..."
docker compose -p "$PROJECT" up -d

SMOLAGENTS_PORT=$(grep "^SMOLAGENTS_PORT_HOST=" .env | cut -d= -f2-)
SMOLAGENTS_PORT=${SMOLAGENTS_PORT:-8090}

echo ""
echo "smolagents is starting. Ready in ~15 seconds."
echo ""
echo "  UI:    http://localhost:${SMOLAGENTS_PORT}"
echo ""
echo "Requires ai/ollama to be running, with both models pulled:"
echo "  docker exec ollama ollama pull qwen3-coder:30b"
echo "  docker exec ollama ollama pull gemma4:12b"
echo ""
echo "To watch startup: docker compose -p $PROJECT logs -f smolagents"
