"""Environment-driven configuration for the alexa-bridge, same convention as
mcp-tools/tools/config.py and smolagents/agents/config.py."""

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# Skill ID from the Alexa Developer Console — the main defense against a
# leaked endpoint being replayed against it from an unrelated skill (see
# verify.py). Empty means the check is skipped (e.g. before the skill
# exists yet) — never leave it empty once the tunnel is live.
ALEXA_SKILL_APPLICATION_ID = _env("ALEXA_SKILL_APPLICATION_ID")

MCP_TOOLS_URL = _env("MCP_TOOLS_URL", "http://host.docker.internal:8099")

# Same token mcp-tools' own /approvals web UI uses (query-string, not a
# header — see mcp-tools/server.py's _authorized()).
APPROVALS_TOKEN = _env("APPROVALS_TOKEN")

# Bypasses signature/timestamp verification for local curl testing only.
# Must be false whenever the Cloudflare Tunnel is live — it turns off the
# only thing standing between the public internet and this endpoint.
DEV_MODE = _env("DEV_MODE", "false").lower() == "true"

# How long one Alexa turn waits for the liaison's reply before giving up
# and replying "still working" — kept comfortably under Alexa's ~8s hard
# response timeout, leaving headroom for verification, MCP round trips, and
# Alexa's own network path.
TURN_POLL_TIMEOUT_S = float(_env("TURN_POLL_TIMEOUT_S", "6.0"))
TURN_POLL_INTERVAL_S = float(_env("TURN_POLL_INTERVAL_S", "0.5"))
