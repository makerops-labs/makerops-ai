# Source: SEAL (arXiv:2506.10943)

Reference distillation of the second paper behind this library: models that
generate their own training data and improve by judging it against
downstream performance.

**"Self-Adapting Language Models"** — Adam Zweiger, Jyothish Pari, Han Guo,
Ekin Akyürek, Yoon Kim, Pulkit Agrawal (MIT), June 2025 (v2 Sep 2025).
<https://arxiv.org/abs/2506.10943>

## Problem

LLM weights are static after deployment; adapting to new knowledge or novel
tasks normally means finetuning on externally-prepared data. SEAL asks: can
the model itself decide *what* to train on and *how*?

## Method

A **self-edit** is the model's own generated adaptation directive:

- **Knowledge incorporation**: given a passage, the model generates natural-
  language *implications* — inferences, consequences, restatements — which
  become the SFT data (the passage itself is not what gets trained on).
- **Few-shot learning (ARC)**: the model emits a JSON spec choosing data
  augmentations (rotations, flips, resizing, chain reasoning) and training
  hyperparameters (learning rate 1e-4–2e-3, 1–15 epochs, loss strategy)
  from a fixed toolkit.

**Inner loop**: apply the self-edit via LoRA SFT (knowledge: r=64 α=128 on
MLP+attention, 2 epochs, lr 3e-4; ARC: r=16 for RL-phase SFT). Cheap —
~30–45 s per configuration on their hardware.

**Outer loop (RL)**: sample M self-edits per context, finetune with each,
evaluate the updated model on the downstream task, **binary reward = did
performance improve**, then reinforce only the positive-reward self-edits
(ReST-EM / filtered behavior cloning — PPO/GRPO were unstable because the
reward depends on the updated weights and isn't differentiable).

## Key results

Knowledge incorporation (SQuAD, closed-book QA after adaptation):

| Method | Single passage | Continued pretraining (n=200) |
| --- | --- | --- |
| Base model | 32.7% | 32.7% |
| Train on raw passage | 33.5% | 32.2% |
| + self-generated implications (no RL) | 39.7% | 41.0% |
| + GPT-4.1-generated synthetics | 46.3% | 39.4% |
| **SEAL (after RL)** | **47.0%** | **43.8%** |

Few-shot ARC subset: in-context learning 0%, self-edit without RL 20%,
**SEAL 72.5%**, oracle (hand-tuned config) 100%.

## Findings that transfer beyond finetuning

- **The model's own restatements beat the raw source as learning material**
  — and after RL even beat a much stronger model's (GPT-4.1) synthetic data
  in the continued-pretraining setting. What matters is the *form*: by RL
  iteration 2 self-edits converge on "easily learnable **atomic facts**" —
  small, self-contained statements — not verbosity (explicitly ablated:
  longer-prompted baselines gain less than RL-discovered structure).
- **Downstream performance is the only reward.** A self-edit is never judged
  by plausibility or fluency — only by whether the adapted model does better
  on the task. RL gains +6–11 points across every prompt format tried.
- **Catastrophic forgetting is the failure mode of sequential adaptation**:
  after 8 unconstrained sequential self-edits, accuracy on early tasks fell
  from ~80% to ~20%. No retention mechanism ships with the paper; suggested
  remedies are reward-shaping against regressions and constrained edits.
- **Autonomous adaptation-config choice works but is imperfect** (72.5% vs
  100% oracle) — self-selected strategies need constraining templates and
  toolkits, not open-ended freedom.
- **Compute asymmetry**: the inner loop (self-edit → LoRA SFT → eval) is
  cheap; the RL outer loop is not (~6 h on 2×H100 for one ReST-EM round of
  50 passages × 5 candidates × 3 seeds). A local-scale adopter can afford
  the inner loop and a *single* filtered-behavior-cloning pass, not the
  full RL.

## Limitations

Catastrophic forgetting unaddressed; RL outer loop expensive; needs paired
(context, downstream-task) labels, so it can't scale to unlabeled corpora
as-is (authors suggest self-generated eval questions as a remedy).
