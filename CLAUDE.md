# makerops-ai

**Private** agentic AI ecosystem layered on the public
[makerops-core](https://github.com/makerops-labs/makerops-core) stack.
Deliberately split from core (2026-07-04, public history scrubbed): the user
wants to slow AI adoption/job displacement — only well-known foundational
tools stay public. **Never move or commit this repo's content into
makerops-core**, and keep any core-side reference local-only (core's
`.git/info/exclude`, never its tracked `.gitignore`).

## Services (each a self-contained compose project, core conventions apply)

| Service | Port | Notes |
| --- | --- | --- |
| openwebui | 8080 | Chat UI. Workspace-model presets live in `openwebui/contexts/*.md` (git source of truth; recreate in UI by hand). All presets start with `contexts/_baseline.md`. |
| smolagents | 8090 | Agent workspace (Gradio). Agents in `smolagents/agents/`; code is bind-mounted — `docker restart smolagents` reloads it, rebuild only on lockfile change. |
| searxng | 8098 | Private metasearch; JSON API backs web tools. |
| mcp-tools | 8099 | FastMCP tool server; per-domain endpoints `/mcp/<domain>/`; human write-approvals at `/approvals`; doc tree at `/context` (see below). |
| speech | 8091 STT / 8093 TTS | speaches (whisper) + Kokoro, CPU-only on purpose. |
| trellis | 8094 | Image-to-3D (TRELLIS-image-large → GLB). GPU-heavy, start-on-demand only; serve.py is bind-mounted (restart to reload). Backs the `trellis` tool domain. |

Hermes Agent is host-level (not Docker): per-project memory profiles under
`~/.hermes/profiles/` — see `docs/hermes-setup.md`; never share a profile
across projects.

## Model hierarchy (canonical table in README.md)

Lead-per-domain: best benchmark performer that fits the hardware leads;
same-expertise lower-benchmark models (plus cross-lineage `gpt-oss:20b`)
review to catch blind spots. Currently: `qwen3.6:35b` coding,
`qwen3.5:9b`/`qwen3.5:9b-64k` general+vision, `qwen3-embedding:0.6b` RAG,
`qwen3.6:35b-64k` default chat/dispatch. Switch leads on benchmark evidence
(no local A/B gate); old lead becomes a reviewer. On a switch update:
`SMOLAGENTS_*_MODEL_ID` env vars, `openwebui/contexts/*.md` base models,
README table. The debate system applies the same reviewer-decorrelation
reasoning to its critic persona (defaults to `gpt-oss:20b`, same as the
reviewer pools) — see the "Debate system" bullet below.

## Architecture facts that cost debugging time

- **Tool docs are a progressive-disclosure tree**: `GET /context[/<domain>
  [/<tool>]]` on mcp-tools, mirrored by the `tools_help(path)` tool on every
  domain endpoint. smolagents injects the root manifest into every agent's
  instructions (`agents/context.py` → `with_baseline`; custom-agent template
  included). Long tool lists degrade local models — attach few domains,
  discover the rest via the tree.
- `tools_help` exists on EVERY domain endpoint → agents combining domains
  must merge with `agents/tools.get_domains_tools(*domains)` (dedup);
  plain concatenation crashes agent init on duplicate names.
- `docker compose restart` does NOT re-read `.env` — use
  `docker compose -p <name> up -d`. Inline comments after `=` in `.env`
  become the value.
- smolagents/mcpadapt `MCPClient` hangs forever on a 404 MCP URL —
  `agents/tools.py` pre-checks `/healthz`; keep that pattern.
- Write tools' docstrings start with `WRITE ACTION` and may return
  `PENDING APPROVAL #id` — surface it, never retry (policy in
  `mcp-tools/tools/policy.py`, tiers per user trust model).
- Open WebUI stores everything UI-side in its DB: presets, RAG embedding
  model (`qwen3-embedding:0.6b`), Audio (STT 8091 / TTS 8093), tool
  connections — the repo docs are recreate-from-git instructions
  (`docs/ai-setup-checklist.md` is the walkthrough).
- **Agent job queue is a shared directory**: `smolagents/data/smolagents/
  jobs`, bind-mounted into mcp-tools as `/agent-jobs`. mcp-tools
  (`agent_dispatch`) only creates `queued` records; the smolagents worker
  thread (`agents/jobs.py`, started by `app.py`) owns all other status
  transitions and runs one job at a time (single model in VRAM). Long jobs
  run in segments resuming from `jobs/<id>/workspace/synopsis.md`. Adding
  the volume needed `docker compose -p mcp-tools up -d` (recreate) —
  remember `restart` never applies compose/volume/.env changes.
- **Project workspaces are a different thing from the job queue above**:
  `~/workspace/<project-name>` directories are user-created **siblings of
  `~/workspace/makerops/`** (never inside it), registered and read/written
  via mcp-tools' `project` domain (`tools/project.py`). Reads span all of
  `~/workspace` (prior-art browsing, including this stack's own source);
  writes are confined to one registered project and execute immediately
  (notify tier). `~/workspace/makerops/` itself can never be registered as
  a write target — that subtree stays governed by `propose_code_change`/
  `redeploy` instead. The mount (`WORKSPACES_ROOT` → `/workspaces`) lives
  only in mcp-tools, never smolagents, so even the `manager`/`coder`
  `CodeAgent`s reach it only through the `project_*` tools, not raw
  `pathlib`. Every registered project gets a `PROJECT_CONTEXT.md` seeded at
  its root — the always-read-first orientation doc for a stateless agent
  resuming the project later. Commands can also be run against a
  registered project (`project_run_command`) inside an ephemeral,
  resource-capped, socket-less container launched by `sandbox/` — a second
  Docker-socket-holding service alongside `redeploy` — network access is
  allowed (bridge), but the ephemeral container never gets the Docker
  socket and only that one project directory is mounted. WSL2 quirk that
  bit us building it: docker-py's `containers.run()` needs its own explicit
  `dns=[...]` (same broken-bridge-resolver issue as every build in this
  repo, but this one isn't a compose file so there's no `dns:` key to
  inherit from). Also: the runtime image's Debian base rejects bare `pip
  install` (PEP 668) unless `PIP_BREAK_SYSTEM_PACKAGES=1` is set in the
  container's env — it's a throwaway container with no system Python to
  protect, so this is set unconditionally.
- **Debate system is a second, parallel job queue**: `smolagents/data/
  smolagents/debates`, bind-mounted into mcp-tools as `/agent-debates`
  (same ownership split as the job queue — mcp-tools' `debate_start`
  creates `session.json` + the first turn's queued job; the smolagents
  worker, `agents/jobs.py`'s `_advance_debate`, owns every other
  transition, including queuing each following turn). A debate turn IS an
  ordinary job (tagged `job["debate"]`), run by a *separate* dedicated
  orchestrator (`agents/debate_manager.py`, its own `CodeAgent` built once
  alongside the general `manager`) — never the general manager, whose
  `_PROCEDURE` would actively fight "delegate this turn to exactly one
  persona and relay verbatim." Turn advancement (deciding whether to queue
  another turn and who speaks next) is deterministic Python, never an LLM
  tool call — same reasoning as the rule that a job's own manager never
  gets dispatch tools (`manager.py`'s `_MANAGER_AGENT_TOOLS` comment): an
  LLM inside a job must never be the one that triggers the next job. Two
  narrow, explicitly-scoped exceptions mirror the job queue's own
  `queued→cancelled` carve-out: mcp-tools may flip a debate `stuck→active`
  (`debate_resume`) or any non-terminal status `→cancelled`
  (`debate_cancel`). Entrepreneur/monitor personas default to the
  `qwen3.6:35b-64k` lead (same as Task Dispatcher) — stop `trellis` first,
  same RAM-starvation gotcha as opening that chat, since an unattended
  debate hits it just as hard. Round files are prose by a doubly-enforced
  contract (`agents/debate/format.py`: prompt block + `final_answer_checks`
  rejection, plus `jobs.py`'s `_clean_round_text` fence-unwrap backstop) —
  local models otherwise relay raw python/JSON that poisons the next
  turn's input. Every debate ends with ONE auto-queued closing monitor
  turn in SYNTHESIS MODE (status `concluding`) that writes the
  human-facing `summary.md`, served by `debate_result` — that file is the
  deliverable; rounds are the working record. Turn orchestration can also
  consult the `researcher` agent (at most once, before the persona) for a
  sourced brief.

## Dependencies on makerops-core (sibling checkout `../makerops-core`)

- **Ollama** (11434) serves all models; the `qwen3.5:9b-64k` derivative is
  created via Modelfile (checklist §1). **ComfyUI** (8188) backs the comfyui
  tool domain.
- **name-proxy** integration is drop-in only: copy `proxy/local-ai.conf.template`,
  `proxy/local-services.json`, `proxy/icons/ → html/local-icons/` into core
  (gitignored there); recreate proxy for route changes (`proxy/README.md`).
- Core is symlinked back at `makerops-core/ai/private` — navigation only;
  always run services from real paths.
- Core-side conventions (env files, WSL2 DNS/`network: host`, teardown
  patterns) are documented in core's `CLAUDE.md` and `docs/env-conventions.md`.

## Hardware envelope

RTX 4070 Ti SUPER 16 GB VRAM; WSL2 capped at 24 GB RAM (`.wslconfig`).
Models >16 GB (both coding models) partially offload to RAM — if a load is
OOM-killed (`signal: killed` during tensor load), free RAM or raise the cap.
Speech stays CPU-only to protect VRAM. Flash attention is on in Ollama.
TRELLIS wants most of the 16 GB during a generation — run it while the LLMs
are idle (or accept slow WSL shared-memory spill); it unloads its pipeline
after 10 min idle and the whole service is start-on-demand. **Idle-unload
frees VRAM only: the trellis container keeps ~5.4 GB host RAM while up,
which OOM-kills qwen3.6:35b* loads (they need ~10 GB host for the VRAM
overflow) — stop trellis before using the 35b models.**
