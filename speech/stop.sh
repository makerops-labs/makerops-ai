#!/bin/bash
# Stops the speech containers. The model cache is preserved.
# Pass --volumes to also remove the data volume (destructive).
set -e

PROJECT=speech

docker compose -p "$PROJECT" down "$@"
