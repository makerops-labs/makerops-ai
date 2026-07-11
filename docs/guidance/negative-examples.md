# Teaching with negative examples

## Principle

Models learn a task's boundaries fastest from deliberately-invalid examples
annotated with *why* they fail. Prompts, orientation docs, and tool docs that
show only the happy path leave the failure modes to the model's imagination.

## Practice

- When writing a system prompt or task brief for a recurring failure mode,
  include one concrete **bad example plus the reason it is wrong**, next to the
  good example. "Never do X" is weaker than showing X and naming the violated
  requirement.
- Classify failures when documenting them — the useful taxonomy from planning
  transfers broadly: **precondition violation** (acted before the state
  allowed it), **effect misapplication** (assumed a result that didn't
  happen), **frame violation** (clobbered something that should have been
  untouched), **goal failure** (finished without meeting the objective).
- Maintain a **footgun section** in every orientation doc (project context,
  service README, CLAUDE.md): the mistakes that already cost debugging time,
  stated as "doing X causes Y — do Z instead".
- When a verifier rejects work, **preserve the rejection with its reason**
  where the next attempt (or the next agent) will see it — rejections are
  training data for the session even without fine-tuning.

## Evidence

PDDL-Instruct's Phase 1 (see
[pddl-instruct-source.md](pddl-instruct-source.md)) trained on valid plans
*and* deliberately corrupted ones annotated with their violation class
(precondition / effect / frame / goal). Phase 1 alone took Llama-3-8B from
28% to 78% on Blocksworld — error education delivered the single largest jump
in the whole pipeline.

## Stack mapping

- `makerops-ai/CLAUDE.md` "Architecture facts that cost debugging time" is
  the stack's footgun ledger — keep feeding it.
- `smolagents/agents/manager.py` `_PROCEDURE` step 2b already teaches by
  negative example ("a plan dressed up as a deliverable is a failed job that
  LOOKS finished"); use that pattern for new procedure rules.
- `PROJECT_CONTEXT.md` seeds (mcp-tools `tools/project.py`) should carry
  project-specific footguns as they are discovered.
- Verifier rejections that agents see: `propose_code_change` returns the
  SyntaxError text; `redeploy` reverts include the container log tail — both
  are negative examples in-band.
