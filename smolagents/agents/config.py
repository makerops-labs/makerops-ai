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


def _model_list(env_var: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(env_var, default).split(",")
            if m.strip()]


# Reviewer pools for the audit agent: same-expertise models that sit below
# the lead on benchmarks, used to catch the lead model's blind spots.
# gpt-oss is a different lineage (OpenAI vs Qwen/Gemma), which decorrelates
# the review. See the model hierarchy table in README.md.
CODING_REVIEW_MODEL_IDS = _model_list("SMOLAGENTS_CODING_REVIEW_MODEL_IDS",
                                      "qwen3-coder:30b,gpt-oss:20b")
# qwen3.5:9b is the former general lead, kept as a reviewer per the
# lead-switch convention (old lead becomes a reviewer).
GENERAL_REVIEW_MODEL_IDS = _model_list("SMOLAGENTS_GENERAL_REVIEW_MODEL_IDS",
                                       "qwen3.5:9b,gemma4:12b,gpt-oss:20b")

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
