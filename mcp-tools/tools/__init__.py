"""Tool domains for the MakerOps MCP server.

Each module exposes a FastMCP sub-server named ``mcp`` and a ``required_env``
attribute naming the config setting that must be non-empty for the domain to
mount (None = always mounted). server.py composes them.
"""

from . import config

# domain name → (module import name, required config attribute or None)
DOMAINS: dict[str, str | None] = {
    "web": None,
    "approvals": None,
    "outline": "OUTLINE_API_TOKEN",
    "inventree": "INVENTREE_API_TOKEN",
    "plane": "PLANE_API_KEY",
    "n8n": "N8N_API_KEY",
    "n8nmcp": "N8NMCP_AUTH_TOKEN",
    "comfyui": None,
    "freescout": "FREESCOUT_API_KEY",
    "drawio": None,
    "triggerdev": "TRIGGERDEV_SECRET_KEY",
    "agents": None,
    "project": None,
    "speech": None,
    "trellis": None,
    "debate": None,
    "liaison": None,
    "devteam": None,
    "hardware": None,
    "x": "X_API_BEARER_TOKEN",
}

_MODULE_NAMES = {"approvals": "approvals_tools", "agents": "agents_domain",
                 "debate": "debate_domain", "liaison": "liaison_domain",
                 "devteam": "devteam_domain", "hardware": "hardware_domain",
                 "x": "x_search"}


def available_domains() -> dict[str, object]:
    """Import and return {domain: FastMCP} for every domain whose required
    token is set. Skipped domains are reported by the caller."""
    import importlib

    mounted = {}
    for domain, required in DOMAINS.items():
        if required and not getattr(config, required, ""):
            continue
        module = importlib.import_module(
            f".{_MODULE_NAMES.get(domain, domain)}", package=__name__)
        mounted[domain] = module.mcp
    return mounted


def skipped_domains() -> dict[str, str]:
    """{domain: missing env var} for domains that will not mount."""
    return {d: req for d, req in DOMAINS.items()
            if req and not getattr(config, req, "")}
