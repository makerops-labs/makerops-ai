"""Environment-driven configuration shared by all agents.

Defaults assume a host venv talking to Ollama on localhost. The Docker
service overrides OLLAMA_API_BASE and SMOLAGENTS_DATA_DIR via compose.
"""

import os

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434/v1")
# Ollama ignores the key, but the OpenAI client requires a value.
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "ollama")

CODING_MODEL_ID = os.environ.get("SMOLAGENTS_CODING_MODEL_ID", "qwen3.6:35b")
GENERAL_MODEL_ID = os.environ.get("SMOLAGENTS_GENERAL_MODEL_ID", "qwen3.6:35b-64k")

# Per-request ceiling on one model call. Generous on purpose: a 35b step at
# ~30k tokens of context legitimately takes 15+ minutes on this hardware
# (partial CPU offload). Without an explicit value, a wedged Ollama call
# can hold a job "running" indefinitely — job-1784231534 sat silent for
# 3h+ (2026-07-16) with the single-threaded worker blocked behind it. A
# timeout converts that hang into a failed job → stuck session → the
# normal resume path. MODEL_MAX_RETRIES stays low because a retried
# timeout re-prefills the same huge context.
MODEL_TIMEOUT_S = float(os.environ.get("SMOLAGENTS_MODEL_TIMEOUT_S", "1800"))
MODEL_MAX_RETRIES = int(os.environ.get("SMOLAGENTS_MODEL_MAX_RETRIES", "1"))

# A running job whose last step heartbeat is older than this triggers ONE
# job.stalled webhook (per job) from the watchdog thread in jobs.py. The
# watchdog never kills the job — Python threads can't be interrupted, and
# the model timeout above already bounds a hung call; this is the early
# human signal that the worker may be wedged (e.g. an MCP call hanging).
JOB_STALL_NOTIFY_S = float(os.environ.get("SMOLAGENTS_JOB_STALL_NOTIFY_S",
                                          "2700"))


def _model_list(env_var: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(env_var, default).split(",")
            if m.strip()]


# Reviewer pools for the audit agent: same-expertise models used to catch
# the lead model's blind spots. gpt-oss is a different lineage (OpenAI vs
# Qwen), which decorrelates the review. See the model hierarchy table in
# README.md. qwen3.8:27b-64k (successor to qwen3.6:27b, swapped 2026-08-26)
# out-benchmarks the 35b coding lead (61.7 vs — SWE-bench Pro) but is
# dense — ~14 tok/s generation on this hardware (measured on the 3.6
# generation, 2026-07-16; same architecture/footprint) — too slow to lead
# agentic loops. Reviews are unattended background work, so the speed
# penalty is free here (see docs/model-stack.md's 2026-08-26 pass) — it
# reviews instead of leading. The -64k derivative (not the bare tag) is
# required: this model's reasoning burns Ollama's 4k default context
# before ever producing review output (observed 2026-08-28 on the
# Researcher preset — see docs/model-stack.md's 2026-08-28 note).
CODING_REVIEW_MODEL_IDS = _model_list("SMOLAGENTS_CODING_REVIEW_MODEL_IDS",
                                      "qwen3.8:27b-64k,gpt-oss:20b")
# qwen3.5:9b is the former general lead, kept as a reviewer per the
# lead-switch convention (old lead becomes a reviewer).
GENERAL_REVIEW_MODEL_IDS = _model_list("SMOLAGENTS_GENERAL_REVIEW_MODEL_IDS",
                                       "qwen3.5:9b,gpt-oss:20b")

DATA_DIR = os.environ.get("SMOLAGENTS_DATA_DIR", "./data")
MAX_STEPS = int(os.environ.get("SMOLAGENTS_MAX_STEPS", "12"))

# Manager orchestration: extra step headroom, periodic replanning, and the
# segment cap for long jobs that continue from a workspace synopsis. Verified
# live that 20 exhausts mid-orchestration on a self-improvement sweep job:
# the manager receives maintainer's (large) final_answer, needs steps left to
# delegate onward to web_researcher and still compile a structured report —
# 20 wasn't enough headroom for that multi-hop delegation chain.
MANAGER_MAX_STEPS = int(os.environ.get("SMOLAGENTS_MANAGER_MAX_STEPS", "32"))

# maintainer's self-improvement procedure spans internal review (job/audit
# history) AND the external trends sweep (ledger bootstrap/dedup, research
# delegation, evaluation, reporting) — more phases than the default
# specialist budget affords; verified live that MAX_STEPS=12 exhausts
# before the sweep phase ever completes.
MAINTAINER_MAX_STEPS = int(os.environ.get("SMOLAGENTS_MAINTAINER_MAX_STEPS", "30"))
PLANNING_INTERVAL = int(os.environ.get("SMOLAGENTS_PLANNING_INTERVAL", "5"))
MAX_SEGMENTS = int(os.environ.get("SMOLAGENTS_MAX_SEGMENTS", "8"))

# Background job queue shared with mcp-tools (agent_dispatch) via bind mount.
JOBS_DIR = os.path.join(DATA_DIR, "jobs")

# Optional webhook (e.g. n8n) POSTed when a background job finishes or needs
# attention. Empty = disabled.
NOTIFY_WEBHOOK = os.environ.get("SMOLAGENTS_NOTIFY_WEBHOOK", "")

# Public URL of mcp-tools, used for inbox links in reports/notifications.
MCP_TOOLS_PUBLIC_URL = os.environ.get("SMOLAGENTS_MCP_PUBLIC_URL",
                                      "http://mcp.localhost")

# Shared MCP tool server (mcp-tools). Agents load tools from its
# per-domain endpoints; unavailable domains degrade to no tools.
MCP_TOOLS_URL = os.environ.get("SMOLAGENTS_MCP_URL",
                               "http://host.docker.internal:8099")

# Debate system: three fixed personas (entrepreneur, critic, monitor) argue
# in series, one turn per background job (see agents/debate/ and jobs.py's
# _run_debate_turn/_advance_debate — the worker runs each persona directly;
# no orchestrator LLM sits between them). Entrepreneur/monitor use
# the most capable model on the stack — both make judgment calls (building
# the case / deciding when to conclude) where quality matters more than the
# multi-minute VRAM swap cost, which is fine for an unattended background
# tool. Critic uses a different lineage (gpt-oss) so it doesn't share the
# other two's blind spots, same reasoning as the audit reviewer pools. Empty
# = fall back to get_model("general")'s role default.
DEBATE_ENTREPRENEUR_MODEL_ID = os.environ.get("SMOLAGENTS_DEBATE_ENTREPRENEUR_MODEL_ID",
                                              "qwen3.6:35b-64k")
# -32k derivative (Modelfile num_ctx bump, checklist §5h): the base model
# serves at Ollama's 4k default, and a debate turn's prompt+argument
# overflows that — the answer truncates mid-generation before the final
# answer ever lands, burning the whole step budget. Same reason the qwen
# leads have -64k derivatives.
DEBATE_CRITIC_MODEL_ID = os.environ.get("SMOLAGENTS_DEBATE_CRITIC_MODEL_ID",
                                        "gpt-oss:20b-32k")

# Personas that run as RAW completions (one plain generation against the
# persona's system prompt — the audit reviewer pool's proven pattern)
# instead of as ToolCallingAgents. Observed live: gpt-oss writes excellent
# critiques but persistently fumbles smolagents' tool-calling protocol
# (plain-text answers, typed-out pseudo final_answer() calls), burning its
# whole step budget on submission mechanics. Raw mode trades mid-turn web
# research for reliability — the right trade for the critic, whose job is
# argument, not research. Comma-separated persona names.
DEBATE_RAW_PERSONAS = {p.strip() for p in os.environ.get(
    "SMOLAGENTS_DEBATE_RAW_PERSONAS", "critic").split(",") if p.strip()}
DEBATE_MONITOR_MODEL_ID = os.environ.get("SMOLAGENTS_DEBATE_MONITOR_MODEL_ID",
                                         "qwen3.6:35b-64k")

# Dedicated researcher agent (agents/researcher_agent.py) — structured,
# multi-source research briefs, delegatable by the general manager and
# usable standalone. Empty = the general lead
# (same resident model as the managers, so delegating to it costs no VRAM
# swap).
RESEARCHER_MODEL_ID = os.environ.get("SMOLAGENTS_RESEARCHER_MODEL_ID", "")

# Investment strategist (agents/investment_agent.py) — sourced, risk-weighted
# investment assessments; carries the researcher as its own managed
# sub-agent. Empty = the general lead.
INVESTMENT_MODEL_ID = os.environ.get("SMOLAGENTS_INVESTMENT_MODEL_ID", "")

# Career coach (agents/career_agent.py) — multi-session career-profile
# building plus tailored resume/cover-letter drafting; keeps its master
# profile and per-application material in the registered `career-profile`
# project. Empty = the general lead.
CAREER_MODEL_ID = os.environ.get("SMOLAGENTS_CAREER_MODEL_ID", "")

# Step budgets are role-shaped, not one-size: research is exploration into
# the unknown and gets a deep internal budget (its whole run still counts
# as ONE step of whoever delegated to it); debate personas stay tightly
# bounded — a persona turn is one argument, not an expedition, and the
# debate-level bound is max_rounds + the monitor's verdict. Everyone else
# keeps MAX_STEPS.
RESEARCHER_MAX_STEPS = int(os.environ.get("SMOLAGENTS_RESEARCHER_MAX_STEPS", "40"))
# The strategist sits between the two: deep research is delegated (one step
# per researcher run), but memo reads/writes and quick lookups need more
# headroom than the default specialist budget.
INVESTMENT_MAX_STEPS = int(os.environ.get("SMOLAGENTS_INVESTMENT_MAX_STEPS", "20"))
# Similar shape to the investment strategist: reading several master files
# plus per-application research and drafting can take more round-trips than
# the default specialist budget.
CAREER_MAX_STEPS = int(os.environ.get("SMOLAGENTS_CAREER_MAX_STEPS", "20"))
# n8n builder (agents/n8n_builder_agent.py) — designs/validates/deploys n8n
# workflows via the n8n-mcp tools, reached through the mcp-tools `n8nmcp`
# passthrough domain (start ../n8n-mcp/ and set N8NMCP_AUTH_TOKEN in
# mcp-tools/.env). Empty model = the resident general lead (no VRAM swap to
# delegate to it). Budget above the default specialist (12): a build is discover
# → configure → validate-each-node → validate-workflow → deploy → re-validate,
# more round-trips than a one-shot task but still one sub-task, not an expedition.
N8N_BUILDER_MODEL_ID = os.environ.get("SMOLAGENTS_N8N_BUILDER_MODEL_ID", "")
N8N_BUILDER_MAX_STEPS = int(os.environ.get("SMOLAGENTS_N8N_BUILDER_MAX_STEPS", "20"))
DEBATE_PERSONA_MAX_STEPS = int(os.environ.get("SMOLAGENTS_DEBATE_PERSONA_MAX_STEPS", "12"))

# Hard cap on a single round file's size (chars) — a backstop, not the
# expected case; persona prompts target ~400-700 words on their own.
DEBATE_ROUND_MAX_CHARS = int(os.environ.get("SMOLAGENTS_DEBATE_ROUND_MAX_CHARS", "8000"))

# Bounds on what gets injected into a turn's task prompt so context stays
# flat regardless of how long the debate runs: how many manifest rows render
# before older ones collapse to "N earlier rounds omitted", and how many of
# the most recent rounds get their full text included (older ones are
# manifest-only, readable on demand via pathlib — see _DEBATE_PROCEDURE).
DEBATE_MANIFEST_RENDER_LIMIT = int(os.environ.get("SMOLAGENTS_DEBATE_MANIFEST_RENDER_LIMIT", "25"))
DEBATE_RECENT_ROUNDS_FULL = int(os.environ.get("SMOLAGENTS_DEBATE_RECENT_ROUNDS_FULL", "2"))

# Default cadence: this many entrepreneur+critic exchanges between monitor
# checkpoints (a monitor round is inserted after each cycle of 2x this many
# turns). The monitor's checkpoint decides continue/redirect/conclude.
DEBATE_MONITOR_EVERY_N_DEFAULT = int(os.environ.get("SMOLAGENTS_DEBATE_MONITOR_EVERY_N", "2"))

# Debate session directory (session.json, manifest.jsonl, rounds/) — shared
# with mcp-tools (debate_start et al.) via bind mount, same pattern as the
# job queue above.
DEBATES_DIR = os.path.join(DATA_DIR, "debates")

# Alexa liaison: a second, dedicated CodeAgent (agents/alexa_liaison.py) that
# owns voice conversations turn-by-turn, built once alongside the manager
# and reused with reset=True per turn (prior turns folded
# into the task text — see jobs.py's _format_liaison_task). One JSON session
# per Alexa userId lives here, shared with mcp-tools (liaison_turn et al.)
# via bind mount, same pattern as JOBS_DIR/DEBATES_DIR above.
LIAISON_DIR = os.path.join(DATA_DIR, "liaison")

# How many of the most recent turns (user+liaison lines) get folded into a
# turn's task text — bounded so context stays flat regardless of how long a
# voice conversation runs; older turns are simply dropped, not summarized
# (a voice session is short-lived by nature, unlike a debate's manifest).
LIAISON_HISTORY_TURNS = int(os.environ.get("SMOLAGENTS_LIAISON_HISTORY_TURNS", "12"))

# A liaison turn is "answer or delegate once, relay concisely" — a fixed
# small shape, nothing like the general manager's multi-phase procedure, so
# it gets a small step budget — this also matters for latency:
# a smaller budget makes jobs.py's salvage re-run kick in sooner on a model
# that computes build_liaison_turn(...) but forgets to call final_answer()
# with it, observed live with the 9b general model.
LIAISON_MAX_STEPS = int(os.environ.get("SMOLAGENTS_LIAISON_MAX_STEPS", "6"))

# A session with no turns for longer than this is treated as stale — its
# history is dropped before the next turn's task is built, rather than
# silently reinjecting days-old context into a "new" conversation the user
# no longer remembers starting.
LIAISON_SESSION_STALE_HOURS = float(os.environ.get("SMOLAGENTS_LIAISON_SESSION_STALE_HOURS", "6"))

# Devteam engagements: a lead-architect orchestrator plus a specialist
# software team (agents/devteam/) builds an application in a registered
# ~/workspace/<project> directory from a user-provided product plan, as a
# durable multi-phase engagement (requirements → architecture → scaffold →
# milestones → qa → docs). A fourth parallel queue sharing the job-record
# mechanism (job["devteam"], see jobs.py) with its own session store here —
# same ownership split as the debate/liaison stores.
DEVTEAM_DIR = os.path.join(DATA_DIR, "devteam")

# The lead architect is a manager-shaped orchestrator, so it gets the
# manager's proven step budget; long phases continue via segments like any
# manager job. Empty model = the resident general lead (orchestration is
# planning, and staying on the resident model means delegating to the
# general-model specialists costs no VRAM swap).
DEVTEAM_ARCHITECT_MODEL_ID = os.environ.get("SMOLAGENTS_DEVTEAM_ARCHITECT_MODEL_ID", "")
DEVTEAM_ARCHITECT_MAX_STEPS = int(os.environ.get("SMOLAGENTS_DEVTEAM_ARCHITECT_MAX_STEPS", "32"))

# Deliberate deviation from this file's usual empty-default-falls-back-to-
# lead convention, same reasoning as HARDWARE_SPECIALIST_MODEL_ID below:
# engineer phases are unattended background work (devteam's segment/
# synopsis loop already tolerates long-running jobs), so they get the
# highest-benchmark model that fits the hardware instead of the fast
# CODING_MODEL_ID lead — the lead is reserved for latency-sensitive paths
# (this same "coder" agent is also reachable live from the Gradio chat UI
# via the manager, which stays fast because it goes through get_model
# with no override). See docs/model-stack.md's 2026-08-26 pass. The -64k
# derivative (not the bare tag) is required — this model's reasoning burns
# Ollama's 4k default context before producing output (observed
# 2026-08-28 on the Researcher preset; docs/model-stack.md's 2026-08-28
# note).
DEVTEAM_ENGINEER_MODEL_ID = os.environ.get("SMOLAGENTS_DEVTEAM_ENGINEER_MODEL_ID", "qwen3.8:27b-64k")

# Engineer specialists get headroom above the default specialist budget
# (12): an engineer sub-task is write-then-verify — code via project_*
# tools plus a real project_run_command test/lint run before reporting —
# which is more round-trips than a one-shot specialist task, but still one
# sub-task, not an expedition (the architect splits bigger work).
DEVTEAM_ENGINEER_MAX_STEPS = int(os.environ.get("SMOLAGENTS_DEVTEAM_ENGINEER_MAX_STEPS", "16"))

# Cap on implementation milestones the architecture phase may plan. Each
# milestone is a whole phase job (up to DEVTEAM_ARCHITECT_MAX_STEPS ×
# MAX_SEGMENTS of model time), so this bounds how much unattended work a
# single architecture sign-off can authorize.
DEVTEAM_MAX_MILESTONES = int(os.environ.get("SMOLAGENTS_DEVTEAM_MAX_MILESTONES", "6"))

# Hardware engagements: an embedded_architect orchestrator plus a
# kicad_specialist builds a circuit design in a registered
# ~/workspace/<project> directory from a desired hardware outcome, as a
# durable multi-phase engagement (requirements → architecture → per-block
# milestones → fab-review → docs), same mechanism as devteam
# (agents/hardware/, jobs.py's hardware section, the mcp-tools `hardware`
# domain) — a parallel, forked implementation rather than a shared one; see
# jobs.py's hardware block comment for why forking (not refactoring devteam
# itself) was the deliberate choice for this pass.
HARDWARE_DIR = os.path.join(DATA_DIR, "hardware")

# The embedded architect is a manager-shaped orchestrator like the devteam
# lead architect, so it gets the same orchestration-scale step budget; long
# phases continue via segments like any manager job. Empty model = the
# resident general lead (orchestration is planning, and staying on the
# resident model means delegating to kicad_specialist/researcher/auditor
# costs no VRAM swap for the architect's own turn).
HARDWARE_ARCHITECT_MODEL_ID = os.environ.get("SMOLAGENTS_HARDWARE_ARCHITECT_MODEL_ID", "")
HARDWARE_ARCHITECT_MAX_STEPS = int(os.environ.get("SMOLAGENTS_HARDWARE_ARCHITECT_MAX_STEPS", "32"))

# kicad_specialist gets headroom above the default specialist budget (12),
# matching the devteam engineer budget: a milestone or fab-review sub-task
# is read-the-brief-then-write-the-build-plan, more round-trips than a
# one-shot specialist task but still one sub-task, not an expedition.
HARDWARE_SPECIALIST_MAX_STEPS = int(os.environ.get("SMOLAGENTS_HARDWARE_SPECIALIST_MAX_STEPS", "16"))
# Deliberate deviation from this file's usual empty-default-falls-back-to-
# lead convention (every other *_MODEL_ID above defaults to ""): pinned
# explicitly rather than following the coding lead. kicad_specialist's job —
# translating a design brief into structured sheet/net/footprint tables —
# wants dense structure-precision, which qwen3.8:27b (dense; took this role
# over from qwen3.6:27b, swapped 2026-08-26 — same architecture/footprint,
# meaningfully better benchmarks) delivers best in the stack. Keeping the
# pin explicit preserves that choice even if the coding lead changes. Do
# not "fix" this back to empty to match the convention above; that would
# undo a deliberate model choice. The -64k derivative (not the bare tag)
# is required — this model's reasoning burns Ollama's 4k default context
# before producing output (observed 2026-08-28 on the Researcher preset;
# docs/model-stack.md's 2026-08-28 note).
HARDWARE_SPECIALIST_MODEL_ID = os.environ.get("SMOLAGENTS_HARDWARE_SPECIALIST_MODEL_ID", "qwen3.8:27b-64k")

# Cap on per-block milestones the architecture phase may plan (one per
# functional block — power, MCU, sensing, radio, etc.), same reasoning as
# DEVTEAM_MAX_MILESTONES: each is a whole phase job, so this bounds how much
# unattended kicad_specialist work a single architecture sign-off authorizes.
HARDWARE_MAX_MILESTONES = int(os.environ.get("SMOLAGENTS_HARDWARE_MAX_MILESTONES", "6"))
