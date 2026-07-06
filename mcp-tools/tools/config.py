"""Environment-driven configuration for the MCP tool server.

Every integrated service gets a base URL (defaulting to its host port via
host.docker.internal) and, where required, an API token. Domains whose token
is unset are skipped at mount time — see server.py.
"""

import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DATA_DIR = Path(_env("MCPTOOLS_DATA_DIR", "/data"))

# ── Web / search ───────────────────────────────────────────────────────────────
SEARXNG_URL = _env("SEARXNG_URL", "http://host.docker.internal:8098")
FETCH_MAX_DOWNLOAD_BYTES = int(_env("FETCH_MAX_DOWNLOAD_BYTES", str(20 * 1024 * 1024)))

# ── Service endpoints & tokens ────────────────────────────────────────────────
OUTLINE_URL = _env("OUTLINE_URL", "http://host.docker.internal:3001")
OUTLINE_API_TOKEN = _env("OUTLINE_API_TOKEN")

INVENTREE_URL = _env("INVENTREE_URL", "http://host.docker.internal:8096")
INVENTREE_API_TOKEN = _env("INVENTREE_API_TOKEN")

PLANE_URL = _env("PLANE_URL", "http://host.docker.internal:8100")
PLANE_API_KEY = _env("PLANE_API_KEY")
PLANE_WORKSPACE_SLUG = _env("PLANE_WORKSPACE_SLUG")

N8N_URL = _env("N8N_URL", "http://host.docker.internal:5678")
N8N_API_KEY = _env("N8N_API_KEY")

COMFYUI_URL = _env("COMFYUI_URL", "http://host.docker.internal:8188")
COMFYUI_PUBLIC_URL = _env("COMFYUI_PUBLIC_URL", "http://comfyui.localhost")
COMFYUI_CHECKPOINT = _env("COMFYUI_CHECKPOINT")

FREESCOUT_URL = _env("FREESCOUT_URL", "http://host.docker.internal:8095")
FREESCOUT_API_KEY = _env("FREESCOUT_API_KEY")
# FreeScout 403s ("Access denied") when the request Host differs from its
# SITE_URL; this Host header must match the browser-facing URL.
FREESCOUT_SITE_HOST = _env("FREESCOUT_SITE_HOST", "localhost:8095")

DRAWIO_PUBLIC_URL = _env("DRAWIO_PUBLIC_URL", "http://draw.localhost")

SPEECH_TTS_URL = _env("SPEECH_TTS_URL", "http://host.docker.internal:8093")
SPEECH_TTS_VOICE = _env("SPEECH_TTS_VOICE", "af_heart")

TRELLIS_URL = _env("TRELLIS_URL", "http://host.docker.internal:8094")

TRIGGERDEV_URL = _env("TRIGGERDEV_URL", "http://host.docker.internal:3040")
TRIGGERDEV_SECRET_KEY = _env("TRIGGERDEV_SECRET_KEY")

# Host path of smolagents/agents is bind-mounted here (rw) for agent_create.
SMOLAGENTS_AGENTS_DIR = Path(_env("SMOLAGENTS_AGENTS_DIR", "/smolagents-agents"))

# Shared agent-job queue (smolagents/data/smolagents/jobs bind-mounted rw)
# for agent_dispatch / job status / the /inbox page.
AGENT_JOBS_DIR = Path(_env("AGENT_JOBS_DIR", "/agent-jobs"))

# ── Write policy ──────────────────────────────────────────────────────────────
APPROVALS_TOKEN = _env("APPROVALS_TOKEN")
APPROVAL_NOTIFY_WEBHOOK = _env("APPROVAL_NOTIFY_WEBHOOK")
APPROVAL_TTL_HOURS = float(_env("APPROVAL_TTL_HOURS", "24"))
# Comma lists of "domain" or "domain.tool_name" entries.
APPROVAL_GATE_EXEMPT = {e.strip() for e in _env("APPROVAL_GATE_EXEMPT").split(",") if e.strip()}
APPROVAL_FORCE_GATE = {e.strip() for e in _env("APPROVAL_FORCE_GATE").split(",") if e.strip()}

# Public URL of this server (used in approval messages shown to the user).
MCPTOOLS_PUBLIC_URL = _env("MCPTOOLS_PUBLIC_URL", "http://mcp.localhost")
