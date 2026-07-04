#!/bin/bash
# Starts the speech services (STT + TTS).
set -e

PROJECT=speech

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── First-run: create .env from template ──────────────────────────────────────
if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# ── First-run: create the STT model cache with host ownership ─────────────────
# speaches errors (rather than creating) when the HF cache dir is missing,
# and a docker-created bind mount would be root-owned. The container runs as
# uid 1000, matching the default host user.
DATA_PATH=$(grep "^SPEECH_DATA_PATH=" .env | cut -d= -f2-)
mkdir -p "${DATA_PATH:-./data/speech}/stt/hub"

# ── Pull and start ─────────────────────────────────────────────────────────────
echo "Pulling latest images..."
docker compose -p "$PROJECT" pull

echo "Starting services..."
docker compose -p "$PROJECT" up -d

STT_PORT=$(grep "^SPEECH_STT_PORT_HOST=" .env | cut -d= -f2-)
STT_PORT=${STT_PORT:-8091}
TTS_PORT=$(grep "^SPEECH_TTS_PORT_HOST=" .env | cut -d= -f2-)
TTS_PORT=${TTS_PORT:-8093}

echo ""
echo "Speech services are starting."
echo "(First STT request downloads the Whisper model — allow a minute.)"
echo ""
echo "  STT: http://localhost:${STT_PORT}/v1/audio/transcriptions"
echo "  TTS: http://localhost:${TTS_PORT}/v1/audio/speech"
echo ""
echo "Wire into Open WebUI: Admin Settings → Audio (see README.md)."
echo "To watch startup: docker compose -p $PROJECT logs -f"
