# smolagents — AI Agent Workspace

smolagents is Hugging Face's minimal agent framework. This service is both a **Python workspace** for authoring your own agents and a **Docker service** that runs them behind a Gradio chat UI — all backed by the local Ollama server, so nothing leaves the host.

It ships with ten starter agents (models follow the lead-per-domain hierarchy in [README.md](../README.md); the general lead is the `qwen3.6:35b-64k` derivative — stop `trellis` before agent runs, its resident host RAM starves 35b loads, see the hardware envelope in [CLAUDE.md](../CLAUDE.md)):

| Agent | Model | Role |
| --- | --- | --- |
| `manager` | `qwen3.6:35b-64k` | Orchestrator served by the UI and the job worker — validates briefs, plans, delegates, audits by risk, reports (see "Orchestration") |
| `web_researcher` | `qwen3.6:35b-64k` | Web search + page reading (mcp-tools web domain, SearXNG-backed) — quick one-off sourced lookups |
| `researcher` | `qwen3.6:35b-64k` | Structured research briefs — numbered findings each attributed to a source URL, plus a confidence-and-gaps note. Delegated to by the manager and by debate turns; the Researcher Open WebUI preset is the direct-chat equivalent |
| `coder` | `qwen3.6:35b` | Writes and executes Python for data work and programming tasks |
| `ops` | `qwen3.6:35b-64k` | Operates the business stack via mcp-tools (wiki, inventory, projects, automation, helpdesk) |
| `writer` | `qwen3.6:35b-64k` | Written deliverables: docs, reports, summaries, marketing copy; publishes durable docs to Outline |
| `studio` | `qwen3.6:35b-64k` | Media assets: images (ComfyUI/FLUX), diagrams (draw.io), speech audio (Kokoro TTS), image→3D models (TRELLIS). No video |
| `auditor` | reviewer pool | Independent multi-model review of finished work (see below) |
| `maintainer` | `qwen3.6:35b-64k` | Self-improvement loop: reviews job/audit history, researches fixes, files Outline reports + Plane issues (see "Self-improvement loop") |
| `investment_strategist` | `qwen3.6:35b-64k` | Sourced, risk-weighted investment assessments (thesis, risks, base rates, falsifiers, verdict); carries `researcher` as its own sub-agent and keeps warm memos in the registered `investments` project. The Investment Strategist Open WebUI preset is the direct-chat equivalent |
| `career_coach` | `qwen3.6:35b-64k` | Multi-session career-profile building (history, identity/boundaries, T-shaped positioning lanes) plus ATS-optimized, tailored resume/cover-letter drafting per target role, backed by live company/posting/salary research; also writes internal-use application strategy notes. Keeps everything in the registered `career-profile` project. The Career Coach Open WebUI preset is the direct-chat equivalent |

A second, separate team lives in `agents/devteam/`: a **lead architect**
(manager-shaped orchestrator, general lead) managing `product_analyst`, five
role-briefed engineers (`backend_engineer`, `frontend_engineer`,
`data_engineer`, `devops_engineer`, `qa_engineer` — all on the coding lead),
`security_reviewer`, `tech_writer`, plus fresh instances of `auditor` and
`researcher`. It is never registered on the general manager; the job worker
runs it for **devteam engagement** phases — building an entire application
in a registered project workspace from a product plan, with user sign-off
gates and mid-run questions (the engagement parks `awaiting_input` and
resumes with the user's answers). See the root [README.md](../README.md)
"Devteam engagements" for the concept and the mcp-tools `devteam` domain
for the controls; models/step budgets are env-tunable
(`SMOLAGENTS_DEVTEAM_*`, see `.env.example`).

A third, separate team lives in `agents/hardware/`: an **embedded
architect** (manager-shaped orchestrator, general lead) managing
`kicad_specialist` (coding-adjacent lead, pinned to `qwen3.6:27b`),
plus fresh instances of `auditor` and `researcher`. Same shape as devteam —
never registered on the general manager, run by the job worker for
**hardware engagement** phases (requirements → architecture → per-block
milestones → fab-review → docs) — but a forked, parallel implementation
rather than a shared one (see `agents/jobs.py`'s hardware section for why).
An engagement designs a circuit in a registered project workspace from a
desired hardware outcome, with the same sign-off gates and mid-run
question mechanics as devteam, plus one gate devteam has no analog for:
`fab-review`, gated in every preset except `none` since it precedes the
real, costly step of sending a design to a manufacturer. **No real KiCad
tooling exists yet** — every phase's deliverables are documents (an
Embedded Design Brief, then per-block KiCad Build Plans), never real
schematic/PCB files; see the mcp-tools `hardware` domain for the controls
and `docs/hardware-agents-guide.md` for the full roadmap. Models/step
budgets are env-tunable (`SMOLAGENTS_HARDWARE_*`, see `.env.example`).

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
docker exec ollama ollama pull qwen3.6:35b       # coding + general lead base (~23 GB, MoE 3B active)
# 64K-context variant the agents use as the general lead (Ollama's default
# context is too small):
printf 'FROM qwen3.6:35b\nPARAMETER num_ctx 64000\n' | docker exec -i ollama sh -c 'cat > /tmp/Modelfile && ollama create qwen3.6:35b-64k -f /tmp/Modelfile'
docker exec ollama ollama pull qwen3.5:9b        # vision lead / light presets (~6.6 GB)
# Hardware specialist + coding reviewer (dense) and cross-lineage reviewer:
docker exec ollama ollama pull qwen3.6:27b       # ~17 GB
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
`get_domains_tools` also appends the local `current_datetime` tool, so
every ToolCallingAgent has clock access — models confabulate dates
otherwise (observed live: memos date-stamped a day off). The matching
Open WebUI mechanism is the `{{CURRENT_DATETIME}}` template variable in
every preset's baseline block.

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
- **embedded_architect** (in `agents/hardware/`) uses `project`, `inventree`
  (read-only stock-check tools only), and `web` — checking local parts
  stock before speccing new components and doing quick research directly,
  while deeper datasheet/part comparisons still go to its own `researcher`
  sub-agent. **kicad_specialist** uses only the `project` domain this
  phase — no `kicad` mcp-tools domain exists yet (a future build phase); it
  reads the architect's design briefs and writes its own KiCad build plans.

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
web access itself.

`maintainer` never chains its own delegation — dispatch internal review and
the external trends sweep as **two separate `agent_dispatch` briefs** (a
first live end-to-end test found that relying on `maintainer`'s prose to
get the manager to make a follow-up call to `web_researcher` was
unreliable: the manager would sometimes skip the delegation and report
"completed" with a fabricated excuse anyway). The external sweep is instead
a **fixed three-call sequence the manager itself executes** (`manager.py`
step 10b), so the loop isn't limited to problems already visible in this
stack's own history without depending on the small model noticing it
should delegate further:

1. Manager calls `maintainer` scoped to read-only: find or bootstrap two
   append-only Outline docs in the **AI** collection — the **Research
   Ledger** (one entry per evaluated external finding: topic, source URL,
   decision of integrated/rejected/deferred, rationale) and the
   **Research Query Log** (fact-only: timestamp, service, query, result
   count, no decision) — and report back their contents. No evaluation or
   writes happen in this call.
2. Manager calls `web_researcher` directly (not through `maintainer`),
   pasting in what was just read back, to sweep arxiv/github/scholar/
   stackoverflow/general web and `x_search_recent` (X/Twitter, only if
   `X_API_BEARER_TOKEN` is configured — this call **costs real money per
   read**, no free tier) for smolagents/MCP/agent-orchestration/
   prompt-engineering developments, skipping or varying anything that
   matches a query already run against the same service within its
   recency window (7 days for X).
3. Manager calls `maintainer` again, pasting in `web_researcher`'s
   findings, scoped to evaluate: dedupe by exact source URL against the
   Research Ledger; for genuinely new findings, judge fit for this
   specific stack (strongest when tied to an observed internal pattern,
   but a purely prospective "this is a widely-recommended technique we
   don't use yet" finding is fine too, labeled as such); log every
   evaluated candidate — accepted, rejected, or deferred — to the Ledger
   (what lets the next run's dedup pass actually skip what's already been
   considered); log every search to the Query Log; file one Plane issue
   per accepted candidate exactly like an internal-pattern finding.

Everything downstream of an accepted candidate (coder drafts, gated
`propose_code_change`, auto-redeploy) is identical to an internal-pattern
finding either way.

**X cost per loop iteration**: confirmed live (2026-07-09) at the
$0.005/read tier — a 10-result call billed $0.05. `x_search_recent`
defaults to and caps at 100 results/call regardless of the endpoint's own
default of 10 (cost is per-read either way, so always ask for the max),
putting one call at **$0.50-$1.00** (X bills some read types at $0.01).
The sweep brief covers up to four topic areas, so a cold Research Query
Log (first run, or a long gap since the last one) could see all four go
out fresh — **worst case ~$4.00/iteration**. Once the log is populated,
steady-state weekly runs typically see one or zero fresh X calls (the rest
skipped as already-asked-within-7-days), i.e. **~$0.50 or less/iteration**
in practice. No cross-run dollar budget tracker exists in this version —
the Query Log's own line count (per `x_search_recent` entry) is the
running proxy for spend; see
[docs/ai-setup-checklist.md](../docs/ai-setup-checklist.md) "§5e" for the
full cost breakdown.

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
                ├─► manager agent  (qwen3.6:35b-64k — orchestrator + agent scaffolding tools)
                │     ├─► web_researcher  (qwen3.6:35b-64k — web search + page reading)
                │     ├─► researcher  (qwen3.6:35b-64k — structured, sourced research briefs)
                │     ├─► coder  (qwen3.6:35b — sandboxed Python execution)
                │     ├─► ops  (qwen3.6:35b-64k — wiki/inventory/projects/automation/helpdesk)
                │     ├─► writer  (qwen3.6:35b-64k — docs/summaries/copy → Outline)
                │     ├─► studio  (qwen3.6:35b-64k — images/diagrams/TTS audio/3D models)
                │     ├─► auditor  (reviewer pool — multi-model second opinions)
                │     ├─► maintainer  (qwen3.6:35b-64k — self-improvement: job/audit review → Outline + Plane)
                │     ├─► investment_strategist  (qwen3.6:35b-64k — sourced investment assessments; owns a researcher sub-agent)
                │     ├─► career_coach  (qwen3.6:35b-64k — multi-session career profile + tailored resume/cover-letter drafting)
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
