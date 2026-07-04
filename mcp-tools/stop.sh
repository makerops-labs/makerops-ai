#!/bin/bash
# Stops the mcp-tools container. The data volume (approvals, audit log,
# provenance registry, saved diagrams) is preserved.
# Pass --volumes to also remove the data volume (destructive).
set -e

PROJECT=mcp-tools

docker compose -p "$PROJECT" down "$@"
