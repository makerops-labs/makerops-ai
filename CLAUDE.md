# makerops-ai

**Public** (since 2026-08-10) agentic AI ecosystem layered on the public
[makerops-core](https://github.com/makerops-labs/makerops-core) stack.
Split from core (2026-07-04, core's public history scrubbed of AI-ecosystem
work) to keep the two repos' version control separate; both are now public,
but the split itself stays — **never move or commit this repo's content into
makerops-core**, and keep any core-side reference local-only (core's
`.git/info/exclude`, never its tracked `.gitignore`).

## Services (each a self-contained compose project, core conventions apply)

| Service | Port | Notes |
| --- | --- | --- |
| openwebui | 8080 | Chat UI. Workspace-model presets live in `openwebui/contexts/*.md` (git source of truth; recreate in UI by hand). All presets start with `contexts/_baseline.md`. Runs the upstream image + in-place source patches in `openwebui/patches/` (re-applied by `start.sh`; lost on image recreate). |
| smolagents | 8090 | Agent workspace (Gradio). Agents in `smolagents/agents/`; code is bind-mounted — `docker restart smolagents` reloads it, rebuild only on lockfile change. **Check the job queue is idle first** (`GET :8099/healthz` → `jobs`): a restart kills any running job mid-step (`failed: worker restarted mid-job`). |
| searxng | 8098 | Private metasearch; JSON API backs web tools. |
| mcp-tools | 8099 | FastMCP tool server; per-domain endpoints `/mcp/<domain>/`; human write-approvals at `/approvals`; doc tree at `/context` (see below). |
| n8n-mcp | 8104 | czlonkowski/n8n-mcp (HTTP mode) wrapping the makerops-core n8n public API with node schemas + templates + validation, so an LLM can *author* workflows. Feeds the "n8n Architect" preset (direct) and the `n8n_builder` persona (via the mcp-tools `n8nmcp` proxy domain). Destructive tools disabled in-process (`DISABLED_TOOLS`); **no** approval gate on this path — unlike the mcp-tools `n8n` domain (read + gated trigger), which is separate and unchanged. |
| speech | 8091 STT / 8093 TTS | speaches (whisper) + Kokoro, CPU-only on purpose. |
| trellis | 8094 | Image-to-3D (TRELLIS-image-large → GLB). GPU-heavy, start-on-demand only; serve.py is bind-mounted (restart to reload). Backs the `trellis` tool domain. |

Hermes Agent is host-level (not Docker): per-project memory profiles under
`~/.hermes/profiles/` — see `docs/hermes-setup.md`; never share a profile
across projects.

## Model hierarchy (canonical table in README.md)

Lead-per-domain: best benchmark performer that fits the hardware leads;
same-expertise models (plus cross-lineage `gpt-oss:20b`) review to catch
blind spots. Since 2026-08-26 this also splits by **workload latency
sensitivity**: interactive/chat-facing roles keep the fastest good-enough
model, unattended background queues (devteam engineer phases, hardware
specialist, reviewers) can prefer a slower higher-benchmark model instead —
see `docs/model-stack.md`'s 2026-08-26 pass. Currently: `qwen3.6:35b`
coding lead (interactive — chat coder, Coding Assistant preset),
`qwen3.6:35b-64k` general/agents AND default chat/dispatch (one resident
model; the trellis stop-first RAM gotcha now applies to agent jobs too),
`qwen3.8:27b-64k` hardware/KiCad specialist + coding reviewer + devteam
engineer phases (dense; successor to qwen3.6:27b, out-benchmarks the 35b
coding lead — SWE-bench Pro 61.7 vs — Terminal-Bench 2.1 73.0 vs 63.4 —
but measured ~14 tok/s generation on the 3.6 generation (same
architecture/footprint) — too slow to lead *interactive* agentic loops,
fine for background ones; the `-64k` derivative is required, not the
bare tag — this model's reasoning exhausts Ollama's 4k default context
before producing output, observed 2026-08-28), `qwen3.5:9b` vision +
light presets (former
general lead, now also a general reviewer), `qwen3-embedding:0.6b` RAG.
Switch leads on benchmark evidence (no local A/B gate); old lead becomes a
reviewer. On a switch update: `SMOLAGENTS_*_MODEL_ID` env vars,
`openwebui/contexts/*.md` base models, README table. The debate system
applies the same reviewer-decorrelation reasoning to its critic persona
(defaults to `gpt-oss:20b-32k` — a num_ctx derivative of the reviewer
pools' model; the base serves at Ollama's 4k default, which truncates a
debate turn mid-answer) — see the "Debate system" bullet below.

## Architecture facts that cost debugging time

- **Best-practice guidance library**: `docs/guidance/` (git source of
  truth) holds distilled AI operating practices — planning as state
  tracking, external verification + detailed feedback, negative examples,
  small-model tooling, knowledge distillation for persistent memory, local
  fine-tuning feasibility (from arXiv:2509.13351 + 2506.10943; see its
  README for the add-a-distillation convention). Read the doc matching
  what you're changing. Served to agents at `/context/guidance`
  (`tools_help('guidance')`), mirrored to Outline collection "Guidance" —
  re-publish after meaningful edits. Write tools follow its Preconditions/
  Effects/Failure-modes docstring convention. Related:
  `docs/model-development-playbook.md` (roadmap to self-trained
  specialized models) and `experiments/seal-lora/` (working single-round
  self-edit → QLoRA → eval prototype).
- **Tool docs are a progressive-disclosure tree**: `GET /context[/<domain>
  [/<tool>]]` on mcp-tools, mirrored by the `tools_help(path)` tool on every
  domain endpoint. smolagents injects the root manifest into every agent's
  instructions (`agents/context.py` → `with_baseline`; custom-agent template
  included). Long tool lists degrade local models — attach few domains,
  discover the rest via the tree.
- `tools_help` exists on EVERY domain endpoint → agents combining domains
  must merge with `agents/tools.get_domains_tools(*domains)` (dedup);
  plain concatenation crashes agent init on duplicate names.
- **`n8nmcp` is a passthrough domain**: `mcp-tools/tools/n8nmcp.py` is a
  `FastMCP.as_proxy` of the standalone `n8n-mcp` service (:8104), so the
  smolagents `n8n_builder` persona can reach n8n-mcp's tools (`get_domains_tools`
  only speaks to mcp-tools endpoints). Per-request proxy sessions — no
  long-lived backend socket. If n8n-mcp is stopped, mcp-tools still starts (the
  proxy is lazy) but `docs_tree._tools()` would 500 the whole `/context` tree
  and every agent's `tools_help('')` — hence its per-domain try/except guard,
  which degrades just that one domain to empty. Open WebUI's n8n Architect
  preset connects to :8104 directly; only smolagents goes through the proxy.
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
- **Open WebUI runtime patches** live in `openwebui/patches/` — in-place
  edits to the upstream image's Python (no Dockerfile of our own), applied
  by `start.sh` via `patches/apply.sh`, idempotent, **lost on `docker
  compose up -d`/`pull`** (survive `restart`). Current patch:
  `merge-model-toolids.py` — the image is pinned to a `vX.Y.Z` tag in
  `openwebui/docker-compose.yml` (currently `v0.11.3`; bump deliberately —
  the 0.11.x line has shipped migration regressions). Stock Open WebUI
  (through 0.11.3) applies a Workspace Model's
  default `skillIds` server-side but not `toolIds`, and the frontend only
  sends `tool_ids` on an in-chat model switch, so a preset chat opened
  directly (or a cloned/continued thread) runs **toolless**. The patch
  mirrors the `skill_ids` merge in `middleware.py:process_chat_payload`.
  If a preset reports "no tools", first check `apply.sh` ran since the
  last recreate.
- **Agent job queue is a shared directory**: `smolagents/data/smolagents/
  jobs`, bind-mounted into mcp-tools as `/agent-jobs`. mcp-tools
  (`agent_dispatch`) only creates `queued` records; the smolagents worker
  thread (`agents/jobs.py`, started by `app.py`) owns all other status
  transitions and runs one job at a time (single model in VRAM). Long jobs
  run in segments resuming from `jobs/<id>/workspace/synopsis.md`. Adding
  the volume needed `docker compose -p mcp-tools up -d` (recreate) —
  remember `restart` never applies compose/volume/.env changes.
  **Step-budget exhaustion is handled by the worker, not the model**:
  smolagents' forced max-steps final answer bypasses `final_answer_checks`
  (verified in 1.26 source), so `jobs.py` detects the recorded
  `AgentMaxStepsError` after each segment and auto-continues from
  `synopsis.md` — but only when the synopsis was touched during that
  segment (no-progress guard), else `needs_attention`. Step budgets are
  role-shaped: researcher deep (`SMOLAGENTS_RESEARCHER_MAX_STEPS`, 40),
  debate personas bounded (`SMOLAGENTS_DEBATE_PERSONA_MAX_STEPS`, 12),
  everyone else `SMOLAGENTS_MAX_STEPS` (12). A managed agent's whole run
  is ONE step of its caller, so deep research doesn't eat the manager's
  job budget.
- **MCP tool sessions are process-lifetime and die silently when
  mcp-tools restarts** (2026-07-16 yield-logic incident: both devteam
  engagements ran every phase with dead `project_*` tools — zero files
  landed while phases self-reported "completed"). Worker defenses, all in
  `agents/jobs.py` + `agents/tools.py`: (1) pre-job
  `tools_session_alive()` round trip — on a dead session the worker
  resets the tool cache and REBUILDS all agents (agents hold Tool objects
  bound to the dead clients, so reuse is never safe), or parks the job
  failed + session stuck when mcp-tools is truly down; (2) deterministic
  deliverable-landing validation in `_advance_devteam`/`_advance_hardware`
  — a "completed" phase whose deliverables point into `/data` scratch, or
  (for file-mandate kinds) are only inline document text, parks the
  session stuck instead of advancing (judged from location shape, not the
  declared `type=`, which models mislabel); (3) explicit model-call
  timeout (`SMOLAGENTS_MODEL_TIMEOUT_S`, 30 min) so a wedged Ollama call
  becomes a failed job instead of an eternally "running" one blocking the
  single-threaded worker; (4) a stall watchdog firing one `job.stalled`
  webhook after `SMOLAGENTS_JOB_STALL_NOTIFY_S` (45 min) of heartbeat
  silence — notify-only, threads can't be killed. Caveat: the Gradio chat
  UI's agents (`app.py`) are still built once at startup with no
  self-heal — after an mcp-tools restart, restart smolagents too if the
  chat UI's tools matter. `PYTHONUNBUFFERED=1` is set in compose so the
  `[jobs]`/`[tools]` diagnostics actually reach `docker logs` (they were
  fully lost during the incident).
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
  ordinary job (tagged `job["debate"]`) and the worker runs the named
  persona DIRECTLY (`_run_debate_turn`) — there is deliberately NO
  orchestrator LLM between the worker and a persona. A `debate_manager`
  CodeAgent relay existed briefly and failed on every real run: its whole
  job was shuttling the persona's argument into a report tool, and the
  local model did that by re-typing the text into giant string literals →
  SyntaxError → step exhaustion → forced junk answer. Task assembly, prose
  enforcement (persona `final_answer_checks`), the monitor's `VERDICT:`
  line (regex), and turn advancement are all deterministic Python — same
  reasoning as the rule that a job's own manager never gets dispatch tools
  (`manager.py`'s `_MANAGER_AGENT_TOOLS` comment): an LLM inside a job
  must never be the trigger or the plumbing for the next job. Personas in
  `SMOLAGENTS_DEBATE_RAW_PERSONAS` (default: critic) run as RAW completions
  — one plain generation, the audit reviewer pool's pattern — because
  gpt-oss writes excellent arguments but persistently fumbles smolagents'
  tool-calling protocol (plain-text answers, typed-out pseudo
  `final_answer()` calls), burning its step budget on submission mechanics.
  A raw persona's prompt MUST end with `RAW_MODE_NOTE` (`debate/format.py`,
  wired in `jobs.py`'s `_worker_loop`): without it, any tool mention in the
  persona text ("use your web tool… if you have one") makes tool-trained
  gpt-oss emit a tool call into the void and return an EMPTY visible answer
  (thoughts only, `done_reason: stop`) → "persona produced no usable round"
  → debate stuck. Topic-dependent and stochastic — it worked for days
  before first failing; diagnose via native Ollama `/api/chat` (shows the
  `thinking`/`content` split), not the OpenAI-compat endpoint. Two
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
- **Devteam engagements are a fourth parallel queue**: `smolagents/data/
  smolagents/devteam`, bind-mounted into mcp-tools as `/agent-devteam`
  (same ownership split — mcp-tools' `devteam_start` creates
  `session.json` + queued phase jobs, and performs exactly five
  user-driven transitions: `devteam_answer`, `devteam_approve`,
  `devteam_revise`, `devteam_resume`, `devteam_cancel`; the worker,
  `agents/jobs.py`'s `_advance_devteam`, owns everything else, including
  auto-queuing the next phase past an UNGATED completion, debate-style).
  A phase run IS an ordinary job (tagged `job["devteam"]`) executed by
  the lead architect (`agents/devteam/`, a manager-shaped CodeAgent with
  its own specialist team, never registered on the general manager) via
  the shared segment/synopsis loop (`_run_report_segments`). The
  deliberate inversion vs. debates: phases whose kind/name is in the
  session's `gates` list (default: requirements, architecture, docs)
  PARK as `awaiting_review` — only a human-driven mcp-tools call queues
  what runs next; `needs_clarification` parks as `awaiting_input` and
  resumes via `devteam_answer` with the answers injected — this is the
  one queue where "the team cannot ask questions mid-run" does NOT
  apply. Phase workspaces are per-PHASE
  (`devteam/<id>/phases/<NN>-<name>/workspace/`), not per-job, so
  synopsis working memory survives revision/answer re-runs. The
  architecture phase's milestone plan is parsed by deterministic worker
  code (`_extract_milestones`) — missing/malformed → session `stuck`,
  never repaired by code or guessed. Webhook events: `devteam.needs_input`
  (carries `questions`), `devteam.milestone`, `devteam.stuck`,
  `devteam.completed`.
- **Hardware engagements are a fifth parallel queue**, structurally
  forked from devteam above rather than sharing its code (only
  `_extract_milestones` was generic enough to parameterize and share —
  see `agents/jobs.py`'s hardware section for why forking, not
  generalizing, was the deliberate call): `smolagents/data/
  smolagents/hardware`, bind-mounted into mcp-tools as `/agent-hardware`.
  `embedded_architect` (never registered on the general manager, built
  once in `_worker_loop`) orchestrates `kicad_specialist` — pinned to
  `qwen3.8:27b-64k` via `HARDWARE_SPECIALIST_MODEL_ID`, a deliberate
  deviation from every other `*_MODEL_ID`'s empty-default-falls-back-to-
  lead convention — through requirements → architecture (emits a
  milestone plan, one per functional block, validated by the same
  `_extract_milestones`) → per-block milestone phases → **fab-review** →
  docs. `fab-review` has no devteam analog: it is gated in every gate
  preset except `none`, unconditionally, because it precedes the real,
  hard-to-reverse cost of sending a design to a manufacturer — unlike a
  milestone gate, nothing overrides it. No real KiCad tooling exists yet:
  every phase's deliverables are documents (an Embedded Design Brief, then
  per-block KiCad Build Plans), and a build plan's manufacturing-outputs
  section is explicitly intent-only. See `docs/hardware-agents-guide.md`
  (user-facing guide + deferred-tooling roadmap) and
  `docs/guidance/hardware-design-handoff.md` (document schemas + handoff
  discipline). Webhook events: `hardware.needs_input`,
  `hardware.milestone`, `hardware.stuck`, `hardware.completed`.

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
Models >16 GB (`qwen3.6:35b*` and `qwen3.8:27b-64k`) partially offload to RAM — if a load is
OOM-killed (`signal: killed` during tensor load), free RAM or raise the cap.
Speech stays CPU-only to protect VRAM. Flash attention is on in Ollama.
TRELLIS wants most of the 16 GB during a generation — run it while the LLMs
are idle (or accept slow WSL shared-memory spill); it unloads its pipeline
after 10 min idle and the whole service is start-on-demand. **Idle-unload
frees VRAM only: the trellis container keeps ~5.4 GB host RAM while up,
which OOM-kills qwen3.6:35b* loads (they need ~10 GB host for the VRAM
overflow) — stop trellis before using the 35b models.**
