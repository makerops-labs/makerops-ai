# Model-development playbook

How to develop this stack's own specialized local models — starting with the
target the user actually wants: **software-operation models** that manage
software tasks from prompted goals (the work the manager/coder agents do
today with general-purpose leads). This document is the durable roadmap;
update it as learnings land. Companion docs:
[docs/guidance/local-finetuning-feasibility.md](guidance/local-finetuning-feasibility.md)
(what this hardware can train) and
[experiments/seal-lora/](../experiments/seal-lora/) (the working prototype
of the core loop).

Grounding papers, distilled in [docs/guidance/](guidance/):
PDDL-Instruct (arXiv:2509.13351 — logical-CoT traces + external
verification for planning) and SEAL (arXiv:2506.10943 — self-generated
training data judged by downstream reward).

## Why specialize at all

A small model trained on *this stack's* tasks competes with a much larger
general model on those tasks: PDDL-Instruct took an 8B model from 28% to
94% on planning (above GPT-4's 91% under the same treatment), and SEAL
showed a model's own restatements of new material beat GPT-4.1-generated
training data. Specialization is the small-hardware path to frontier-like
behavior in a narrow domain.

## 1. Data strategy — the stack is already collecting it

Every dispatched job leaves a labeled trajectory on disk. That is training
data no public dataset has: this stack's tools, this stack's conventions,
real success/failure labels.

| Source | Location | Use |
| --- | --- | --- |
| Job briefs + reports | `smolagents/data/smolagents/jobs/<id>/job.json` | task prompt (brief) + outcome label (status, report) |
| Step-level traces | smolagents telemetry / job segments | tool-call trajectories (state→action→observation) |
| Audit findings | `mcp-tools/data/mcp-tools/audit.jsonl` + auditor reports | negative examples with named defects |
| Redeploy reverts | audit.jsonl (`redeploy.reverted` + log tail) | failure traces with the actual error attached |
| Approvals decisions | approvals store | human preference labels on write actions |

Recipe:

- **Positives**: trajectories from jobs that ended `completed` with a clean
  audit — filtered behavior cloning keeps only these (SEAL's binary-reward
  filter, applied offline).
- **Negatives with explanations** (PDDL-Instruct "error education" — its
  single biggest gain, +50 pts in Phase 1 alone): failed/reverted/audited
  trajectories annotated with the violation class — precondition violation
  (acted before the state allowed), effect misapplication (assumed a result
  that didn't happen), frame violation (clobbered something unrelated),
  goal failure (finished without meeting the brief).
- **Augmentation** (SEAL self-edits): for each kept trajectory, have the
  current lead generate implications/restatements — why each action was
  valid, what the state was before/after — as additional atomic training
  examples. The generator can be the model being trained; quality of the
  *format* matters more than generator strength.
- **Hygiene**: strip secrets/tokens from traces before they enter a
  dataset (`.env` values, API keys in tool args); keep datasets in the
  private repo or outside git entirely.

## 2. Trace format — train the reasoning, not just the answer

Format traces as logical chains, the representation both papers converge on:

```text
STATE: <atomic facts currently true>
GOAL:  <what the brief requires>
THINK: preconditions of <action>: <p1 — verified how>, <p2 — ...>
       expected effect: <e1>
ACT:   <tool call>
OBS:   <tool result>
CHECK: effect held? <yes/no — evidence>   invariants intact? <...>
... (repeat)
REPORT: <final structured report>
```

Software-operation specifics: include the Preconditions/Effects/Failure-
modes trailer of each tool used (they're already in the docstrings) so the
model learns tool semantics explicitly, not from names (Mystery-Blocksworld
lesson: names alone collapse to ~1%).

## 3. Training recipe (local scale)

1. **SFT via QLoRA** on the formatted traces — sizes/params per the
   feasibility doc; start at 3–8B base (Qwen lineage, matching the stack's
   leads) with r=16–64.
2. **One filtered-BC round instead of full RL** (the local-affordable
   stand-in for SEAL's ReST-EM): generate k candidate trajectories per
   held-out brief with the current adapter, score them with **external
   verifiers only** (tests pass, health checks, auditor findings, brief
   deliverables exist), SFT on the winners. Each round is hours, not
   H100-days, because the inner loop is cheap and the expensive part
   (candidate scoring) is bounded by k × briefs.
3. **Iterate on benchmark evidence**, matching the stack's existing
   model-hierarchy convention: a self-trained model takes a lead slot only
   when it beats the incumbent on the eval set; the incumbent becomes a
   reviewer.

## 4. Evaluation — external verifiers are the reward

- Hold out a fixed set of job briefs (grow it as jobs accumulate; never
  train on it).
- Score ONLY with programmatic ground truth: project test suites via
  `project_run_command`, container health via redeploy, deliverable
  existence checks, plus the decorrelated reviewer pool for quality —
  never the trained model's self-assessment (both papers: models cannot
  self-verify).
- Track per-capability scores, not one aggregate — see §5.

## 5. Forgetting mitigation (SEAL's stated failure mode)

Sequential unconstrained updates dropped early-task accuracy 80%→20% in the
paper. Locally:

- **One LoRA adapter per specialization**, swapped at load time — never
  sequentially retrain one adapter on new domains, and never merge-and-
  retrain the base. Ollama serves base+adapter; switching specializations
  is a model swap, same as today's hierarchy.
- **Regression set**: every capability the model is relied on for gets a
  few held-out cases; run the full set before promoting any new adapter
  version. A gain on the new skill that costs an old one is a rejection.

## 6. Integration into the stack

1. Train → merge or keep adapter separate → **convert to GGUF**
   (llama.cpp `convert_hf_to_gguf.py`), quantize (Q4_K_M default, match
   the stack's serving quants).
2. **Ollama Modelfile** (`FROM ./model.gguf` or `FROM base` + `ADAPTER`),
   `ollama create <name>` — same path as the existing `qwen3.5:9b-64k`
   derivative (checklist §1).
3. Slot into the **model hierarchy** per the existing convention: update
   `SMOLAGENTS_*_MODEL_ID` env vars, openwebui context base models, README
   table. Reviewer decorrelation applies to self-trained models *more*,
   not less — a model trained on this stack's own outputs shares its blind
   spots, so keep at least one cross-lineage reviewer (gpt-oss) in every
   pool that reviews it.

## 7. Milestones

- **M0 (done 2026-07-11)**: single-round self-edit → QLoRA → eval loop runs
  locally — `experiments/seal-lora/`. Measured finding: both adapters beat
  base, but a 1.5B model's own implications lost to the raw-passage control
  — self-edit generation quality is the bottleneck, so M1+ should have the
  strongest lead (35B via Ollama) generate training data for the small
  student, and lean on verified filtering over format cleverness. Numbers
  in the feasibility doc.
- **M1**: trace-extraction script — jobs/audit stores → formatted SFT
  dataset (start read-only, no stack changes needed).
- **M2**: first specialization attempt: **report discipline** for the 9B
  general lead (the stack's best-documented weakness — narrating instead of
  calling `final_answer`, dict-format reports; plentiful labeled examples
  already exist in job history). Small, measurable, low-risk.
- **M3**: software-operation adapter for coder-style tasks (write file →
  edit → run tests → report), trained on M1 data + error education;
  evaluated on held-out briefs with `project_run_command` as the verifier.
- **M4**: filtered-BC improvement round on M3; promote to a hierarchy slot
  only on benchmark evidence.

## Update log

- 2026-07-11 — created, from the SEAL + PDDL-Instruct distillations.
