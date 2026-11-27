# MakerOps AI

[![CI](https://github.com/makerops-labs/makerops-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/makerops-labs/makerops-ai/actions/workflows/ci.yml)

**Local AI agents that run a small manufacturer's back office, with a human
approving every action that matters.** They run entirely on local models: no
API keys, no per-token costs, and no data leaving the machine.

> **Demo video:** coming soon, a 2–3 minute walkthrough of the scenario below
> ([shot list](demo/VIDEO_SCRIPT.md)).

## The scenario

A customer emails asking for 20 EN-100 enclosures. Asked to handle it, the
ops agent:

1. reads the request in the help desk (FreeScout) and the bill of materials
   in inventory (InvenTree);
2. works out what's short (only 8 lids in stock) and who supplies it;
3. raises a draft purchase order for the shortfall; *placing* it comes back
   `PENDING APPROVAL`;
4. drafts a reply that promises only what stock allows; *sending* it is
   held for approval too;
5. a human approves or rejects each held action at `/approvals`.

The demo data is seeded and reset by [demo/](demo/); the same scenario
drives the evaluation below.

## Architecture

![Architecture: Open WebUI and smolagents call the mcp-tools server, which gates writes through human approvals before they reach InvenTree, FreeScout and the rest of the makerops-core stack; all models are served locally by Ollama](assets/architecture.svg)

## What this demonstrates

- **Approval-gated tool use with per-tool policy.** Every write tool has a
  tier: additive writes run and notify; destructive or customer-facing
  ones return `PENDING APPROVAL #id` and wait for a human
  ([mcp-tools/tools/policy.py](mcp-tools/tools/policy.py), unit-tested).
- **Progressive tool disclosure.** Agents get a short manifest and look up
  domains and tools on demand, instead of carrying the whole catalog in context
  ([Tool discovery](#tool-discovery-progressive-disclosure)).
- **Multi-agent delegation.** A manager agent delegates to researcher, coder,
  ops and auditor agents, plus long-running engagement queues with their own
  review gates ([smolagents/README.md](smolagents/README.md)).
- **Cross-lineage review.** Reviewers are deliberately different model
  families (gpt-oss alongside Qwen), so they don't share the lead model's
  blind spots ([docs/model-stack.md](docs/model-stack.md)).
- **Sandboxed execution.** Agent commands run in throwaway, resource-capped
  containers with one project directory mounted and no Docker socket
  ([sandbox/](sandbox/)).
- **Self-improvement with rollback.** Agents propose code changes as diffs; a
  human approves each one; the change is deployed, health-checked and
  automatically reverted if it fails
  ([Self-improvement loop](#self-improvement-loop)).
- **Fully local inference.** Every model runs on Ollama on one 16 GB GPU;
  the larger ones spill partly into system RAM.

## Evaluation

29 human-reviewed tasks from the scenario above, run on four local models;
each task runs on a freshly seeded demo, using the real tools and approval gate.

| Model | Pass | Median latency |
| --- | ---: | ---: |
| `qwen3.8:27b-64k` | 26/29 | 88 s |
| `qwen3.6:35b-64k` | 24/29 | 28 s |
| `qwen3.5:9b-64k` | 22/29 | 15 s |
| `gpt-oss:20b-32k` | 19/29 | 21 s |

- The first run passed 12–16 of 29. Reading its failures call by call
  turned up four tool-layer bugs (#12, #13, #16, #17); fixing them produced
  the numbers above, with the same models and tasks.
- Asked to do something risky (tell a customer "all 20 ship today" with 8 in
  stock, zero the whole inventory), models often act instead of asking. The
  approval gate held every one of those actions.
- A live-state check caught a model reporting a draft it never created.

Full findings, per-task results and method: [evals/RESULTS.md](evals/RESULTS.md).

## How this was built

The maintainer did the architecture, decisions and review. Implementation
was AI-assisted with [Claude Code](https://claude.com/claude-code), working
under repository conventions ([CLAUDE.md](CLAUDE.md)), CI (policy tests,
lint, eval dry run) and a human-reviewed pull request for every change. The
evaluation was used the same way: its failures were traced to root causes,
and those causes were fixed in separate, tested PRs.

## Quick start

1. Bring up [makerops-core](https://github.com/makerops-labs/makerops-core)
   (Ollama plus InvenTree and FreeScout for the scenario).
2. Work through [docs/ai-setup-checklist.md](docs/ai-setup-checklist.md);
   each phase is useful on its own.
3. Seed the scenario with `python3 demo/seed.py` ([demo/README.md](demo/README.md)),
   then run the eval with [evals/README.md](evals/README.md).

---

## Services

| Service | Port | Purpose |
| ------- | ---- | ------- |
| [Open WebUI](https://openwebui.com) | [8080](http://localhost:8080) | Chat UI — conversation history, RAG, multi-model support, voice |
| [smolagents](https://github.com/huggingface/smolagents) | [8090](http://localhost:8090) | Agent workspace — planning, research, coding, ops, and audit agents with a Gradio UI |
| [SearXNG](https://github.com/searxng/searxng) | [8098](http://localhost:8098) | Private metasearch — web-search backend for Open WebUI and mcp-tools |
| MCP Tools | [8099](http://localhost:8099/healthz) | Shared MCP tool server — read/write tools for the business stack with human write-approvals |
| [n8n-mcp](n8n-mcp/) | [8104](http://localhost:8104/health) | MCP server for agentic n8n workflow management (czlonkowski/n8n-mcp) — wraps the makerops-core n8n public API with node schemas, templates, and validation. Feeds the "n8n Architect" preset (direct) and the `n8n_builder` persona (via an mcp-tools `n8nmcp` proxy domain). Destructive tools disabled in-process; no approval gate on this path |
| [Speech](speech/) | [8091](http://localhost:8091) STT / [8093](http://localhost:8093) TTS | speaches (faster-whisper) speech-to-text + Kokoro text-to-speech, CPU-only |
| [TRELLIS](trellis/) | [8094](http://localhost:8094/healthz) | Image-to-3D generation (GLB) — GPU-heavy, start-on-demand only |
| [redeploy](redeploy/) | [8101](http://localhost:8101/healthz) | Docker-socket-scoped restart proxy — deploys approved self-improvement code changes |
| [sandbox](sandbox/) | [8102](http://localhost:8102/healthz) | Docker-socket-scoped command runner — sandboxed shell execution (tests/lint/build/git) confined to one project directory, no host/Docker access from inside |

There is also one host-level (non-Docker) component:
[Hermes Agent](https://hermes-agent.nousresearch.com), a terminal agent with
persistent per-project memory that runs against Ollama — see
[docs/hermes-setup.md](docs/hermes-setup.md).

### Using the stack day to day

- **Chat** at <http://localhost:8080> (or `openwebui.localhost`): pick a
  workspace-model preset (Research Assistant, Ops Assistant, Coding
  Assistant, …) rather than a bare model — presets carry the right system
  prompt, tool scope, and baseline context. Attach an image to any
  qwen3.5/qwen3.6 chat for vision; use the mic/speaker buttons once speech
  is wired.
- **Agents** at <http://localhost:8090> (or `agents.localhost`): give the
  manager a task; it delegates to web_researcher / coder / ops / auditor.
  Ask for a "review" or "second opinion" to trigger the multi-model audit.
- **Second opinions**: paste task + artifact into the Code Auditor or
  General Auditor preset (manual), or let the smolagents auditor consult the
  reviewer pool (automated). Reviewers are deliberately weaker,
  different-lineage models — weigh their findings, don't auto-apply.
- **Write actions** (wiki edits, stock adjustments, …) may answer
  `PENDING APPROVAL #id`: review and approve at
  <http://mcp.localhost/approvals>. Additive writes notify; destructive ones
  gate — tune per tool in `mcp-tools/.env`.

### Tool discovery (progressive disclosure)

mcp-tools publishes a documentation tree so agents (and humans) can discover
tools without carrying the whole catalog in context:

| Level | HTTP | From any agent |
| --- | --- | --- |
| Domain manifest | `GET :8099/context` | `tools_help('')` |
| One domain's tools | `GET :8099/context/<domain>` | `tools_help('<domain>')` |
| Full usage for one tool | `GET :8099/context/<domain>/<tool>` | `tools_help('<domain>/<tool>')` |
| Best-practice guidance | `GET :8099/context/guidance[/<doc>]` | `tools_help('guidance[/<doc>]')` |

The `guidance` branch serves [docs/guidance/](docs/guidance/) — distilled
operating best practices (planning discipline, external verification,
tooling for small models) that agents pull on demand; also mirrored to the
Outline "Guidance" collection for RAG.

Every agent gets the root manifest as baseline context automatically:
smolagents injects it into all agents' instructions (`agents/context.py`),
Open WebUI presets start with [contexts/_baseline.md](openwebui/contexts/_baseline.md),
and Hermes profiles learn it once into persistent memory.

### Self-improvement loop

The stack can research, evaluate, and propose improvements to *itself* —
the goal being that you provide direction and approvals, not legwork. The
**maintainer** agent (part of the smolagents roster, see
[smolagents/README.md](smolagents/README.md)) reviews recent job and audit
history for concrete, evidenced failure patterns, *and* sweeps external
sources (arxiv/github/scholar/stackoverflow/general web, plus X/Twitter if
`X_API_BEARER_TOKEN` is configured) for new AI-tooling techniques worth
adopting — tracked in two self-bootstrapping Outline docs (a Research
Ledger of findings/decisions, a Research Query Log of what's already been
searched) so repeat sweeps only look at what's new. It researches fixes
(delegating to web_researcher via the manager), writes an evaluation report
to Outline's **AI** collection, and files one issue per proposed
improvement in the **Stack Improvements** Plane project. For well-scoped
proposals the manager has `coder` draft the actual file content and then
proposes it itself with `propose_code_change`.

**Every actual code change is a human-reviewed diff, no exceptions.**
`propose_code_change` has no file-path restriction — gating on your
approval at [mcp.localhost/approvals](http://mcp.localhost/approvals) is
the safety boundary, not an allowlist. Nothing is written until you
approve. On approval, the affected container (`smolagents` or `mcp-tools`
— the only two with live-editable bind-mounted code) restarts
automatically via the [redeploy](redeploy/) service; if it fails its
health check, the change is **automatically reverted** and the container
restarted again onto the known-good version — you find out what happened
(healthy or reverted) through the same `/approvals` page and notification
webhook you already use for everything else, not a new place to check.

**Your responsibility**: pending code-change approvals expire after
`APPROVAL_TTL_HOURS` (24h default) exactly like any other gated action —
review them or they're simply lost, not queued forever. And a clean
restart only proves the new code *runs*; it doesn't prove it's *correct*
— that judgment call is why review exists. See
[docs/ai-setup-checklist.md](docs/ai-setup-checklist.md) "Self-improvement
loop" for the one-time setup and a full walkthrough of the expected
process, and [docs/operations-notes.md](docs/operations-notes.md) for failure modes to watch
for.

Trigger a review on demand by asking any dispatch-capable chat (e.g. Task
Dispatcher) to "review the stack's recent performance and propose
improvements" — this always includes the external trends sweep, not just
internal history — or set up the optional weekly n8n cron workflow
described in the checklist.

### Project workspaces

Beyond improving itself, the stack can research a problem, propose a
solution, and — once you've reviewed the proposal and created a directory
for it — implement the code and docs there. This is the `project` MCP
domain (see [mcp-tools/README.md](mcp-tools/README.md) "Project
workspaces"): durable directories that are **siblings of `makerops/`**
under `~/workspace/` (e.g. `~/workspace/my-app`), never nested inside
`makerops-ai` or `makerops-core`.

- **You create the directory by hand** — that's the authorization to write
  there; the agents never create it for you. Register it with
  `project_register`, then dispatch work with `agent_dispatch(...,
  project="my-app")`.
- **Reads span all of `~/workspace`** (sibling projects, even this stack's
  own source) so agents can use existing work as prior art; **writes stay
  confined** to the one project you registered for that job.
- **Notify tier by default** — writes execute immediately, since creating
  the directory was already your approval; audit-logged and
  webhook-notified like everything else, not gated per file.
- Every registered project gets a `PROJECT_CONTEXT.md` seeded at its root —
  current state, architecture, and pointers to detail docs — so a
  stateless agent picking the project back up later (a different job, a
  different day) isn't starting from nothing.

#### Sandboxed command execution

File I/O alone can't verify anything — an agent can write a test and claim
it passes without running it. `project_run_command` (also in the `project`
domain) runs a bounded shell command (test runner, linter, build, `git`,
package install) inside an isolated, resource-capped, ephemeral container
with exactly one registered project directory mounted — nothing else, and
no Docker access from inside it. See [sandbox/README.md](sandbox/README.md)
for the full containment model (resource limits, non-root user, network
policy). Like file writes, this executes immediately (notify tier) — the
sandbox itself is the safety boundary, not a human-approval step, since
that would break the "run it, read the output, iterate" loop this exists
for. `coder` and `manager` both use it; before reporting a project job
done, the manager has `coder` actually run the test suite rather than
assume the code works.

### Devteam engagements (build an app from a product plan)

The dev-shop tier on top of project workspaces: a **lead architect** agent
orchestrating a specialist software team (product analyst, five role-briefed
engineers, security reviewer, tech writer, plus the shared auditor and
researcher — `smolagents/agents/devteam/`) builds an entire application in
a registered project directory from a product plan you provide, phase by
phase: requirements → architecture → scaffold → implementation milestones
(planned by the architecture phase itself) → qa → docs. Each phase runs as
one background job through the same segment/synopsis machinery as any long
manager job; the engagement's durable state machine lives in
`smolagents/data/smolagents/devteam/<id>/session.json` (a fourth parallel
queue beside jobs/debates/liaison, same mcp-tools bind-mount ownership
split).

Two things distinguish it from `agent_dispatch`:

- **It can ask you questions mid-run.** When the architect hits a real
  product decision, the engagement parks as `awaiting_input` (webhook
  `devteam.needs_input` carries the questions), and resumes — same phase,
  same working memory — when you answer via `devteam_answer`. No more
  "the team cannot ask questions mid-run".
- **You sign off like a client, not a babysitter.** Phases listed in the
  engagement's `gates` (default `key`: requirements, architecture, final
  docs delivery) park as `awaiting_review` until you `devteam_approve` or
  `devteam_revise` (rework with your feedback injected verbatim);
  everything between gates auto-advances — the worker queues the next
  phase itself, debate-style, notifying you informationally at each
  milestone. `gates="all"` or `"none"` change the contract per
  engagement. Within a phase nothing is people-gated at all: project
  writes and sandboxed runs are notify-tier, so the team iterates freely.

Start one from the **App Builder** chat preset
([openwebui/contexts/app-builder.md](openwebui/contexts/app-builder.md)) —
it interviews you into a concrete plan, registers the project, calls
`devteam_start`, relays questions, and records your verdicts. Track with
`devteam_status` / `devteam_result` or the inbox's engagement cards; a
crashed or failed phase parks as `stuck` (webhook `devteam.stuck`) and
recovers with `devteam_resume`, or `devteam_cancel` ends the engagement
(project files always remain). An architecture phase that fails to produce
a machine-parseable milestone plan is parked `stuck` too — the plan is
validated by deterministic worker code, never guessed.

## Experimental

These components work but are less mature and less tested than the core
above. They're kept here for completeness: the career and investment agents
([smolagents/README.md](smolagents/README.md)), the Alexa voice bridge
([docs/alexa-voice-setup.md](docs/alexa-voice-setup.md)), TRELLIS image-to-3D
([trellis/](trellis/)), the debate system and hardware engagements below.

### Debate system

A fixed team of three personas — **entrepreneur** (proposes and defends the
strongest concrete version of an idea), **critic** (independent devil's
advocate), and **monitor** (neutral facilitator; decides
continue/redirect/conclude) — argues a goal over several rounds. Because all
of them share one GPU, they run one at a time in series, correspondence-chess
style: each turn is a background job that writes its argument to a file and
automatically queues the next persona's turn once it finishes — no polling
loop or scheduler to babysit, it reuses the same file-based job-queue
mechanism as `agent_dispatch` (see `smolagents/agents/jobs.py`).

Each round is kept small (a one-line abstract plus a focused argument,
hard-capped in size), but the debate as a whole stays navigable via a
**manifest**: a sequenced, append-only index (round number, persona, word
count, one-line description, file path) that a turn's own prompt renders
compactly — recent rounds in full, older ones as a description a persona can
choose to read in full or skip, so context stays flat no matter how long the
debate runs. Round files are prose by contract, doubly enforced: each
persona carries an output contract plus a format check that rejects
code/JSON answers with corrective feedback (`agents/debate/format.py`), and
the worker deterministically unwraps anything that still arrives
code-fenced before it becomes the next turn's input.

**Every debate ends with a human-facing synthesis, automatically.** When
the monitor concludes (or the round cap is hit), one closing monitor turn
writes the final report — what was decided or learned, the strongest
surviving objections, concrete next steps, open questions — to the
session's `summary.md`, served by `debate_result`. That report is the
deliverable; the round files are the working record behind it. A turn runs
its persona **directly** — the worker assembles the persona's task,
enforces the prose contract, and regex-parses the monitor's verdict, all in
deterministic code; there is deliberately no orchestrator LLM between the
worker and a persona (an earlier relay design failed constantly by
re-typing arguments into giant string literals). Personas carry their own
web tools for grounding claims; deeper sourced research is available via
the dedicated **researcher** agent through the general manager or the
Researcher preset.

Start one from the **Debate Moderator** chat preset (it refines an ambiguous
ask into a concrete goal/mode/deliverables brief with you first, the same way
Task Dispatcher refines a brief before `agent_dispatch`), or call
`debate_start` directly if you already have one. `mode="narrow"` keeps a
tight, well-scoped question concrete (6 rounds by default); `mode="broad"`
lets the personas research and range wider over an open-ended one (16 rounds
by default). Track a running debate with `debate_status` / `debate_manifest`
/ `debate_read_round`, and read the final synthesis with `debate_result`; a
turn that crashes or ends `needs_attention`/`failed`
halts auto-advancement (status `stuck`, with a `stop_reason`) rather than
silently stalling or queuing garbage into the next turn — recover it with
`debate_resume` or give up with `debate_cancel`.

### Hardware engagements (design a circuit from a desired outcome)

The same engagement mechanism as devteam above, applied to circuit design:
an **embedded architect** agent orchestrating a **KiCad build-plan
specialist** (`smolagents/agents/hardware/`) designs a circuit in a
registered project directory from a desired hardware outcome you provide,
phase by phase: requirements → architecture (with a per-block milestone
plan, one block per functional area — power, MCU, sensing, radio, etc.) →
per-block implementation milestones → fab-review → docs. Each phase runs
as one background job through the same segment/synopsis machinery as any
long manager job; the engagement's durable state machine lives in
`smolagents/data/smolagents/hardware/<id>/session.json` (a fifth parallel
queue beside jobs/debates/liaison/devteam, same mcp-tools bind-mount
ownership split). This is a deliberately forked, parallel implementation
of the devteam mechanism, not a shared one — see
`smolagents/agents/jobs.py`'s hardware section for why forking (rather
than generalizing devteam itself) was the right call for this pass.

**No real KiCad tooling exists yet.** Every phase's deliverables are
documents, not real schematic/PCB files: the architecture phase produces
an Embedded Design Brief (architecture overview, power budget with the
arithmetic shown, a candidate BOM stock-checked against the `inventree`
domain, interface/pinout intent), and each milestone phase produces the
matching slice of a KiCad Build Plan (sheet plan, net list, footprint
assignments, DRC/ERC expectations) whose "Planned Manufacturing Outputs"
section is explicitly marked intent-only. See
[docs/hardware-agents-guide.md](docs/hardware-agents-guide.md) for the
full roadmap toward real `kicad-cli` execution, code-first generation
tooling, and a KiCad-desktop IPC-API integration.

It shares devteam's two distinguishing mechanics — the engagement can ask
you questions mid-run (`awaiting_input`, webhook `hardware.needs_input`,
resume via `hardware_answer`), and you sign off like a client at gated
phases (`awaiting_review`, `hardware_approve`/`hardware_revise`) while
everything between gates auto-advances — plus one hardware-specific
addition: **`fab-review` is gated in every preset except `none`**,
regardless of how much autonomy you chose elsewhere, because it precedes
the real, hard-to-reverse cost of sending a design to a manufacturer.
Physical prototype test results feed back into the design the same way —
`hardware_revise` on the fab-review phase with what you found.

Start one from the **Hardware Builder** chat preset
([openwebui/contexts/hardware-builder.md](openwebui/contexts/hardware-builder.md))
— it interviews you into a concrete desired outcome, registers the
project, calls `hardware_start`, relays questions, and records your
verdicts. Track with `hardware_status` / `hardware_result` or the inbox's
engagement cards; a crashed or failed phase parks as `stuck` (webhook
`hardware.stuck`) and recovers with `hardware_resume`, or `hardware_cancel`
ends the engagement (project files always remain). An architecture phase
that fails to produce a machine-parseable milestone plan is parked `stuck`
too, same as devteam. For quick ad hoc questions outside a formal
engagement, the lightweight **KiCad Specialist** preset talks directly to
the specialist's persona with no engagement machinery attached.

## Setup in detail

This repo is the agentic layer. [makerops-core](https://github.com/makerops-labs/makerops-core)
holds the business services and the foundational GPU services (Ollama,
ComfyUI). The two are kept as separate repositories on purpose.

### Prerequisites (from makerops-core)

These services depend on the sibling checkout of `makerops-core`:

- **Ollama** (`makerops-core/ai/ollama`, port 11434) — serves every LLM here.
  Model pulls are listed in [docs/ai-setup-checklist.md](docs/ai-setup-checklist.md).
- **ComfyUI** (`makerops-core/ai/comfyui`, port 8188) — image generation,
  driven via mcp-tools.
- **name-proxy** (`makerops-core/infrastructure/name-proxy`) — optional
  `*.localhost` names for the services here; enable with the drop-in in
  [proxy/](proxy/) (install/uninstall = copy/delete one file).
- NVIDIA Container Toolkit for the GPU services (documented in
  makerops-core's `ai/README.md`).

### Setup

The complete, ordered walkthrough is
**[docs/ai-setup-checklist.md](docs/ai-setup-checklist.md)** — work it top to
bottom; each phase is independently useful. In outline:

1. Start Ollama (in makerops-core) and pull the models from the hierarchy
   table ([docs/model-stack.md](docs/model-stack.md)), including the `qwen3.5:9b-64k` derivative (checklist §1).
2. Start SearXNG, then mcp-tools (note the approvals URL+token it prints),
   then Open WebUI / smolagents / speech. Each `start.sh` creates `.env`
   from `.env.example` on first run.
3. Add service API tokens to `mcp-tools/.env` one at a time (checklist §2) —
   domains without a token simply stay unmounted.
4. Do the UI-side wiring in Open WebUI (checklist §3–4): web search, tool
   connections, RAG embedding model, audio, and the workspace-model presets
   from [openwebui/contexts/](openwebui/contexts/) (git is the source of
   truth; the UI stores them in its DB).
5. Optional: name-proxy drop-ins ([proxy/README.md](proxy/README.md)) and
   Hermes ([docs/hermes-setup.md](docs/hermes-setup.md)).

### Startup order

Ollama first (in makerops-core, with the models from the [hierarchy table](docs/model-stack.md#model-hierarchy)
pulled), then SearXNG, then mcp-tools, then Open WebUI, smolagents, and/or
speech. SearXNG, mcp-tools, and speech have no GPU dependency and are safe to
leave running continuously. TRELLIS is the opposite: a generation needs most
of the 16 GB card, so start it only for 3D work and stop it after
(`trellis/start.sh` / `stop.sh`). The full tool-access setup (API tokens, Open
WebUI connections, context presets, approval tuning) is walked through in
[docs/ai-setup-checklist.md](docs/ai-setup-checklist.md).

Each service directory is a self-contained Docker Compose project with its
own `start.sh` / `stop.sh` / `teardown.sh` and `.env.example`, following the
makerops-core conventions (including the WSL2 DNS workaround: explicit
`dns:` servers at runtime, `network: host` for image builds).

### Local integration with makerops-core

The two repos stay under one parent directory with strictly separate
version control; every cross-reference from the public repo is local-only:

- **Symlink**: `makerops-core/ai/private` → `../../makerops-ai`, excluded
  via `makerops-core/.git/info/exclude` (git's per-clone exclude file — it
  is never tracked, so the public repo carries no trace; do not use
  `.gitignore` for this, it is public). Navigation convenience only:
  **always run services from the real path** (`makerops-ai/<service>/start.sh`)
  so compose project directories stay canonical.
- **Proxy routes**: install the drop-in per [proxy/README.md](proxy/README.md).
- **One-window workflow**: open `makerops.code-workspace` in the parent
  directory (both repos as workspace folders; the symlink is excluded from
  search/watchers to avoid duplicates). A parent-level `CLAUDE.md` gives
  AI-assistant sessions the two-repo layout and the never-commit-to-core
  rule.

## More documentation

- [docs/model-stack.md](docs/model-stack.md): the model hierarchy (which model
  leads which domain, and its reviewers) and the dated evaluation notes behind it.
- [docs/operations-notes.md](docs/operations-notes.md): tips, gotchas and
  debugging.
- [docs/ai-setup-checklist.md](docs/ai-setup-checklist.md): the full setup
  walkthrough.


## License

MakerOps AI is **source-available**, not open source. You may use it under either the [PolyForm Noncommercial License 1.0.0](LICENSE) or the [PolyForm Internal Use License 1.0.0](LICENSE), at your choice.

**Permitted:** Personal, hobby, research and educational use; use by charitable, educational, public-research, public-safety or public-health, environmental-protection and government organizations; and use for your own company's internal business operations, including changes for that use.
**Not permitted under these licenses:** Selling the software, building it into products or services sold to others, running it as a paid hosted service, or distributing it as part of a commercial offering. For those uses, contact the copyright holder through the makerops-labs GitHub organization to discuss a separate license.

Third-party software integrated by this stack (Open WebUI, smolagents, SearXNG, FastMCP, speaches, Kokoro-FastAPI, Hermes Agent, TRELLIS) is governed by its own license. See [NOTICE](NOTICE) for the full list of upstream projects and their licenses.

## System Requirements

Same GPU/RAM guidance as makerops-core's `ai/README.md`: requirements scale
with the models pulled in Ollama. Models larger than VRAM (the ~19–23 GB MoE
coding leads on a 16 GB GPU) partially offload to system RAM — on WSL2, raise
the memory cap in `.wslconfig` if a large model stalls or is OOM-killed
(24 GB works for the current hierarchy on a 16 GB GPU). The speech services
are CPU-only by design.
