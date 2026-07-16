# LLM Context Presets

Predefined contexts for interacting with the local models. Each file in this
directory defines one context: what it is for, which base model to use, which
mcp-tools domains it gets, and a ready-to-paste system prompt. Open WebUI
stores workspace models in its database, so these files are the git-tracked
source of truth — recreate from here after a reset, and back-port any prompt
tuning you do in the UI.

## Creating a context model (once per preset)

1. Make sure the tool server connection(s) the preset needs exist:
   **Admin Settings → External Tools → Add Connection** → type **MCP
   (Streamable HTTP)** → URL `http://host.docker.internal:8099/mcp/<domain>/`
   (one connection per domain the preset lists — per-domain scoping keeps
   tool lists short, which local models need).
   **Set the API key field to any non-empty value, e.g. `no-key`.** Open
   WebUI (≤0.10.2) sends `Authorization: Bearer <key>` even when the key is
   empty; the resulting header value `Bearer` + trailing space is illegal
   HTTP and the connection fails client-side with "Failed to connect to
   MCP server" before any request is sent. mcp-tools ignores the key's
   value.
2. **Workspace → Models → New Model**:
   - **Name**: the preset's context name (e.g. "Research Assistant").
   - **Base model**: as listed in the preset.
   - **System prompt**: paste from the preset file.
   - **Tools**: tick the connections listed in the preset.
   - **Advanced params → Function calling: Native** (recommended for the
     qwen3.5/qwen3.6 leads; revert to Default if tool calls get unreliable
     on a given base model).
   - **Capabilities: turn OFF Web Search, Builtin Tools, Code Interpreter,
     Image Generation, and Terminal.** These are OpenWebUI's own native
     tools (all on by default) and they collide with the MCP tools above —
     e.g. its native `write_note` looks like a plausible way to "write
     documentation" and the model will use it instead of
     `outline_create_document`, silently writing to a private OpenWebUI
     Note instead of the wiki, then invent a wrong explanation when asked
     why the wiki wasn't updated. Leave `file_context`, `vision`,
     `file_upload`, `citations`, and `status_updates` on — those don't
     conflict. **Presets created before 2026-07-07 need this applied
     retroactively** — open each one in Workspace → Models → Edit and
     flip the five toggles off.
3. Save. The context now appears in the chat model picker.

## Presets

| Context | Base model | Tool domains |
| --- | --- | --- |
| [Task Dispatcher](task-dispatcher.md) | qwen3.6:35b-64k | agents, approvals, web, outline |
| [App Builder](app-builder.md) | qwen3.6:35b-64k | devteam, project |
| [Debate Moderator](debate-moderator.md) | qwen3.6:35b-64k | debate, web |
| [Researcher](researcher.md) | qwen3.6:35b-64k | web |
| [Investment Strategist](investment-strategist.md) | qwen3.6:35b-64k | web, project |
| [Research Assistant](research-assistant.md) | qwen3.5:9b | web |
| [Ops Assistant](ops-assistant.md) | qwen3.5:9b | outline, inventree, plane, n8n, freescout, triggerdev, approvals |
| [Knowledge Curator](knowledge-curator.md) | qwen3.5:9b | outline, web, approvals |
| [Inventory Manager](inventory-manager.md) | qwen3.5:9b | inventree, approvals |
| [Coding Assistant](coding-assistant.md) | qwen3.6:35b | web |
| [Studio](studio.md) | qwen3.5:9b | comfyui, drawio |
| [Code Auditor](code-auditor.md) | gpt-oss:20b | web (optional) |
| [General Auditor](general-auditor.md) | gpt-oss:20b | web (optional) |
| [Hardware Builder](hardware-builder.md) | qwen3.6:35b-64k | hardware, project |
| [KiCad Specialist](kicad-specialist.md) | qwen3.6:27b | project |

### Baseline tool-environment block

Every preset's system prompt **starts with the shared baseline block** from
[_baseline.md](_baseline.md) — it gives each assistant standing awareness of
mcp-tools and the `tools_help()` documentation tree without per-chat
prompting. New presets must include it; when `_baseline.md` changes, update
every preset and re-paste the prompts into their Workspace Models. (The
per-user alternative — Settings → General → System Prompt — is described in
`_baseline.md`.)

Base models follow the lead-per-domain hierarchy in [README.md](../../README.md):
leads produce work, the auditor presets give second opinions from
same-expertise, lower-benchmark models (including a different lineage) to
catch the lead's blind spots.

The same contexts exist in smolagents: web_researcher ≈ Research Assistant,
researcher ≈ Researcher (the structured research briefs the manager and
debate turns delegate to — same fixed brief format both sides),
investment_strategist ≈ Investment Strategist (same fixed assessment
format both sides; both keep warm memos in the registered `investments`
project), ops ≈ Ops Assistant, coder ≈ Coding Assistant,
writer ≈ Knowledge Curator, studio ≈ Studio. For the narrower ones (Inventory Manager), scaffold an
equivalent agent with `agent_create` if you want it in the agent workspace
too.

embedded_architect ≈ Hardware Builder (same Embedded Design Brief format
both sides; both write briefs and build plans into the registered
project) and kicad_specialist ≈ KiCad Specialist — except Hardware Builder
is the engagement front door (carries the `hardware` domain, drives a full
requirements→architecture→milestones→fab-review→docs engagement) while the
smolagents-side `kicad_specialist` only runs inside that engagement as
embedded_architect's managed sub-agent; the standalone KiCad Specialist
preset is a lighter, engagement-independent chat echo of its persona for
ad hoc questions, not a live connection to the same running agent.

### Starting a hardware engagement

**Hardware Builder** is the front door to the hardware engagement system:
an embedded-architect agent plus a KiCad build-plan specialist
(smolagents' `agents/hardware/`) that design a circuit in a registered
`~/workspace/<project>` directory from a desired outcome, phase by phase
(requirements → architecture → per-block milestones → fab-review → docs),
each phase a background job — structurally the same engagement mechanism
as devteam (see "Starting a devteam engagement" below), forked rather than
shared (see `agents/jobs.py`'s hardware section). Advancement is
user-gated at the configured sign-offs (default: requirements,
architecture, fab-review, final delivery — fab-review is gated in every
preset except `none`, since it precedes the real, costly step of sending
a design to a manufacturer) and fully autonomous between them; the
engagement pauses as `awaiting_input` whenever the architect has
questions and resumes with `hardware_answer`. The Hardware Builder preset
refines the desired outcome, registers the project, starts the
engagement, relays questions, and records the user's approve/revise
verdicts; it deliberately does NOT carry the `agents` domain, and Task
Dispatcher/App Builder deliberately do not carry `hardware` — engagement
semantics (answer/approve on a parked session) and plain-job semantics
(`parent_job_id` re-dispatch) confuse a single preset. **No real KiCad
tooling exists yet**: every phase produces documents (design briefs, build
plans), and the fab-review phase's manufacturing-output section stays
explicitly intent-only until a future build phase adds real `kicad-cli`
execution.

### Dispatching to agents

Any preset can mention the agent workforce (it is in the baseline block),
but only chats with the **agents** tool connection can actually dispatch.
The **Task Dispatcher** preset is the dedicated front door — and more than
that, a live liaison: it also carries direct **web** and **outline**
connections so it can research and read/write the wiki itself, in the
conversation, instead of making the user fetch context manually. It
decides per request: do quick lookups, reads, and single-document wiki
work live with the user, or refine a brief and hand long/multi-specialist
work to `agent_dispatch` as a background job. Jobs run in the smolagents
container (one at a time — single-GPU model residency); reports land in
the task inbox at `mcp.localhost/inbox` and can notify via
`SMOLAGENTS_NOTIFY_WEBHOOK` (n8n). Durable *background-job* deliverables
go to the Outline collection **"Agent Deliverables"** (create it once in
Outline); direct writes from the Task Dispatcher chat go wherever the
user asks.

### Starting a devteam engagement

**App Builder** is the front door to the devteam system: a lead-architect
agent plus specialist engineers/analysts/reviewers (smolagents'
`agents/devteam/`) that build an entire application in a registered
`~/workspace/<project>` directory from a product plan, phase by phase
(requirements → architecture → scaffold → milestones → qa → docs), each
phase a background job. Unlike a debate, advancement is user-gated at the
configured sign-offs (default: requirements, architecture, final
delivery) and fully autonomous between them; the engagement pauses as
`awaiting_input` whenever the architect has questions and resumes with
`devteam_answer` — this is the one queue where the team CAN ask the user
questions mid-run. The App Builder preset refines the plan, registers the
project, starts the engagement, relays questions, and records the user's
approve/revise verdicts; it deliberately does NOT carry the agents
domain, and Task Dispatcher deliberately does not carry devteam —
engagement semantics (answer/approve on a parked session) and plain-job
semantics (`parent_job_id` re-dispatch) confuse a single preset.

### Starting a debate

**Debate Moderator** is the front door to a separate, parallel system: a
fixed team of three personas (entrepreneur, critic, monitor) that argue a
goal over several rounds, one turn at a time, each turn a background job
that automatically queues the next once it finishes — no orchestration
needed once started. The Moderator's only job is to refine an ambiguous
ask into a concrete brief (goal, mode, deliverables, constraints) the same
way Task Dispatcher refines one before `agent_dispatch`, then call
`debate_start` itself. Track a running debate with `debate_status`
(quick check), `debate_manifest` (sequenced index of every round with a
one-line description — useful for deciding what's worth reading in full),
or `debate_read_round` (one round's complete text); a debate stuck after a
crash or a failed turn surfaces via `debate_status`'s `stop_reason` and is
recovered with `debate_resume` or ended with `debate_cancel`. See the
model hierarchy table for why the entrepreneur/monitor personas default to
the same lead as Task Dispatcher while the critic deliberately uses a
different model lineage.
