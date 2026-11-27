# Operations notes: tips, gotchas and debugging

Hard-won specifics — check here before deep-diving (core-side basics like
`.env` inline comments and WSL2 DNS are in makerops-core's README):

- **`docker compose restart` does NOT re-read `.env`** — token/policy/model
  changes need `docker compose -p <project> up -d` (recreate). Code changes
  in smolagents/mcp-tools only need a restart (source is bind-mounted);
  rebuild only when `pyproject.toml`/`uv.lock` change.
- **First reply after a model switch is slow.** Only one model lives in VRAM
  at a time; swapping loads ~7–23 GB. `docker exec ollama ollama ps` shows
  what's loaded and the CPU/GPU split.
- **Large-model OOM signature**: `llama-server process has terminated:
  signal: killed` during load = not enough free system RAM for the VRAM
  overflow. Free RAM or raise the WSL2 cap (24 GB works for the current
  hierarchy on a 16 GB GPU). **Check `docker ps` for a running `trellis`
  container first** — its idle-unload only frees VRAM, the container still
  holds ~5.4 GB of host RAM the whole time it's up, which is enough by
  itself to starve a `qwen3.6:35b*` load. `trellis/stop.sh` before using
  Coding Assistant, Task Dispatcher, or any 35b-class chat.
- **A chat "has no tools"?** Tools attach per workspace-model, per-base-model
  (Admin Settings → Models), or per-chat (+ menu) — a bare-model thread has
  none. Old threads also bias the model toward its earlier "no tools"
  claims; test in a fresh thread. Set **Function calling: Native** for the
  qwen leads.
- **Domain missing from tools?** `curl :8099/healthz` — domains without an
  API token are skipped at startup (by design). Add the token to
  `mcp-tools/.env` and recreate.
- **MCP client hangs forever** → it's pointed at an unmounted domain (404s
  hang mcpadapt). smolagents pre-checks `/healthz` (`agents/tools.py`); keep
  that pattern in new consumers. Endpoints need the trailing slash
  (`/mcp/web/`); bare paths get a 307.
- **Agents combining several domains** must merge tools with
  `agents/tools.get_domains_tools(*domains)` — every endpoint carries
  `tools_help`, and duplicate tool names crash agent init.
- **Long tool lists degrade local models.** Attach few domains per
  agent/preset; let `tools_help` handle discovery. Prefer `/mcp/<domain>/`
  over the composed `/mcp/`.
- **Open WebUI settings live in its DB**, not in git — presets, embedding
  model, audio, connections are recreate-from-git per the checklist. Its
  web-search env vars seed the DB on first boot only.
- **Don't commit runtime state**: `.env` and `data/` are gitignored
  everywhere; committed config must not live in a `config/` dir (that glob
  is ignored).
- **Logs**: `docker compose -p <project> logs -f`; agent traces can go to an
  OTLP collector via `OTEL_EXPORTER_OTLP_ENDPOINT` (smolagents `.env`).
- **Never commit this repo's content into makerops-core** — see
  [CLAUDE.md](../CLAUDE.md) and the README's
  [Local integration](../README.md#local-integration-with-makerops-core) section.
- **A `propose_code_change` diff is rejected before you ever see it** if
  it's not valid Python syntax (`ast.parse` pre-check) — that only catches
  syntax errors, not a syntactically valid but wrong change; review is
  still what catches those.
- **`redeploy.reverted` in `/approvals` means the file is already back to
  its prior state** — the change was tried, failed its health check, and
  was rolled back automatically. `git diff`/`git log` on the working tree
  shows exactly what was attempted; there's nothing to manually undo.
- **Approving a change to mcp-tools' own source restarts the process
  handling your approval, mid-flow** — expected, and exactly why
  `redeploy` is a separate service rather than mcp-tools restarting
  itself: it keeps working (and reports the outcome) independent of
  whether mcp-tools is reachable at that moment.
- **Rejecting a proposal is cheap** — no retry pressure, no penalty;
  `maintainer` files independent proposals each review cycle.

Moved from the top-level README (2026-11-26) to keep it short.
