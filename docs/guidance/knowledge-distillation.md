# Knowledge distillation for persistent memory

## Principle

This stack adapts through documents, not weights: PROJECT_CONTEXT.md,
synopsis.md, the Outline wiki, and per-user memory files are its weight
updates. What makes finetuning data effective makes memory writes effective
too: **distilled, self-generated implications and atomic facts beat pasted
raw source**, and **unmanaged rewrites destroy earlier knowledge** exactly
like catastrophic forgetting.

## Practice

- **Distill, never transcribe.** When saving new knowledge, write the
  implications and consequences in your own words — what this fact *means*
  for the project, what decisions it settles, what it rules out. The raw
  source (transcript, tool output, web page) is an appendix or a link,
  never the body of a memory document.
- **Atomic facts.** Break knowledge into small, self-contained statements
  that stand without surrounding context. Each should survive being read
  alone — that is also what RAG retrieval returns: one chunk, no neighbors.
- **Format for the downstream reader.** Ask who consumes this next (a
  stateless agent resuming the project, a RAG query, a human skimming) and
  shape the entry for that use — a fact nobody can retrieve or apply is not
  stored, it is buried.
- **Update by curation, not replacement.** Prefer targeted edits over
  wholesale rewrites of a context doc. Before overwriting a section, check
  what it currently says: every still-true fact you drop is a regression,
  even though the write itself "succeeds". Full-file rewrites of long-lived
  docs are how memories silently rot.
- **Judge a memory edit by downstream performance.** The test of a context
  update is whether the *next* session or job goes better because of it —
  not whether the text reads well. If resuming agents keep re-deriving the
  same fact or re-hitting the same footgun, the memory write failed,
  whatever it looked like.
- **Constrain the format with templates.** Autonomous choice of note format
  works but is imperfect — seeded templates and fixed sections (status /
  architecture / footguns / further reading) outperform open-ended freedom.

## Evidence

SEAL (see [seal-source.md](seal-source.md)): finetuning a model on its own
generated implications of a passage beat finetuning on the passage itself
(39.7% vs 33.5% closed-book QA, 47.0% after RL), and its self-edits
converged on "easily learnable atomic facts." Its RL reward was purely
downstream task performance. Its stated failure mode — ~80%→20% accuracy on
early tasks after 8 sequential unconstrained edits — is the weight-space
version of overwriting a context doc without preserving what still holds.

## Stack mapping

- `PROJECT_CONTEXT.md` (seeded by `mcp-tools/tools/project.py`) — the
  template's curation rules encode this doc; update via `project_edit_file`
  targeted edits.
- `<workspace>/synopsis.md` — the manager's procedure (steps 5/5b in
  `smolagents/agents/manager.py`) requires distillation, not pasted returns.
- Outline ingestion — `openwebui/contexts/knowledge-curator.md` and the
  writer agent (`smolagents/agents/writer_agent.py`) distill sources into
  self-contained statements; `outline_update_document` with `append=True`
  or itemized `changes_summary` over silent full replacement.
- Hermes profiles (`docs/hermes-setup.md`) and Claude auto-memory follow the
  same one-fact-per-entry, curate-don't-duplicate discipline.
