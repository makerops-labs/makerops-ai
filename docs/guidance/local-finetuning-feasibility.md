# Local fine-tuning feasibility

What actually trains on this stack's hardware — an RTX 4070 Ti SUPER
(16 GB VRAM) under WSL2 with a 24 GB RAM cap, shared with the serving stack
(Ollama, ComfyUI, TRELLIS). Written 2026-07-11 alongside the SEAL
distillation ([seal-source.md](seal-source.md)); the working proof is
[../../experiments/seal-lora/](../../experiments/seal-lora/), and the
roadmap that consumes this assessment is
[../model-development-playbook.md](../model-development-playbook.md).

## Method tiers

| Tier | What | Fits here? |
| --- | --- | --- |
| QLoRA (4-bit base + LoRA) | The workhorse. Base frozen in NF4, adapters in bf16. | Yes — primary path |
| LoRA (bf16 base) | Higher fidelity, ~4× the base memory. | Only ≤3B class |
| Full fine-tune | All weights + optimizer states. | Only ≤1B; rarely worth it |

## Model-size envelope (QLoRA, ~2k ctx, small batch)

| Base size | Peak VRAM (approx) | Verdict |
| --- | --- | --- |
| 0.5–3B | 3–8 GB | Trivial; trains alongside an idle desktop |
| 7–9B | 10–13 GB | Comfortable; the sweet spot for specialization |
| 14B | ~15–16 GB | Possible (unsloth demonstrates 14B on a 16 GB T4) but zero headroom — short ctx, batch 1 |
| 30B-A3B MoE | ~17.5 GB (unsloth) | Marginal — over this card's 16 GB; no |
| 32B+ dense | >20 GB | No |

Host RAM (24 GB WSL2 cap) is the second constraint: tokenizer + dataset +
CPU-offloaded states for a 14B run compete with everything else running —
same class of pressure as the qwen3.6:35b serving loads.

**Lineage caveat**: unsloth explicitly recommends **against QLoRA (4-bit)
training on Qwen3.5 models** (dense or MoE — higher-than-normal
quantization deltas). For QLoRA use Qwen3 / Qwen2.5 lineage bases; for a
Qwen3.5 base, use bf16 LoRA and stay small (≤3B class here).

## Toolchain

- **unsloth** — fastest option (claims 2× speed, ~70% less VRAM), directly
  supports Qwen lineage + GGUF export. Install churns (forced reinstalls,
  torch pinning) — try first, don't fight it long.
- **transformers + PEFT + bitsandbytes** — the boring fallback that always
  works; it's what `experiments/seal-lora/` uses (plain HF stack, zero
  exotic deps). Add TRL's SFTTrainer when datasets get real.
- **WSL2 notes**: CUDA-in-WSL already proven here (Ollama, TRELLIS);
  bitsandbytes ships CUDA wheels that work under WSL2. The stack's broken
  bridge-DNS gotcha applies to *docker builds*, not host venvs — train in a
  host venv (uv), not a container.

## Serving the result (→ Ollama)

Two paths, both ending in an Ollama Modelfile — same flow as the existing
`qwen3.5:9b-64k` derivative (checklist §1):

1. **Adapter-only** (preferred while iterating): keep the LoRA separate,
   convert with llama.cpp's `convert_lora_to_gguf.py` (or let Ollama import
   the safetensors adapter directly) → `FROM <base>` + `ADAPTER <path>` →
   `ollama create <name>`. Swapping specializations = swapping adapters;
   the base stays untouched (forgetting mitigation, playbook §5).
2. **Merged**: merge adapter into base → `convert_hf_to_gguf.py` → quantize
   (Q4_K_M to match the stack's serving quants) → `FROM ./model.gguf`.
   Do this only for a promoted, benchmark-validated model.

## What SEAL-style adaptation costs locally

- **Inner loop** (self-edit → QLoRA SFT → eval): minutes for ≤3B models at
  toy scale — measured numbers below. This is the affordable unit.
- **Single filtered-BC round** (generate k candidates per held-out brief,
  keep verified winners, SFT once — the playbook's stand-in for ReST-EM):
  hours-to-overnight for a 7–9B base on hundreds of samples. Feasible as an
  occasional, deliberate run — not a continuous loop.
- **Full SEAL RL outer loop** (multi-round ReST-EM): ~6 h on 2×H100 per
  round in the paper. **Out of reach locally**; do not attempt.

## GPU/RAM discipline for training runs

Stop `trellis` (holds ~5.4 GB host RAM while merely up); let Ollama models
idle-unload or `ollama stop <model>` explicitly; `nvidia-smi` should show
~0 MiB before a run. Training and the 35B serving loads cannot coexist.
Serving resumes cleanly afterwards — Ollama reloads on next request.

## Go / no-go by use case

| Use case | Verdict | Why |
| --- | --- | --- |
| Report-discipline adapter for the 9B general lead | **GO** (playbook M2) | QLoRA on 9B fits; failure examples already logged in job history |
| Software-operation adapter, 3–8B base | **GO** (playbook M3) | Sweet-spot sizes; traces + external verifiers exist |
| Replacing the 35B coding lead with a self-trained model | **NO-GO** | Can't train at that size here; rent GPU or wait |
| SEAL-style wiki internalization (knowledge in weights) | **GO but low value** | Loop works (prototype), but RAG already serves this cheaper; revisit if RAG retrieval becomes the bottleneck |
| Continuous online self-adaptation | **NO-GO** | RL outer loop unaffordable; forgetting unmanaged — use the document-memory practices ([knowledge-distillation.md](knowledge-distillation.md)) instead |

## Measured locally (experiments/seal-lora)

**2026-07-11, first run** — Qwen2.5-1.5B-Instruct (NF4 4-bit), LoRA r=64
α=128 lr 3e-4, 3 epochs; 8 SQuAD passages / 185 questions; implications
generated by the same base model (74 statements).

| Step | Runtime | Peak VRAM |
| --- | --- | --- |
| Self-edit generation (74 implications) | ~2 min | ~2.5 GiB |
| QLoRA SFT, implications variant | **9.8 s** | 2.95 GiB |
| QLoRA SFT, raw-passage control | 3.4 s | 7.18 GiB (longer sequences) |
| Closed-book eval, 185 q × 3 conditions | ~8 min | ~3 GiB |

Closed-book QA (EM / F1): base **8.6 / 13.9** → raw-passage control
**15.7 / 22.4** → implications **9.7 / 17.1**.

Interpretation (honest): knowledge incorporation via QLoRA plainly works —
both adapters beat base after seconds of training. But the paper's
implications-beat-raw-passage contrast **inverted** at this scale: a 1.5B
model's untrained implications are weak (SEAL's no-RL implications number
came from a 7B generator, and even there the no-RL gain was modest — RL is
what made self-edits win, 20%→72.5% on ARC). Also, SQuAD answers are often
verbatim passage spans, which memorizing the raw passage serves directly.
Consequences for the playbook: self-edit *generation quality is the
bottleneck* — use the strongest available model (the 35B lead via Ollama)
to generate training data for a small student, and expect filtered
selection (keep only edits that verifiably help) to matter more than the
edit format itself. The hardware verdicts above are confirmed: the inner
loop costs seconds-to-minutes at small scale, exactly as budgeted.

## Sources

- [Unsloth: Qwen3 how to run & fine-tune](https://unsloth.ai/docs/models/tutorials/qwen3-how-to-run-and-fine-tune)
- [Unsloth: Qwen3.5 fine-tuning guide](https://unsloth.ai/docs/models/qwen3.5/fine-tune) (QLoRA-not-recommended caveat)
- [Ollama: importing models / ADAPTER](https://docs.ollama.com/import)
- [llama.cpp convert_lora_to_gguf.py](https://github.com/ggml-org/llama.cpp/blob/master/convert_lora_to_gguf.py)
- SEAL paper compute figures: [seal-source.md](seal-source.md)
