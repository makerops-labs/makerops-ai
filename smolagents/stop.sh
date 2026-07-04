#!/bin/bash
# Stops the smolagents container. The data volume (agent outputs, uploads) is preserved.
# Pass --volumes to also remove the data volume (destructive).
set -e

PROJECT=smolagents

docker compose -p "$PROJECT" down "$@"
