#!/bin/bash
# Stops the SearXNG container. The cache volume is preserved.
# Pass --volumes to also remove the data volume (destructive).
set -e

PROJECT=searxng

docker compose -p "$PROJECT" down "$@"
