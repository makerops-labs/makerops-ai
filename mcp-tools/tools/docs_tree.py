"""Progressive-disclosure documentation tree for the mounted tool domains.

Three levels, each kept small so agents load only what they need:

    ""                  root manifest — one line per domain, enough for a
                        go/no-go decision, with a link one level down
    "<domain>"          the domain's tools with one-line descriptions
    "<domain>/<tool>"   full docstring + parameter table for one tool

Every node ends with navigation (up/down) so an agent can drill in for
detail or back out when a branch does not fit the task. Served both over
plain HTTP (GET /context[...]) and as the ``tools_help(path)`` MCP tool
present on every domain endpoint (see server.py).

Rendered lazily from live FastMCP introspection and cached per process —
mounts only change when the container is recreated.
"""

WRITE_PREFIX = "WRITE ACTION"
WRITE_MARK = "✎"  # ✎
HELP_TOOL = "tools_help"


def _first_sentence(text: str | None) -> str:
    if not text:
        return "(no description)"
    line = " ".join(text.split())
    for sep in (". ", " — ", "; "):
        idx = line.find(sep)
        if 0 < idx < 180:
            return line[: idx + (1 if sep == ". " else 0)]
    return line[:180]


class DocsTree:
    def __init__(self, domains: dict, skipped: dict[str, str], base_url: str):
        self._domains = domains
        self._skipped = skipped
        self._base = base_url.rstrip("/")
        self._inventory: dict[str, dict] | None = None
        self._cache: dict[str, str | None] = {}

    async def _tools(self) -> dict[str, dict]:
        """{domain: {tool_name: Tool}} from live introspection, help tool excluded."""
        if self._inventory is None:
            self._inventory = {
                name: {t_name: tool
                       for t_name, tool in (await sub.get_tools()).items()
                       if t_name != HELP_TOOL}
                for name, sub in self._domains.items()
            }
        return self._inventory

    async def render(self, path: str) -> str | None:
        """Markdown for the node at ``path``; None for unknown paths."""
        path = (path or "").strip().strip("/")
        if path not in self._cache:
            parts = path.split("/") if path else []
            if len(parts) == 0:
                self._cache[path] = await self._render_root()
            elif len(parts) == 1:
                self._cache[path] = await self._render_domain(parts[0])
            elif len(parts) == 2:
                self._cache[path] = await self._render_tool(parts[0], parts[1])
            else:
                self._cache[path] = None
        return self._cache[path]

    # ── Node renderers ─────────────────────────────────────────────────────────

    def _nav(self, down_hint: str | None = None, up: str | None = None) -> str:
        lines = []
        if down_hint:
            lines.append(f"Drill down: {down_hint}")
        if up is not None:
            lines.append(f"Back up: `{HELP_TOOL}('{up}')` · GET {self._base}/context/{up}".rstrip("/"))
        return "\n".join(lines)

    async def _render_root(self) -> str:
        tools = await self._tools()
        rows = []
        for name in sorted(tools):
            sub = self._domains[name]
            blurb = getattr(sub, "instructions", None) or f"Tools for {name}."
            n = len(tools[name])
            writes = sum(1 for t in tools[name].values()
                         if (t.description or "").startswith(WRITE_PREFIX))
            counts = f"{n} tool{'s' if n != 1 else ''}" + (f", {writes} {WRITE_MARK}" if writes else "")
            rows.append(f"| `{name}` | {blurb} | {counts} | `{HELP_TOOL}('{name}')` |")
        skipped = "".join(f"\n- `{d}` — not mounted (set {env} in mcp-tools/.env)"
                          for d, env in sorted(self._skipped.items()))
        return f"""# Tool environment — mcp-tools

A shared MCP tool server at {self._base}. Tools are grouped into **domains**;
each domain is its own MCP endpoint at `/mcp/<domain>/`. Attach only the
domains a task needs — long tool lists degrade local models. Every domain
endpoint also carries `{HELP_TOOL}(path)` for browsing this documentation tree.

| Domain | Purpose | Tools | Details |
| --- | --- | --- | --- |
{chr(10).join(rows)}

{WRITE_MARK} = gated write tools. A write may answer `PENDING APPROVAL #id` —
report that to the user and stop; a human approves it at {self._base}/approvals.
Never retry a pending write.
{f"{chr(10)}Unmounted domains:{skipped}{chr(10)}" if skipped else ""}
{self._nav(down_hint=f"`{HELP_TOOL}('<domain>')` · GET {self._base}/context/<domain>")}"""

    async def _render_domain(self, domain: str) -> str | None:
        tools = await self._tools()
        if domain not in tools:
            return None
        sub = self._domains[domain]
        blurb = getattr(sub, "instructions", None) or f"Tools for {domain}."
        lines = []
        for t_name in sorted(tools[domain]):
            tool = tools[domain][t_name]
            desc = tool.description or ""
            mark = f"{WRITE_MARK} " if desc.startswith(WRITE_PREFIX) else ""
            one_liner = _first_sentence(desc.removeprefix(WRITE_PREFIX).lstrip(" —-"))
            lines.append(f"- {mark}**{t_name}** — {one_liner}  "
                         f"→ `{HELP_TOOL}('{domain}/{t_name}')`")
        return f"""# Domain `{domain}`

{blurb}

MCP endpoint: `{self._base}/mcp/{domain}/`

{chr(10).join(lines)}

{WRITE_MARK} = gated write (may return `PENDING APPROVAL #id` — report, don't retry).

{self._nav(down_hint=f"`{HELP_TOOL}('{domain}/<tool>')` for full usage details", up="")}"""

    async def _render_tool(self, domain: str, t_name: str) -> str | None:
        tools = await self._tools()
        tool = tools.get(domain, {}).get(t_name)
        if tool is None:
            return None
        desc = (tool.description or "(no description)").strip()
        is_write = desc.startswith(WRITE_PREFIX)
        schema = getattr(tool, "parameters", None) or {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        rows = []
        for p_name, p in props.items():
            p_type = p.get("type") or "/".join(
                a.get("type", "?") for a in p.get("anyOf", [])) or "any"
            default = "" if "default" not in p else f"`{p['default']!r}`"
            rows.append(f"| `{p_name}` | {p_type} | "
                        f"{'yes' if p_name in required else 'no'} | {default} |")
        params_md = ("| Parameter | Type | Required | Default |\n| --- | --- | --- | --- |\n"
                     + "\n".join(rows)) if rows else "_No parameters._"
        write_md = (f"\n{WRITE_MARK} **Gated write.** May answer `PENDING APPROVAL #id`: "
                    "report it to the user and stop — a human approves at "
                    f"{self._base}/approvals. Never retry a pending write.\n") if is_write else ""
        return f"""# Tool `{t_name}` (domain `{domain}`)

{desc}
{write_md}
## Parameters

{params_md}

{self._nav(up=domain)}"""
