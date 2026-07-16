# Thinking before answering

## Principle

For judgment-heavy, non-mathematical tasks, generate structured private
thoughts *before* composing the response — zoom out to the pattern class, list
candidate intuitive conclusions, draft, evaluate the draft — and surface only
the clean, fixed-format answer. Thought-leadership belongs in the thoughts;
discipline belongs in the output. Applied only to thought-leader roles:
direction-followers (routers, CRUD operators, small models, coding agents)
stay direct.

## Practice

- **Direct the content of the thoughts, not just their existence.** An
  unguided "think first" underperforms; the working scaffold is: (1) what
  broader class of problem is this an instance of, and what does that class
  imply (base rates, typical failure modes)? (2) 2–3 candidate conclusions or
  relations an experienced practitioner would intuit — at least one from an
  adjacent domain — each marked evidence-backed or hunch; (3) draft the
  answer, then judge the draft against the required output contract.
- **For reviewer roles, use the draft-and-evaluate variant**: draft findings,
  then re-review your own draft as a harsher reviewer — a finding without a
  concrete triggering input/state/scenario is dropped; a systemic pattern
  across surviving findings is itself a finding.
- **Hide the thoughts.** The response must contain no scratchpad headings and
  no commentary about the procedure. On hybrid-thinking models (qwen3.x) and
  native-reasoning models (gpt-oss) the scaffold directs content into the
  existing thinking channel — never fight or replace that channel.
- **Make leakage strippable by code, never by another LLM.** Wherever an
  output feeds another agent's turn, require the exact markers
  "Here is my thought process:" / "Here is my response:" for any forced
  leakage, and strip with a deterministic function
  (`agents/thoughts.strip_thoughts`) at the choke point.
- **Convert hunches into verification where tools allow it**: a researcher's
  intuitive lead is a search lead — spend a tool round checking a checkable
  hunch instead of shipping it as speculation; label what remains
  `(interpretation)`.
- **Do not scaffold**: routers with strict dispatch contracts, small-model
  (≤9b) presets with known report-discipline issues, precise-computation and
  coding roles (the evidence says they benefit least or regress), or
  latency-bound voice paths.

## Evidence

Thinking LLMs / TPO (see
[thought-generation-source.md](thought-generation-source.md)) trained
Llama-3-8B to think privately before answering, judging only the response:
+4.1 AlpacaEval LC over an identically-trained direct baseline, with gains
concentrated in non-reasoning categories (marketing, health, research,
general knowledge) and math flat-to-negative. Untrained thought prompting
underperformed until thought *content* was structured (plan → draft →
evaluate), which is the transferable inference-time piece adopted here.

## Stack mapping

- `smolagents/agents/thoughts.py` — `THINK_FIRST` (generic scaffold),
  `DRAFT_AND_EVALUATE` (reviewer variant), `strip_thoughts()` (deterministic
  leak backstop). Opt-in per agent; direction-follower agents must not import
  it.
- `smolagents/agents/researcher_agent.py`, `investment_agent.py` —
  `THINK_FIRST` appended to the persona; researcher brief gains an optional
  `**Patterns & leads:**` slot where pattern-level insight surfaces.
- `smolagents/agents/audit_agent.py` — reviewer pool prompts carry
  `DRAFT_AND_EVALUATE`; `collect_reviews` strips leaked thoughts before
  aggregation.
- `smolagents/agents/debate/` — entrepreneur/critic personas think before
  arguing (monitor: synthesis mode only; the checkpoint VERDICT path stays
  mechanical); `jobs.py` `_clean_round_text` strips leaked thoughts so a
  scratchpad can never poison the next round.
- `openwebui/contexts/` — researcher, investment-strategist, code-auditor,
  general-auditor, debate-moderator presets carry the chat-side adaptation
  (general-auditor uses a visible two-part output — originally because its
  then-base gemma4:12b, retired 2026-07, had no hidden thinking channel;
  kept on gpt-oss:20b for the auditable trail).
- NOT applied (deliberately): task-dispatcher, research-assistant and other
  9b presets, manager (`planning_interval` + `_PROCEDURE` is its thinking
  mechanism), coder/coding-assistant, alexa_liaison.
