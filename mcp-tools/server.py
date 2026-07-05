"""MakerOps MCP tool server.

Endpoints:
  /mcp            — all mounted tool domains in one MCP server (streamable HTTP)
  /mcp/<domain>   — one domain only (smaller tool list for local models)
  /context[/...]  — progressive-disclosure tool documentation tree (markdown);
                    the same tree backs the tools_help() MCP tool present on
                    every domain endpoint
  /approvals      — human review UI for gated write actions (+ audit history)
  /healthz        — liveness + mounted-domain report
  /               — redirects to /approvals
"""

import contextlib
import html
import json

import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                                 RedirectResponse)
from starlette.routing import Mount, Route

from tools import available_domains, skipped_domains, config, policy
from tools.docs_tree import DocsTree

# ── Compose the MCP apps ───────────────────────────────────────────────────────

domains = available_domains()
for domain, missing in skipped_domains().items():
    print(f"[mcp-tools] domain '{domain}' NOT mounted — set {missing} in .env to enable it.")
print(f"[mcp-tools] mounted domains: {', '.join(domains)}")

# ── Documentation tree + tools_help ────────────────────────────────────────────
# One tree, two access paths: GET /context[/...] over HTTP, and the
# tools_help(path) tool registered on every domain endpoint so any agent can
# browse it with plain tool-calling.

tree = DocsTree(domains, skipped_domains(), config.MCPTOOLS_PUBLIC_URL)


async def tools_help(path: str = "") -> str:
    """Browse the tool documentation tree: '' lists every tool domain with its
    purpose, '<domain>' lists that domain's tools, '<domain>/<tool>' gives full
    usage details for one tool. Drill down before using an unfamiliar tool;
    back out if a branch does not fit the task."""
    text = await tree.render(path)
    return text or (f"Unknown documentation path {path!r}. "
                    "Start with tools_help('') for the domain manifest.")


for sub in domains.values():
    sub.tool(tools_help)

composed = FastMCP("makerops-tools")
composed.tool(tools_help)  # local registration wins over the mounted copies
for sub in domains.values():
    # Tools already carry their domain prefix in their names; mount unprefixed.
    composed.mount(sub)

domain_apps = {name: sub.http_app(path="/") for name, sub in domains.items()}
composed_app = composed.http_app(path="/")
all_mcp_apps = [composed_app, *domain_apps.values()]


@contextlib.asynccontextmanager
async def lifespan(app):
    async with contextlib.AsyncExitStack() as stack:
        for mcp_app in all_mcp_apps:
            await stack.enter_async_context(mcp_app.lifespan(mcp_app))
        yield


# ── Approvals UI ───────────────────────────────────────────────────────────────

_PAGE_CSS = """
body{font-family:system-ui,sans-serif;background:#0f1923;color:#e8edf2;margin:0}
header{padding:1rem 2rem;border-bottom:1px solid #2a3f58;display:flex;gap:1rem;align-items:baseline}
h1{font-size:1.2rem;margin:0}h1 span{color:#f07820}
main{max-width:960px;margin:0 auto;padding:1.5rem}
.card{background:#1a2332;border:1px solid #2a3f58;border-radius:6px;padding:1rem 1.25rem;margin-bottom:1rem}
.card h3{margin:0 0 .25rem 0;font-size:1rem}
.meta{color:#7a9ab8;font-size:.82rem;margin-bottom:.5rem}
ul.changes{margin:.25rem 0 .75rem 1.25rem;padding:0}
pre{background:#0f1923;border:1px solid #2a3f58;border-radius:6px;padding:.75rem;
    overflow-x:auto;font-size:.78rem;max-height:320px}
form{display:inline}
button{border:0;border-radius:6px;padding:.45rem 1.1rem;font-weight:600;cursor:pointer}
.approve{background:#2e7d32;color:#fff;margin-right:.5rem}
.reject{background:#b03a2e;color:#fff}
.empty{color:#7a9ab8;padding:2rem;text-align:center}
h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:#f07820;
   border-bottom:1px solid #2a3f58;padding-bottom:.4rem}
.audit{font-size:.8rem;color:#7a9ab8}.audit b{color:#e8edf2}
.badge{display:inline-block;padding:.1rem .5rem;border-radius:999px;font-size:.72rem;
       border:1px solid #2a3f58;color:#7a9ab8;margin-left:.5rem}
"""


def _authorized(request: Request) -> bool:
    if not config.APPROVALS_TOKEN:
        return True
    supplied = request.query_params.get("token") or request.cookies.get("approvals_token")
    return supplied == config.APPROVALS_TOKEN


def _auth_page() -> HTMLResponse:
    return HTMLResponse(
        f"<style>{_PAGE_CSS}</style><main><div class='card'>"
        "<h3>Authorization required</h3><p class='meta'>Open this page as "
        "<code>/approvals?token=&lt;APPROVALS_TOKEN from mcp-tools/.env&gt;</code> "
        "— a cookie is set so the token is only needed once per browser.</p></div></main>",
        status_code=401)


async def approvals_page(request: Request):
    if not _authorized(request):
        return _auth_page()

    pending = policy.list_actions(status="pending")
    cards = []
    for a in pending:
        changes = "".join(f"<li>{html.escape(str(c))}</li>" for c in a.get("changes", []))
        diff = (f"<pre>{html.escape(a['diff'])}</pre>" if a.get("diff") else "")
        params = html.escape(json.dumps(a.get("params", {}), indent=1)[:3000])
        cards.append(f"""
        <div class="card">
          <h3>{html.escape(a['summary'])}<span class="badge">{a['domain']}.{a['tool']}</span></h3>
          <div class="meta">#{a['id']} · requested {a['created_at']} · kind: {a['action_kind']}</div>
          {f'<ul class="changes">{changes}</ul>' if changes else ''}
          {diff}
          <details><summary class="meta">raw parameters</summary><pre>{params}</pre></details>
          <p>
            <form method="post" action="/approvals/{a['id']}/approve"><button class="approve">Approve &amp; execute</button></form>
            <form method="post" action="/approvals/{a['id']}/reject"><button class="reject">Reject</button></form>
          </p>
        </div>""")

    audit_rows = "".join(
        f"<div class='audit'>{e.get('ts', '')} — <b>{html.escape(e.get('event', ''))}</b> "
        f"{html.escape(e.get('domain', ''))}.{html.escape(e.get('tool', ''))}: "
        f"{html.escape(str(e.get('summary', e.get('error', ''))))}</div>"
        for e in policy.read_audit(40))

    body = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <title>MCP Tools — Approvals</title><style>{_PAGE_CSS}</style></head><body>
    <header><h1><span>MCP Tools</span> — Write Approvals</h1>
    <div class="meta">{len(pending)} pending</div></header><main>
    {''.join(cards) if cards else '<div class="empty">No write actions are waiting for approval.</div>'}
    <h2>Recent activity</h2>{audit_rows or '<div class="empty">No activity yet.</div>'}
    </main></body></html>"""
    resp = HTMLResponse(body)
    token = request.query_params.get("token")
    if token and token == config.APPROVALS_TOKEN:
        resp.set_cookie("approvals_token", token, httponly=True, max_age=86400 * 30)
    return resp


async def resolve_action(request: Request):
    if not _authorized(request):
        return _auth_page()
    approve = request.path_params["verb"] == "approve"
    ok, message = policy.resolve_action(request.path_params["action_id"], approve)
    if not ok:
        return HTMLResponse(f"<style>{_PAGE_CSS}</style><main><div class='card'>"
                            f"<h3>{html.escape(message)}</h3>"
                            f"<p><a href='/approvals' style='color:#5ba8d4'>back</a></p>"
                            f"</div></main>", status_code=409)
    return RedirectResponse("/approvals", status_code=303)


async def context_node(request: Request):
    """Markdown node of the documentation tree; helpful 404 for unknown paths."""
    path = "/".join(p for p in (request.path_params.get("domain"),
                                request.path_params.get("tool")) if p)
    text = await tree.render(path)
    if text is None:
        return PlainTextResponse(
            f"Unknown context path '/{path}'. Valid: /context, /context/<domain>, "
            f"/context/<domain>/<tool>. Mounted domains: {', '.join(sorted(domains))}.",
            status_code=404)
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


async def healthz(request: Request):
    return JSONResponse({"status": "ok", "domains": sorted(domains),
                         "skipped": skipped_domains(),
                         "pending_approvals": len(policy.list_actions(status="pending"))})


async def root(request: Request):
    return RedirectResponse("/approvals", status_code=302)


async def slash_redirect(request: Request):
    """The MCP apps live at slash-terminated mounts (/mcp/, /mcp/web/); 307
    preserves method+body for clients that hit the bare path."""
    return RedirectResponse(request.url.replace(path=request.url.path + "/"),
                            status_code=307)


# ── Assemble & run ─────────────────────────────────────────────────────────────

routes = [
    Route("/healthz", healthz),
    Route("/context", context_node),
    Route("/context/{domain}", context_node),
    Route("/context/{domain}/{tool}", context_node),
    Route("/approvals", approvals_page),
    Route("/approvals/{action_id}/{verb:str}", resolve_action, methods=["POST"]),
    Route("/", root),
    # Domain endpoints must precede the catch-all /mcp mount. Exact bare paths
    # 307 to their slash-terminated mounts.
    *[Route(f"/mcp/{name}", slash_redirect, methods=["GET", "POST", "DELETE"])
      for name in domain_apps],
    *[Mount(f"/mcp/{name}", app=app) for name, app in domain_apps.items()],
    Route("/mcp", slash_redirect, methods=["GET", "POST", "DELETE"]),
    Mount("/mcp", app=composed_app),
]

app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
