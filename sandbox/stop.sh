#!/bin/bash
# Stops the sandbox container.
set -e

PROJECT=sandbox

docker compose -p "$PROJECT" down "$@"
