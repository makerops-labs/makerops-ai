# Tooling for small local models

## Principle

Small models lean hard on semantic priors: they infer what a tool or action
does from its *name* and fill gaps with plausible guesses. Strip the
suggestive name (or use a tool outside training distribution) and performance
collapses — unless the semantics are spelled out. State every tool's
preconditions, effects, and failure modes explicitly, and keep the injected
context small enough that the model actually reads them.

## Practice

- **Write-tool docstrings carry a semantic trailer**: one terse line each for
  `Preconditions:` (what must be true before calling), `Effects:` (what
  changes, including side effects like restarts or notifications), and
  `Failure modes:` (how it fails and what the error looks like). Terseness is
  part of the spec — descriptions ship in tool schemas to every attached
  agent.
- **Never rely on the name.** If correct use of a tool depends on knowledge
  not in its docstring, the docstring is incomplete — a model that has never
  seen this stack must be able to use it safely from the docstring alone.
- **Progressive disclosure over preloading.** Long tool lists and bulky
  context measurably degrade small models. Attach only the domains a task
  needs; expose the rest through an on-demand documentation tree.
- **Structure beats scale.** An 8–9B model with enforced stepwise reasoning
  plus an external verifier approaches frontier-model planning quality — reach
  for structure and verification before reaching for a bigger model.

## Evidence

In PDDL-Instruct (see [pddl-instruct-source.md](pddl-instruct-source.md)),
obfuscating predicate names (Mystery Blocksworld) collapsed baseline accuracy
from 28% to 1%; explicit precondition/effect reasoning recovered it to 64% —
direct proof that models substitute name-priors for missing semantics. The
same framework took Llama-3-**8B** to 94% on Blocksworld, above GPT-4's 91%
under identical treatment.

## Stack mapping

- WRITE ACTION tools in `mcp-tools/tools/*.py` carry the
  Preconditions/Effects/Failure-modes trailer; the docs tree
  (`mcp-tools/tools/docs_tree.py`) renders full docstrings only at the tool
  leaf, so the trailer costs nothing until an agent drills in — but note MCP
  tool schemas always include the full description for *attached* domains.
- Progressive disclosure: `GET /context` tree + `tools_help(path)` on every
  domain endpoint; `smolagents/agents/context.py` injects only the root
  manifest.
- Model hierarchy (`makerops-ai/README.md`): structure + decorrelated review
  is why 9B-class leads are viable at all.
