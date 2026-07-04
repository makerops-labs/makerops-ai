#!/bin/bash
# Stops the Open WebUI container. The data volume (chat history, accounts) is preserved.
# Pass --volumes to also remove the data volume (destructive).
set -e

PROJECT=openwebui

docker compose -p "$PROJECT" down "$@"
