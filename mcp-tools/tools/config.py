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

# Best-practice guidance library served as the docs tree's `guidance`
# branch (tools/docs_tree.py), read via the existing whole-repo mount that
# propose_code_change already uses. Missing/empty directory just hides the
# branch.
GUIDANCE_DIR = Path(_env("GUIDANCE_DIR", "/repo/docs/guidance"))

# ── Web / search ───────────────────────────────────────────────────────────────
SEARXNG_URL = _env("SEARXNG_URL", "http://host.docker.internal:8098")
FETCH_MAX_DOWNLOAD_BYTES = int(_env("FETCH_MAX_DOWNLOAD_BYTES", str(20 * 1024 * 1024)))

# ── Service endpoints & tokens ────────────────────────────────────────────────
OUTLINE_URL = _env("OUTLINE_URL", "http://host.docker.internal:3001")
OUTLINE_API_TOKEN = _env("OUTLINE_API_TOKEN")
# Browser-facing URL, for turning the relative "url" Outline's API returns
# into a link a human (or a report) can actually follow.
OUTLINE_PUBLIC_URL = _env("OUTLINE_PUBLIC_URL", "http://localhost:3001")

INVENTREE_URL = _env("INVENTREE_URL", "http://host.docker.internal:8096")
INVENTREE_API_TOKEN = _env("INVENTREE_API_TOKEN")

PLANE_URL = _env("PLANE_URL", "http://host.docker.internal:8100")
PLANE_API_KEY = _env("PLANE_API_KEY")
PLANE_WORKSPACE_SLUG = _env("PLANE_WORKSPACE_SLUG")
# Hand-maintained (Plane's public API has no workspace-list endpoint) — see
# plane_list_workspaces.
PLANE_WORKSPACE_SLUGS = [s.strip() for s in _env("PLANE_WORKSPACE_SLUGS").split(",") if s.strip()]

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

# X (Twitter) recent search — costs real money per read (no free tier since
# Feb 2026); used only by the self-improvement loop's research sweep. See
# tools/x_search.py.
X_API_URL = _env("X_API_URL", "https://api.x.com")
X_API_BEARER_TOKEN = _env("X_API_BEARER_TOKEN")

# Host path of smolagents/agents is bind-mounted here (rw) for agent_create.
SMOLAGENTS_AGENTS_DIR = Path(_env("SMOLAGENTS_AGENTS_DIR", "/smolagents-agents"))

# Shared agent-job queue (smolagents/data/smolagents/jobs bind-mounted rw)
# for agent_dispatch / job status / the /inbox page.
AGENT_JOBS_DIR = Path(_env("AGENT_JOBS_DIR", "/agent-jobs"))

# Shared debate session store (smolagents/data/smolagents/debates
# bind-mounted rw) for debate_start / status / manifest / round reads. A
# second, parallel queue alongside AGENT_JOBS_DIR above — see
# tools/debate_domain.py and tools/debate_store.py.
AGENT_DEBATES_DIR = Path(_env("AGENT_DEBATES_DIR", "/agent-debates"))

# Shared Alexa-liaison session store (smolagents/data/smolagents/liaison
# bind-mounted rw) for liaison_turn / liaison_session_status /
# liaison_reset_session / liaison_clear_pending_action. A third, parallel
# queue alongside AGENT_JOBS_DIR and AGENT_DEBATES_DIR above — see
# tools/liaison_domain.py and tools/liaison_store.py.
AGENT_LIAISON_DIR = Path(_env("AGENT_LIAISON_DIR", "/agent-liaison"))

# Shared devteam engagement store (smolagents/data/smolagents/devteam
# bind-mounted rw) for devteam_start / status / answer / approve / revise /
# resume / cancel. A fourth, parallel queue alongside the three above — see
# tools/devteam_domain.py and tools/devteam_store.py.
AGENT_DEVTEAM_DIR = Path(_env("AGENT_DEVTEAM_DIR", "/agent-devteam"))

# Debate round-count defaults/ceiling — mode-dependent default, caller
# overridable up to the hard ceiling (see debate_start).
DEBATE_MAX_ROUNDS_NARROW = int(_env("DEBATE_MAX_ROUNDS_NARROW", "6"))
DEBATE_MAX_ROUNDS_BROAD = int(_env("DEBATE_MAX_ROUNDS_BROAD", "16"))
DEBATE_HARD_MAX_ROUNDS = int(_env("DEBATE_HARD_MAX_ROUNDS", "40"))
# Default cadence (entrepreneur+critic exchanges between monitor
# check-ins) and manifest row cap for debate_manifest — mirrors the
# smolagents-side defaults each turn's own prompt uses (kept as a separate
# constant since this is a different service/process; see agents/config.py).
DEBATE_MONITOR_EVERY_N_DEFAULT = int(_env("DEBATE_MONITOR_EVERY_N_DEFAULT", "2"))
DEBATE_MANIFEST_RENDER_LIMIT = int(_env("DEBATE_MANIFEST_RENDER_LIMIT", "25"))

# Self-improvement loop: full repo bind-mounted rw for propose_code_change to
# read/diff any file (gating on approval is the safety boundary, not a path
# allowlist); the actual write + container restart happens in the separate
# redeploy service, which owns Docker socket access.
REPO_ROOT = Path(_env("REPO_ROOT", "/repo"))
REDEPLOY_URL = _env("REDEPLOY_URL", "http://host.docker.internal:8101")
REDEPLOY_TOKEN = _env("REDEPLOY_TOKEN")

# Durable per-project directories the user creates by hand under
# ~/workspace/ (siblings of ~/workspace/makerops/). Read-write, mounted only
# into mcp-tools — never into smolagents, so CodeAgents reach this only via
# the project_* tools, not raw pathlib. See tools/project.py.
PROJECTS_ROOT = Path(_env("PROJECTS_ROOT", "/workspaces"))

# Sandboxed command execution: separate service (sandbox/) with its own
# Docker-socket access, launching resource-capped ephemeral containers with
# exactly one project directory mounted — never the socket itself. See
# tools/project.py's project_run_command and sandbox/README.md.
SANDBOX_URL = _env("SANDBOX_URL", "http://host.docker.internal:8102")
SANDBOX_TOKEN = _env("SANDBOX_TOKEN")
SANDBOX_MAX_TIMEOUT_S = int(_env("SANDBOX_MAX_TIMEOUT_S", "600"))

# ── Write policy ──────────────────────────────────────────────────────────────
APPROVALS_TOKEN = _env("APPROVALS_TOKEN")
APPROVAL_NOTIFY_WEBHOOK = _env("APPROVAL_NOTIFY_WEBHOOK")
APPROVAL_TTL_HOURS = float(_env("APPROVAL_TTL_HOURS", "24"))
# Comma lists of "domain" or "domain.tool_name" entries.
APPROVAL_GATE_EXEMPT = {e.strip() for e in _env("APPROVAL_GATE_EXEMPT").split(",") if e.strip()}
APPROVAL_FORCE_GATE = {e.strip() for e in _env("APPROVAL_FORCE_GATE").split(",") if e.strip()}

# Public URL of this server (used in approval messages shown to the user).
MCPTOOLS_PUBLIC_URL = _env("MCPTOOLS_PUBLIC_URL", "http://mcp.localhost")
