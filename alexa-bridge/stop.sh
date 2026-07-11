#!/bin/bash
# Stops the alexa-bridge container.
set -e

PROJECT=alexa-bridge

docker compose -p "$PROJECT" down "$@"
