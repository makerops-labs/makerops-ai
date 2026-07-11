# Source: PDDL-Instruct (arXiv:2509.13351)

Reference distillation of the paper behind this library's practice docs:
methodology, quantitative results, and limitations.

**"Teaching LLMs to Plan: Logical Chain-of-Thought Instruction Tuning for
Symbolic Planning"** — Pulkit Verma, Ngoc La, Anthony Favier, Swaroop Mishra,
Julie A. Shah (MIT CSAIL), September 2025.
<https://arxiv.org/abs/2509.13351>

Reference distillation backing the practice docs in this directory. Read this
when you need the evidence or the methodology detail; read the practice docs
when you need to act.

## Problem

LLMs are poor at symbolic planning: they fail to track action preconditions
and effects across steps, and they cannot reliably verify their own plans.
Baseline Llama-3-8B solves 28% of Blocksworld planning problems, 1% of
Mystery Blocksworld (same domain, obfuscated predicate names), 11% of
Logistics.

## Method — three phases

1. **Initial instruction tuning ("error education")**: train on planning
   problems paired with detailed solution explanations — including
   deliberately *invalid* plans annotated with why they fail: precondition
   violations, effect misapplications, frame-axiom breaches, goal failures.
2. **Logical chain-of-thought tuning with external verification** (the core):
   the model generates explicit state-action-state sequences
   ⟨s₀,a₁,s₁⟩,⟨s₁,a₂,s₂⟩,… where each step contains: state representation
   (predicates/facts), action selection with justification, precondition
   verification, effect application, state-transition computation, invariant
   preservation, goal-progress evaluation. Every chain is checked by the
   **VAL** plan validator (ground truth, not the model), and the verifier's
   feedback drives further tuning. Two-stage optimization: a reasoning-chain
   loss (state distance + weighted penalties: precondition α=1.0, effect
   α=1.0, goal α=1.5) followed by an end-task loss (invalid-plan penalty
   β=2.0 + binary cross-entropy).
3. **Evaluation** on PlanBench domains.

An iteration budget η bounds the verify-refine loop; η=15 consistently beats
η=10 (avg +4.3 points with detailed feedback).

## Key results (Llama-3-8B, detailed feedback, η=15)

| Domain | Baseline | Phase 1 only | Phase 2 only | Full |
| --- | --- | --- | --- | --- |
| Blocksworld | 28% | 78% | 72% | **94%** |
| Mystery Blocksworld | 1% | 32% | 17% | **64%** |
| Logistics | 11% | 23% | 45% | **79%** |

GPT-4 with the same treatment: 91% / 59% / 78%. Both phases are necessary —
neither alone approaches the combination.

## Findings that transfer beyond PDDL

- **External verification beats self-verification.** The gains depend on a
  ground-truth validator; the paper cites evidence that LLMs "cannot
  self-correct reasoning yet" and treats self-critique as a future-work goal,
  not a technique.
- **Detailed feedback beats binary feedback** by +5 (Blocksworld), +15
  (Mystery Blocksworld), +7 (Logistics) points: naming *which* precondition
  or effect failed outperforms a bare valid/invalid signal.
- **Explicit logical structure compensates for missing semantic priors.**
  Mystery Blocksworld obfuscates predicate names, collapsing the baseline to
  1%; explicit precondition/effect reasoning recovers it to 64%. Models lean
  heavily on what names *suggest* — spell out the semantics instead.
- **Small models close most of the gap to frontier models** when forced
  through structured logical reasoning plus an external verifier
  (8B model at 94% vs GPT-4 at 91% on Blocksworld).
- **Bounded refinement iterations** give consistent, diminishing gains —
  budget them explicitly.

## Limitations

Not 100% in any domain; restricted PDDL subset (no conditional effects or
durative actions); satisficing (not optimal) planning; performance still
degrades with domain complexity/obfuscation. Prior work (Stechly et al. 2024)
argued CoT is unsuitable for planning — this paper's counterexample requires
the full tuning + verification apparatus, not CoT prompting alone.
