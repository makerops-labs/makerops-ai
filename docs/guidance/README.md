# AI guidance library

Distilled, actionable best practices for building and operating the agents in
this stack. Written for AI consumption: each doc is short, imperative, and ends
with a **Stack mapping** section pointing at where the practice is (or should
be) applied in this repo. Humans are welcome too.

## How to consume

- **Claude sessions**: read the doc relevant to what you are changing
  (pointer lives in `CLAUDE.md`).
- **Local agents**: the set is served through the mcp-tools progressive-
  disclosure tree — `tools_help('guidance')` or `GET /context/guidance` —
  pull a doc on demand, never preload all of them.
- **Open WebUI**: the docs are mirrored to the Outline collection
  "Guidance" for RAG retrieval. Git (this directory) is the source of
  truth; re-publish after meaningful edits.

## Index

| Doc | One-line takeaway |
| --- | --- |
| [planning-state-tracking.md](planning-state-tracking.md) | Plan as explicit state→action→state chains: verify preconditions, track effects, check goal progress. |
| [external-verification.md](external-verification.md) | LLMs cannot reliably self-verify — route outputs through external validators, and make failure feedback detailed, not binary. |
| [negative-examples.md](negative-examples.md) | Teach with deliberately-invalid examples plus *why* they fail; document footguns next to happy paths. |
| [small-model-tooling.md](small-model-tooling.md) | Small local models need explicit semantics: tool docs state preconditions/effects/failure modes; keep injected context minimal. |
| [pddl-instruct-source.md](pddl-instruct-source.md) | Reference distillation of the source paper (arXiv:2509.13351) with methodology and numbers. |

## Convention for adding a new distillation

One reference doc per source (`<slug>-source.md`: citation, methodology,
quantitative results, limitations) plus edits to the practice docs above —
extend an existing practice doc rather than adding a parallel one when the
lesson overlaps. Every practice doc keeps the structure: **Principle → Practice
(imperative bullets) → Evidence (one paragraph, cite the source doc) → Stack
mapping (file paths)**. Update this index and re-publish to Outline.

## Future work (deliberately deferred)

- Fine-tuning a local qwen on logical-CoT planning traces (PDDL-Instruct
  Phases 1–2 proper) — needs training infra; prompt-level discipline captures
  most of the value first.
- A dedicated plan-verifier agent for multi-step jobs — revisit once the
  manager's inline precondition/effect discipline has observable effect on
  job failure rates.
