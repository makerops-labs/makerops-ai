# Image the sandbox service's EPHEMERAL containers run from — not the
# sandbox service itself (see Dockerfile for that). Sized for real
# test/lint/build workflows (git, curl, a C toolchain for native deps,
# Python, Node) without being a full devcontainer-style image. No Docker
# CLI/SDK is installed here on purpose — these containers must never be
# able to reach Docker at all, nested or otherwise.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    nodejs \
    npm \
 && rm -rf /var/lib/apt/lists/*
