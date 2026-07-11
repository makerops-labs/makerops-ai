# External verification and detailed feedback

## Principle

LLMs cannot reliably verify their own reasoning — route outputs through
verifiers *outside* the producing model, and when verification fails, feed
back the specific violation, never a bare pass/fail.

## Practice

- **Verifier hierarchy** — prefer the highest available rung:
  1. **Programmatic ground truth**: syntax checks, test suites, health checks,
     schema validation, running the code. Cheap, exact, incorruptible.
  2. **Decorrelated LLM reviewers**: different models (ideally different
     lineages) than the producer, reviewing independently.
  3. **Self-review**: last resort only; treat its verdict as weak evidence,
     never as a gate.
- **Detailed feedback beats binary.** A failing verifier must report *what*
  failed and *where* — the violated precondition, the traceback, the failing
  test name — because that report is the input to the next repair attempt.
  If your validator only says "invalid", fix the validator before blaming the
  model.
- **Bound the verify-refine loop.** Give repair loops an explicit iteration
  budget; expect consistent but diminishing returns per iteration. Pair the
  budget with a no-progress guard: if an iteration changes nothing observable,
  stop and escalate instead of burning the budget.
- **Verify at the transition, not the end.** Checking each step catches errors
  before they compound; a final-answer-only check discards all localization.

## Evidence

PDDL-Instruct (see [pddl-instruct-source.md](pddl-instruct-source.md)) is
built on an external plan validator (VAL); the authors cite prior findings
that LLMs "cannot self-correct reasoning yet". Detailed feedback (naming the
violated precondition/effect) outperformed binary valid/invalid by 5–15
points depending on domain; raising the iteration budget η from 10 to 15
added ~4.3 points on average.

## Stack mapping

- Programmatic rung: `ast.parse` gate in `mcp-tools/tools/agents_domain.py`
  (`propose_code_change`), health-check + auto-revert in `redeploy/main.py`
  (which reports the failing container's log tail — detailed, not binary),
  `project_run_command` test runs.
- Decorrelated-reviewer rung: the reviewer pools in
  `smolagents/agents/audit_agent.py` and the model-hierarchy convention
  (lead produces, lower-benchmark + cross-lineage models review).
- Bounded refinement: the report-salvage pass in `smolagents/agents/jobs.py`
  (one short re-run, then degrade honestly) and the segment auto-continue
  with its synopsis no-progress guard.
- Human approval at `/approvals` is the top-level external verifier for
  self-modification.
