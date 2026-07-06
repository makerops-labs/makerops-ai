#!/bin/bash
# Stops the TRELLIS container. Model caches and job outputs are preserved.
# Pass --volumes to also remove volumes (destructive).
set -e

PROJECT=trellis

docker compose -p "$PROJECT" down "$@"
