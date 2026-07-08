# smolagents — AI Agent Workspace

smolagents is Hugging Face's minimal agent framework. This service is both a **Python workspace** for authoring your own agents and a **Docker service** that runs them behind a Gradio chat UI — all backed by the local Ollama server, so nothing leaves the host.

It ships with eight starter agents (models follow the lead-per-domain hierarchy in [README.md](../README.md)):

| Agent | Model | Role |
| --- | --- | --- |
| `manager` | `qwen3.5:9b-64k` | Orchestrator served by the UI and the job worker — validates briefs, plans, delegates, audits by risk, reports (see "Orchestration") |
| `web_researcher` | `qwen3.5:9b-64k` | Web search + page reading (mcp-tools web domain, SearXNG-backed) |
| `coder` | `qwen3.6:35b` | Writes and executes Python for data work and programming tasks |
| `ops` | `qwen3.5:9b-64k` | Operates the business stack via mcp-tools (wiki, inventory, projects, automation, helpdesk) |
| `writer` | `qwen3.5:9b-64k` | Written deliverables: docs, reports, summaries, marketing copy; publishes durable docs to Outline |
| `studio` | `qwen3.5:9b-64k` | Media assets: images (ComfyUI/FLUX), diagrams (draw.io), speech audio (Kokoro TTS), image→3D models (TRELLIS). No video |
| `auditor` | reviewer pool | Independent multi-model review of finished work (see below) |
| `maintainer` | `qwen3.5:9b-64k` | Self-improvement loop: reviews job/audit history, researches fixes, files Outline reports + Plane issues (see "Self-improvement loop") |

- **Docs:** <https://huggingface.co/docs/smolagents>
- **GitHub:** <https://github.com/huggingface/smolagents>

---

## Attribution

**smolagents** is open-source software developed and maintained by [Hugging Face](https://huggingface.co) and the [smolagents contributors](https://github.com/huggingface/smolagents/graphs/contributors), made freely available under the [Apache 2.0 License](https://github.com/huggingface/smolagents/blob/main/LICENSE).

---

## Prerequisites

Ollama must be running with the lead models (and, for the auditor, the
reviewer pool) pulled before agents can run:

```bash
cd ../../makerops-core/ai/ollama && ./start.sh
docker exec ollama ollama pull qwen3.6:35b       # coding lead (~23 GB, MoE 3B active)
docker exec ollama ollama pull qwen3.5:9b        # general lead (~6.6 GB)
# 64K-context variant the agents use (Ollama's default context is too small):
printf 'FROM qwen3.5:9b\nPARAMETER num_ctx 64000\n' | docker exec -i ollama sh -c 'cat > /tmp/Modelfile && ollama create qwen3.5:9b-64k -f /tmp/Modelfile'
# Reviewer pool for the auditor:
docker exec ollama ollama pull qwen3-coder:30b   # ~19 GB
docker exec ollama ollama pull gemma4:12b        # ~7.6 GB
docker exec ollama ollama pull gpt-oss:20b       # ~13 GB
```

See [makerops-core/ai/ollama/README.md](../../makerops-core/ai/ollama/README.md) for Ollama setup and model management.

---

## Local Access

| | |
| --- | --- |
| **Web UI** | <http://localhost:8090> |
| **Via name-proxy** | <http://agents.localhost> |

---

## Setup

### Start

```bash
./start.sh
```

On first run this copies `.env.example` → `.env` (no secrets to generate), builds the image, and starts the container. Open <http://localhost:8090> and give the manager agent a task.

---

## Dev workspace

Agent code lives in [`agents/`](agents/) and is a normal uv-managed Python project — you can iterate without Docker at all:

```bash
uv sync                                                    # one-time: create .venv
OLLAMA_API_BASE=http://localhost:11434/v1 uv run python app.py
```

To add an agent, drop a `build_*_agent()` factory module in `agents/` (see `web_agent.py` for the pattern), get its LLM from `agents.model.get_model("coding" | "general")`, and wire it into `manager.py`'s `managed_agents` list.

**The container bind-mounts `agents/` and `app.py`**, so code edits only need a restart — no rebuild:

```bash
docker restart smolagents
```

Rebuild only when `pyproject.toml`/`uv.lock` change:

```bash
uv sync && ./start.sh   # start.sh always rebuilds the image
```

---

## Baseline tool awareness

Every agent's `instructions` automatically end with a **Tool environment**
section (`agents/context.py`): the root of the mcp-tools documentation tree
(`GET /context`) — one line per domain — plus guidance to drill down with the
`tools_help(path)` tool that every domain endpoint carries. Agents know what
exists across the whole stack without carrying the full tool catalog in
context, and inspect a tool's full usage doc before first use. If mcp-tools
is down at startup a static fallback is used (agents keep working).

Custom agents scaffolded by `agent_create` get the same wrapper
(`with_baseline`). Scaffolds created before this convention can be upgraded
by re-scaffolding or by hand-wrapping their `instructions=` with
`with_baseline(...)` from `..context`.

Agents that combine several domains must merge tools with
`tools.get_domains_tools(*domains)` — every domain endpoint carries
`tools_help`, and smolagents requires unique tool names per agent.

---

## Executor safety

smolagents `CodeAgent`s execute model-written Python. The stance here:

- **In the container** (normal service use): the default local executor is fine — the container is the sandbox. Code mounts are read-only, only `/data` is writable, and the only network dependency is Ollama. The Docker socket is deliberately **not** mounted.
- **On the host venv**: the agents keep a minimal `additional_authorized_imports` list (no `os`, `subprocess`, or `shutil`), and smolagents' interpreter blocks unauthorized imports. For untrusted or long-autonomy runs from the host, pass `executor_type="docker"` to `CodeAgent` so generated code runs in a throwaway container instead. (Not used here — see below.)

This is a different containment mechanism from the one backing
`project_run_command`: that's a **separate service** ([sandbox/](../sandbox/)),
not this CodeAgent-interpreter sandboxing, and not smolagents' own
`DockerExecutor` either (that's a Jupyter-kernel-over-websocket executor
for Python, needs the `docker` extra this image doesn't install, and would
require giving *this* container Docker socket access — exactly what the
bullet above rules out). `project_run_command` runs real shell commands in
throwaway, resource-capped containers with one project directory mounted,
launched by `sandbox/` (which holds the socket instead), never by
smolagents itself.

---

## MCP tools (mcp-tools)

Agents load their tools from the shared MCP tool server
([mcp-tools](../mcp-tools/)) when it is running:

- **web_researcher** uses the `web` domain (SearXNG-backed `web_search` +
  content-type-aware `fetch_url`) and falls back to the stock DuckDuckGo
  tools when the server is down.
- **ops** operates the business stack: Outline, InvenTree, Plane, n8n,
  FreeScout, trigger.dev. Only domains with an API token configured on
  mcp-tools contribute tools; the rest are skipped with a log line. Write
  tools follow the human approval policy described in the
  [mcp-tools README](../mcp-tools/README.md) — a gated write returns
  `PENDING APPROVAL #id` and the ops agent reports it instead of retrying.
- **writer** uses the `outline` domain to publish durable deliverables
  (collection "Agent Deliverables", dated names, job-id footer), plus the
  `project` domain to write docs/READMEs directly into a project workspace
  and to draft/keep its `PROJECT_CONTEXT.md` current.
- **studio** merges `comfyui`, `drawio`, `speech`, and `trellis` — images,
  diagrams, TTS audio, and image→3D GLB models. Video is out of scope and
  declared as such.
- **manager** holds the `agents` domain (`agent_create`, `agent_list`,
  `agent_read`, `propose_code_change`) so it can scaffold new specialist
  agents and propose stack self-improvements, plus the `project` domain
  (see "Project workspaces" below) for reading/writing a user-assigned
  project directory and running commands in it (`project_run_command`) —
  it has `coder` do this before marking a project job "review."
- **coder** holds only the `project` domain — its own output otherwise goes
  through its sandboxed Python interpreter (`pathlib`, scoped to
  `config.DATA_DIR`), which cannot reach a project directory at all; that's
  the point (see "Project workspaces" below). It also uses
  `project_run_command` to actually run a project's tests/linter/build
  rather than assume they pass.

### Orchestration (manager procedure)

The manager's instructions (`agents/manager.py::_PROCEDURE`) encode the
operating loop: **validate** the brief (vague → `needs_clarification` with
questions, never guess) → **plan and delegate** with long sub-task briefs →
**batch by model** (general-model work first, `coder` sub-tasks
consecutively, audits last — every swap of the big models costs minutes of
VRAM loading) → **audit by risk** (code-to-be-used / business effects /
publish-facing content get the auditor; drafts and exploration don't; a
brief's `audit: always|never` overrides) → **deliver** (durable docs to
Outline) → **report** as a JSON object (`status`, `summary`,
`deliverables`, `audit`, `attention`, `questions`, `next_steps`), enforced
by a lenient `final_answer_checks` validator. `planning_interval=5`
refreshes the plan mid-task; `SMOLAGENTS_MANAGER_MAX_STEPS` (default 20)
bounds each run.

### Background jobs (dispatch from Open WebUI or any MCP client)

`app.py` starts a **job worker thread** (`agents/jobs.py`) beside the
Gradio UI. mcp-tools' `agent_dispatch` tool writes a queued job record into
the shared queue (`data/smolagents/jobs/`, bind-mounted into mcp-tools as
`/agent-jobs`); the worker polls every 2 s, runs the manager on it (one job
at a time — single-GPU model residency), and owns every status transition
(`queued → running → completed | needs_clarification | needs_attention |
failed`; mcp-tools only creates `queued` records). Reports land in the task
inbox at `mcp.localhost/inbox`; `SMOLAGENTS_NOTIFY_WEBHOOK` (n8n) fires on
`job.completed` / `job.needs_clarification` / `job.needs_attention` /
`job.failed`.

**Segmented execution:** long jobs stay inside a bounded context. The
manager keeps `jobs/<id>/workspace/synopsis.md` (goal, key facts,
deliverables so far, open items) plus deeper notes files as working memory;
at a phase boundary it answers `status: "continuation"` and the worker
starts a fresh run from the brief + synopsis. `SMOLAGENTS_MAX_SEGMENTS`
(default 8) caps the loop — exceeding it finishes the job as
`needs_attention` with the synopsis as the report. The worker also writes
`jobs/roster.json` at startup (live roster consumed by `agent_list`) and
flips any job stuck in `running` to `failed` after a crash/restart.

### Project workspaces

Distinct from the per-job `jobs/<id>/workspace/` scratch dir above: a
**project** is a durable directory under `~/workspace/` that *you* create
and register (via the mcp-tools `project` domain — see
[mcp-tools/README.md](../mcp-tools/README.md) "Project workspaces"), where
an already-approved solution's code and docs live across many jobs, not
just one segment. Pass `project="<name>"` to `agent_dispatch` to target it;
`jobs.py::_format_task` then instructs the manager to read
`PROJECT_CONTEXT.md` first (always present once registered), survey the
project and any sibling directories as prior art with `project_glob`/
`project_grep`, and write via `project_write_file`/`project_edit_file` —
never raw `pathlib`, since the mount lives only in the mcp-tools container,
not here. `manager.py::_PROCEDURE` step 5b (PROJECT ORIENTATION) and the
DELIVER step encode this; reads span all of `~/workspace`, writes stay
confined to the one registered project, and writes execute immediately
(notify tier by default).

Before marking a project job "review" or done, the DELIVER step also has
`coder` actually run the project's test suite/linter via
`project_run_command` — an isolated, resource-capped, ephemeral container
with only that project mounted (network included, for installs), launched
by the separate [sandbox](../sandbox/) service, never smolagents itself —
and report the real result rather than assume the code works.

### Multi-model review (auditor)

The `auditor` agent implements the reviewer-pool convention: the lead model
of a domain produces work, and same-expertise models with lower benchmark
scores review it to catch the lead's blind spots — including `gpt-oss:20b`,
whose different lineage (OpenAI vs Qwen/Gemma) decorrelates the review.
Ask the manager for a "review" or "second opinion" on an artifact and it
delegates to the auditor, which queries each model in the domain's pool
sequentially (Ollama swaps one model in VRAM at a time) and merges the
findings into one severity-ordered report. Pools are configured via
`SMOLAGENTS_CODING_REVIEW_MODEL_IDS` / `SMOLAGENTS_GENERAL_REVIEW_MODEL_IDS`
in `.env`.

### Custom agents

`agent_create` (callable from any MCP client, including the manager itself)
scaffolds a new agent module into `agents/custom/<name>.py` from a fixed
template — review it with `git diff`, edit it by hand freely. The manager
auto-discovers every `build_*_agent()` in that package at startup:

```bash
docker compose -p smolagents restart   # pick up new custom agents
```

A custom module that fails to import is skipped with a log line, never fatal.

### Self-improvement loop

`maintainer` reviews the stack's own recent performance: `agent_job_history`
and `agent_audit_history` (mcp-tools `agents`/`approvals` domains) surface
job outcomes and write-action patterns from a recency window; it identifies
concrete, evidenced failure patterns (never vague impressions — a pattern
needs at least two instances or one clearly reproducible cause), writes an
evaluation report to Outline's **AI** collection, and files one Plane issue
per proposed improvement in the **Stack Improvements** project. It has no
web access itself — external research it flags gets delegated to
`web_researcher` by the manager, same as any other sub-task.

For well-scoped proposals the manager has `coder` draft the new file
content, then calls `propose_code_change` itself (the manager, not
`maintainer`, holds this tool — every code change traces back to one
place). This is a full `agents` domain tool, not a scaffold-only one:
`file_path` can be *any* file in the repo (`.env` files and anything under
`.git/` or a `data/` dir are hard-excluded — a confidentiality/integrity
boundary, not a trust one), diffed against the current content and routed
through the same gated approval flow as every other write in this stack.
Approving it writes the file and — if it's under `smolagents/` or
`mcp-tools/` — restarts the affected container via the separate
[redeploy](../redeploy/) service (the only thing with Docker socket
access); a failed health check triggers an automatic revert-and-restart
onto the known-good version. See the root [README.md](../README.md)
"Self-improvement loop" and [docs/ai-setup-checklist.md](../docs/ai-setup-checklist.md)
"§5e" for the full walkthrough and one-time setup.

---

## Files

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Single-container stack definition (built from `Dockerfile`) |
| `Dockerfile` | Bakes the uv-managed dependency set; code is bind-mounted over it |
| `pyproject.toml` / `uv.lock` | Python project — smolagents with toolkit/openai/mcp/telemetry/gradio extras |
| `agents/` | Agent package: config, model factory, telemetry, job worker, and the starter agents |
| `app.py` | Entry point: Gradio UI (manager agent, port 7860) + background job worker |
| `.env.example` | Configuration template |
| `start.sh` | Build image and start |
| `stop.sh` | Stop (data preserved) |
| `teardown.sh` | Full wipe with confirmation |

---

## Architecture

```text
Browser                              Open WebUI / any MCP client
  └─► localhost:8090 → Gradio UI      └─► mcp-tools agent_dispatch
          │                                   │ writes queued job
          ▼                                   ▼
        smolagents  (built from ./Dockerfile)
                ├─► job worker thread  (polls /data/jobs every 2s, one job at a time)
                ├─► manager agent  (qwen3.5:9b-64k — orchestrator + agent scaffolding tools)
                │     ├─► web_researcher  (qwen3.5:9b-64k — web search + page reading)
                │     ├─► coder  (qwen3.6:35b — sandboxed Python execution)
                │     ├─► ops  (qwen3.5:9b-64k — wiki/inventory/projects/automation/helpdesk)
                │     ├─► writer  (qwen3.5:9b-64k — docs/summaries/copy → Outline)
                │     ├─► studio  (qwen3.5:9b-64k — images/diagrams/TTS audio/3D models)
                │     ├─► auditor  (reviewer pool — multi-model second opinions)
                │     ├─► maintainer  (qwen3.5:9b-64k — self-improvement: job/audit review → Outline + Plane)
                │     └─► agents/custom/*  (auto-discovered custom agents)
                ├─► host.docker.internal:11434/v1  → Ollama OpenAI-compatible API
                ├─► host.docker.internal:8099/mcp/<domain>/  → mcp-tools (tool server)
                │         │
                │         └─► propose_code_change (manager only) ──► redeploy:8101
                │                   writes /repo/<any file>, restarts the container,
                │                   auto-reverts on a failed health check
                └─► ./data/smolagents  → /data  (agent outputs, uploads, jobs/ queue
                                          — jobs/ is bind-mounted into mcp-tools)
```

---

## Cheat Sheet

### Logs

```bash
docker compose -p smolagents logs -f
```

### Change models

Edit `SMOLAGENTS_CODING_MODEL_ID` / `SMOLAGENTS_GENERAL_MODEL_ID` in `.env` (pull the new model in Ollama first), then:

```bash
./stop.sh && ./start.sh
```

### Run an agent one-off from the host

```bash
OLLAMA_API_BASE=http://localhost:11434/v1 uv run python -c \
  "from agents import build_manager_agent; print(build_manager_agent().run('your task here'))"
```

### Enable telemetry

Point `OTEL_EXPORTER_OTLP_ENDPOINT` in `.env` at an OTLP HTTP collector (e.g. a local [Arize Phoenix](https://github.com/Arize-ai/phoenix) instance) and restart — agent runs will be traced automatically.
