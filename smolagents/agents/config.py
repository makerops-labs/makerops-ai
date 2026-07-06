"""Environment-driven configuration shared by all agents.

Defaults assume a host venv talking to Ollama on localhost. The Docker
service overrides OLLAMA_API_BASE and SMOLAGENTS_DATA_DIR via compose.
"""

import os

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434/v1")
# Ollama ignores the key, but the OpenAI client requires a value.
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "ollama")

CODING_MODEL_ID = os.environ.get("SMOLAGENTS_CODING_MODEL_ID", "qwen3.6:35b")
GENERAL_MODEL_ID = os.environ.get("SMOLAGENTS_GENERAL_MODEL_ID", "qwen3.5:9b-64k")


def _model_list(env_var: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(env_var, default).split(",")
            if m.strip()]


# Reviewer pools for the audit agent: same-expertise models that sit below
# the lead on benchmarks, used to catch the lead model's blind spots.
# gpt-oss is a different lineage (OpenAI vs Qwen/Gemma), which decorrelates
# the review. See the model hierarchy table in README.md.
CODING_REVIEW_MODEL_IDS = _model_list("SMOLAGENTS_CODING_REVIEW_MODEL_IDS",
                                      "qwen3-coder:30b,gpt-oss:20b")
GENERAL_REVIEW_MODEL_IDS = _model_list("SMOLAGENTS_GENERAL_REVIEW_MODEL_IDS",
                                       "gemma4:12b,gpt-oss:20b")

DATA_DIR = os.environ.get("SMOLAGENTS_DATA_DIR", "./data")
MAX_STEPS = int(os.environ.get("SMOLAGENTS_MAX_STEPS", "12"))

# Manager orchestration: extra step headroom, periodic replanning, and the
# segment cap for long jobs that continue from a workspace synopsis.
MANAGER_MAX_STEPS = int(os.environ.get("SMOLAGENTS_MANAGER_MAX_STEPS", "20"))
PLANNING_INTERVAL = int(os.environ.get("SMOLAGENTS_PLANNING_INTERVAL", "5"))
MAX_SEGMENTS = int(os.environ.get("SMOLAGENTS_MAX_SEGMENTS", "8"))

# Background job queue shared with mcp-tools (agent_dispatch) via bind mount.
JOBS_DIR = os.path.join(DATA_DIR, "jobs")

# Optional webhook (e.g. n8n) POSTed when a background job finishes or needs
# attention. Empty = disabled.
NOTIFY_WEBHOOK = os.environ.get("SMOLAGENTS_NOTIFY_WEBHOOK", "")

# Public URL of mcp-tools, used for inbox links in reports/notifications.
MCP_TOOLS_PUBLIC_URL = os.environ.get("SMOLAGENTS_MCP_PUBLIC_URL",
                                      "http://mcp.localhost")

# Shared MCP tool server (mcp-tools). Agents load tools from its
# per-domain endpoints; unavailable domains degrade to no tools.
MCP_TOOLS_URL = os.environ.get("SMOLAGENTS_MCP_URL",
                               "http://host.docker.internal:8099")
