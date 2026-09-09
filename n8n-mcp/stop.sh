#!/bin/bash
# Stops the n8n-mcp container. n8n-mcp is stateless (it only proxies the n8n
# REST API), so there is no data volume to preserve.
set -e

PROJECT=n8n-mcp

docker compose -p "$PROJECT" down "$@"
