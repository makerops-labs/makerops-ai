# Planning as explicit state tracking

## Principle

Treat a multi-step plan as a chain of state→action→state transitions, not a
to-do list. Before each action: verify its preconditions against the *current*
state. After each action: apply its effects to an explicit state record and
check progress toward the goal. Plans fail when state is carried implicitly in
the model's head.

## Practice

- Before any consequential or irreversible action, state its **preconditions**
  and check the ones that are checkable (file exists? service healthy? approval
  granted?). If a precondition is unverifiable, say so and treat the action as
  higher-risk.
- State the action's **expected effect** before executing. After executing,
  verify the effect actually holds before depending on it — a delegate's
  "done" report is a claim, not a state change.
- Keep an **explicit state file** for any work spanning multiple steps or
  sessions: current facts, decisions taken, and a checklist where items are
  marked done only when their effect is observable (the artifact exists with
  real content).
- Watch **invariants**: things that must stay true across the whole plan
  (service stays healthy, budget not exceeded, no untracked writes). Re-check
  them at phase boundaries, not just at the end.
- Evaluate **goal progress** each phase: does the current state measurably
  approach the goal, or are steps being consumed without state change? No
  progress → stop and report, don't loop.

## Evidence

PDDL-Instruct (see [pddl-instruct-source.md](pddl-instruct-source.md)) raised
Llama-3-8B from 28% to 94% planning accuracy on Blocksworld chiefly by forcing
generation of explicit ⟨state, action, state⟩ chains with per-action
precondition verification and effect application, validated externally. The
structure, not model scale, delivered the gain.

## Stack mapping

- `smolagents/agents/manager.py` `_PROCEDURE` — PLAN step requires stating
  preconditions/expected effects for consequential actions; WORKING MEMORY step
  requires verifying effects before checking off tasks.
- `<workspace>/synopsis.md` (job segments) and `PROJECT_CONTEXT.md` (projects)
  are the stack's explicit state files — the no-progress guard in
  `smolagents/agents/jobs.py` already refuses to auto-continue a segment whose
  synopsis didn't change.
- `redeploy/main.py` treats "container healthy after restart" as an invariant
  with auto-revert — the model pattern for invariant enforcement.
