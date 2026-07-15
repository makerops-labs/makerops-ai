# Hardware design handoff (embedded_architect → kicad_specialist)

## Principle

A hardware engagement splits judgment from rigor across two fixed-schema
documents: the **Embedded Design Brief** (embedded_architect's judgment —
architecture, power budget, candidate BOM) and the **KiCad Build Plan**
(kicad_specialist's rigor — sheet plan, net list, footprints, DRC/ERC
expectations). Each document's headings are addressable and stable, so a
later phase, another agent, or the human reads exactly the section it
needs without loading the whole thing — the same reasoning behind the
Investment Assessment and Research Brief formats elsewhere in this stack,
extended one step further: a Build Plan is explicitly *instructions* for
what to build, not just information about what was found.

## Practice

- **Every design brief and build plan uses its fixed Markdown schema**
  (see `smolagents/agents/hardware/embedded_architect.py`'s
  `_ARCHITECT_PROCEDURE` and `smolagents/agents/hardware/kicad_specialist.py`'s
  `_KICAD_SYSTEM` for the exact headings) — a downstream reader relies on
  section names being present and in the same place every time.
- **An open risk or question is never silently resolved** just because a
  later phase produced a plan around it. embedded_architect's brief §7
  (Open Risks & Questions) and kicad_specialist's build plan §8 (Open
  Items Referred Back) are the same discipline in both directions: carry
  the item forward explicitly, or resolve it explicitly — never let it
  quietly drop.
- **kicad_specialist never invents an architecture to plan against.** No
  matching brief (or, at fab-review, no matching milestone build plans) to
  read means stop and say so — the same "never fabricate a source" rule
  the research/investment personas already follow, applied to design
  intent instead of facts.
- **Revision, not parallel documents.** A same-subject follow-up updates
  the existing brief or build plan in place (bump `Revision of` /
  `Status: revised`, note what changed) rather than writing a second,
  silently-contradictory document under a new filename.
- **`needs_clarification` on the requirements phase is success, not
  failure.** A hardware outcome is almost never fully specified up front;
  the engagement pausing to ask is the mechanism working as designed, not
  an error to suppress by guessing.
- **`fab-review` is gated in every preset except `none`, unconditionally.**
  Milestones can auto-advance because rework is cheap; fab-review cannot,
  because it precedes the real, hard-to-reverse cost of sending a design
  to a manufacturer. Don't let a `gates="all"`/`"none"` request silently
  skip this one the way it would skip a milestone gate.
- **"Planned Manufacturing Outputs" is never mistaken for finished work.**
  Until a future build phase adds real `kicad-cli` execution, every build
  plan's manufacturing-outputs section stays explicitly intent-only — the
  same "a plan dressed up as a deliverable is a failed job that looks
  finished" reasoning `manager.py`'s procedure already states for the rest
  of this stack.

## Evidence

This mirrors two things already proven out in this stack rather than a
new experiment: the Investment Assessment/Research Brief fixed-shape
pattern (`investment_agent.py`, `researcher_agent.py`) for
addressable-by-section, sight-unseen-consumable documents, and the
`DRAFT_AND_EVALUATE` reviewer scaffold (see
[thinking-before-answering.md](thinking-before-answering.md) and
`thoughts.py`) for a role whose job is characterizing and validating
someone else's artifact rather than generating its own from scratch —
exactly kicad_specialist's position relative to embedded_architect's
brief.

## Stack mapping

- `smolagents/agents/hardware/embedded_architect.py` — Embedded Design
  Brief schema and PHASE MANDATES.
- `smolagents/agents/hardware/kicad_specialist.py` — KiCad Build Plan
  schema, `DRAFT_AND_EVALUATE` scaffold.
- `smolagents/agents/jobs.py`'s hardware section — the deterministic gate/
  advancement machinery that makes `needs_clarification` and gated
  phases actually pause the engagement, rather than relying on an LLM to
  remember to stop.
- `mcp-tools/tools/hardware_domain.py` — `GATE_PRESETS` (`fab-review`
  present in every preset but `none`), the five user-driven transitions.
- `docs/hardware-agents-guide.md` — the user-facing guide to the whole
  engagement, including the deferred-tooling roadmap this doc's
  intent-only convention is bridging toward.
