#!/bin/bash
# Stops the redeploy container.
set -e

PROJECT=redeploy

docker compose -p "$PROJECT" down "$@"
