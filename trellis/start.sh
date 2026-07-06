#!/bin/bash
# Starts the TRELLIS image-to-3D service (GPU, start-on-demand).
set -e

PROJECT=trellis

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── First-run: create .env from template ──────────────────────────────────────
if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# ── First-run: create cache dirs with host ownership ──────────────────────────
# A docker-created bind mount would be root-owned.
DATA_PATH=$(grep "^TRELLIS_DATA_PATH=" .env | cut -d= -f2-)
mkdir -p "${DATA_PATH:-./data}"/{hf,torch,u2net,jobs}

# ── Build and start ────────────────────────────────────────────────────────────
# First build compiles CUDA extensions — allow 20–40 minutes.
echo "Building (first build takes 20-40 min) and starting..."
docker compose -p "$PROJECT" up -d --build

PORT=$(grep "^TRELLIS_PORT_HOST=" .env | cut -d= -f2-)
PORT=${PORT:-8094}

echo ""
echo "TRELLIS is starting."
echo "(First-ever start downloads ~5 GB of model weights in the background;"
echo " watch: docker compose -p $PROJECT logs -f"
echo " ready when: curl -s localhost:${PORT}/healthz reports weights_ready:true."
echo " The first generation also JIT-compiles nvdiffrast kernels — allow ~10 min.)"
echo ""
echo "  API:     http://localhost:${PORT}/healthz"
echo "  Proxy:   http://trellis.localhost"
echo ""
echo "GPU note: a generation needs most of the 16 GB card. Run ./stop.sh when"
echo "you are done with 3D work."
