"""Progressive-disclosure documentation tree for the mounted tool domains.

Three levels, each kept small so agents load only what they need:

    ""                  root manifest — one line per domain, enough for a
                        go/no-go decision, with a link one level down
    "<domain>"          the domain's tools with one-line descriptions
    "<domain>/<tool>"   full docstring + parameter table for one tool

A parallel ``guidance`` branch serves the best-practice library
(makerops-ai/docs/guidance, bind-mounted read-only): ``guidance`` lists the
docs, ``guidance/<slug>`` returns one in full. It is rendered from disk on
every request (the mount updates live with the repo checkout), unlike the
introspected domain nodes below.

Every node ends with navigation (up/down) so an agent can drill in for
detail or back out when a branch does not fit the task. Served both over
plain HTTP (GET /context[...]) and as the ``tools_help(path)`` MCP tool
present on every domain endpoint (see server.py).

Rendered lazily from live FastMCP introspection and cached per process —
mounts only change when the container is recreated.
"""

from pathlib import Path

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


GUIDANCE_NODE = "guidance"


class DocsTree:
    def __init__(self, domains: dict, skipped: dict[str, str], base_url: str,
                 guidance_dir: Path | None = None):
        self._domains = domains
        self._skipped = skipped
        self._base = base_url.rstrip("/")
        self._guidance_dir = guidance_dir
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
        parts = path.split("/") if path else []
        if parts and parts[0] == GUIDANCE_NODE:
            # Never cached: the guidance mount updates live with the repo.
            if len(parts) == 1:
                return self._render_guidance_index()
            if len(parts) == 2:
                return self._render_guidance_doc(parts[1])
            return None
        if path not in self._cache:
            if len(parts) == 0:
                self._cache[path] = await self._render_root()
            elif len(parts) == 1:
                self._cache[path] = await self._render_domain(parts[0])
            elif len(parts) == 2:
                self._cache[path] = await self._render_tool(parts[0], parts[1])
            else:
                self._cache[path] = None
        return self._cache[path]

    # ── Guidance branch ────────────────────────────────────────────────────────

    def _guidance_docs(self) -> list[Path]:
        if self._guidance_dir is None or not self._guidance_dir.is_dir():
            return []
        # README.md is the human-facing index; the index node below already
        # plays that role for agents.
        return sorted(p for p in self._guidance_dir.glob("*.md")
                      if p.stem.lower() != "readme")

    @staticmethod
    def _guidance_title_blurb(path: Path) -> tuple[str, str]:
        """(title, one-line blurb) from a doc's leading heading + first prose line."""
        title, blurb = path.stem, ""
        try:
            for raw in path.read_text().splitlines():
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    if title == path.stem:
                        title = line.lstrip("# ").strip()
                    continue
                blurb = _first_sentence(line)
                break
        except OSError:
            pass
        return title, blurb

    def _render_guidance_index(self) -> str | None:
        docs = self._guidance_docs()
        if not docs:
            return None
        lines = []
        for p in docs:
            title, blurb = self._guidance_title_blurb(p)
            lines.append(f"- **{title}** — {blurb}  "
                         f"→ `{HELP_TOOL}('{GUIDANCE_NODE}/{p.stem}')`")
        return f"""# Best-practice guidance

Distilled operating guidance for agents in this stack (planning discipline,
verification, tool use). Pull ONE doc when its topic matches your task —
never preload all of them. Source of truth: makerops-ai/docs/guidance/.

{chr(10).join(lines)}

{self._nav(down_hint=f"`{HELP_TOOL}('{GUIDANCE_NODE}/<doc>')` · GET {self._base}/context/{GUIDANCE_NODE}/<doc>", up="")}"""

    def _render_guidance_doc(self, slug: str) -> str | None:
        if self._guidance_dir is None or "/" in slug or slug in ("", ".", ".."):
            return None
        path = self._guidance_dir / f"{slug}.md"
        if not path.is_file():
            return None
        try:
            body = path.read_text()
        except OSError:
            return None
        return f"{body.rstrip()}\n\n{self._nav(up=GUIDANCE_NODE)}"

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
{f"**Best-practice guidance.** Distilled operating guidance (planning discipline, verification, tool use) is browsable at `{HELP_TOOL}('{GUIDANCE_NODE}')` · GET {self._base}/context/{GUIDANCE_NODE} — pull one doc when its topic matches the task.{chr(10)}" if self._guidance_docs() else ""}
**Agent workforce.** Long or multi-step tasks (research + writing, media
creation, business-ops sequences, reviewing and improving the stack
itself, anything needing tools you do not have or unattended execution)
can be delegated to the local agent team via the `agents` domain:
`agent_list` shows the roster, `agent_dispatch(...)` queues a background
job (runs for minutes; long jobs continue across segments from a
workspace synopsis), `agent_job_status` / `agent_job_result` track it.
Refine the task into a concrete brief with the user before dispatching —
the team cannot ask questions mid-run. Finished reports and
needs-attention items land in the task inbox at {self._base}/inbox and
trigger a notification. Handle a request inline when one answer or a
couple of tool calls suffice; dispatch when it does not.

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
