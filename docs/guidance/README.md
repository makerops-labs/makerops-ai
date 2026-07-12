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
| [external-verification.md](external-verification.md) | LLMs cannot reliably self-verify — route outputs through external validators, make failure feedback detailed, and judge adaptations by downstream performance. |
| [negative-examples.md](negative-examples.md) | Teach with deliberately-invalid examples plus *why* they fail; document footguns next to happy paths. |
| [small-model-tooling.md](small-model-tooling.md) | Small local models need explicit semantics: tool docs state preconditions/effects/failure modes; keep injected context minimal. |
| [knowledge-distillation.md](knowledge-distillation.md) | Persistent memory is this stack's weight update: write distilled implications and atomic facts, curate instead of overwriting, judge edits by later outcomes. |
| [local-finetuning-feasibility.md](local-finetuning-feasibility.md) | What actually trains on the local RTX 4070 Ti SUPER 16GB: QLoRA sizes, toolchain, costs, GGUF→Ollama path, go/no-go per use case. |
| [thinking-before-answering.md](thinking-before-answering.md) | Thought-leader roles think privately before answering — pattern class, candidate leaps, draft+evaluate — and surface only the clean fixed-format response. |
| [pddl-instruct-source.md](pddl-instruct-source.md) | Reference distillation of PDDL-Instruct (arXiv:2509.13351): logical CoT + external verification for planning. |
| [seal-source.md](seal-source.md) | Reference distillation of SEAL (arXiv:2506.10943): self-generated training data judged by downstream reward. |
| [thought-generation-source.md](thought-generation-source.md) | Reference distillation of Thinking LLMs / TPO (arXiv:2410.10630): pre-response thought generation, response-only judging. |

## Convention for adding a new distillation

One reference doc per source (`<slug>-source.md`: citation, methodology,
quantitative results, limitations) plus edits to the practice docs above —
extend an existing practice doc rather than adding a parallel one when the
lesson overlaps. Every practice doc keeps the structure: **Principle → Practice
(imperative bullets) → Evidence (one paragraph, cite the source doc) → Stack
mapping (file paths)**. Update this index and re-publish to Outline.

## Future work (deliberately deferred)

- Local fine-tuning is no longer wholesale-deferred: see
  [local-finetuning-feasibility.md](local-finetuning-feasibility.md) for
  what's achievable on this hardware, `../model-development-playbook.md`
  for the roadmap toward specialized self-trained models, and
  `../../experiments/seal-lora/` for the working single-round prototype.
  Still deferred: SEAL's full RL outer loop (multi-round ReST-EM) and
  training production-tier replacements for the current leads.
- A dedicated plan-verifier agent for multi-step jobs — revisit once the
  manager's inline precondition/effect discipline has observable effect on
  job failure rates.
