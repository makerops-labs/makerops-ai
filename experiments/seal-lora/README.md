# seal-lora — minimal self-edit finetuning prototype

Proof of concept for the **inner loop** of SEAL (arXiv:2506.10943, distilled
in [../../docs/guidance/seal-source.md](../../docs/guidance/seal-source.md)):

> self-edit (the model generates implications of new passages) → QLoRA SFT
> on those implications → closed-book eval before/after.

**Deliberately out of scope**: SEAL's RL outer loop (ReST-EM over many
self-edit candidates — ~6 h on 2×H100 per round in the paper). This is a
single round, one self-edit per passage, plus a **raw-passage control
adapter** to reproduce the paper's core contrast (implications > raw
passage) at toy scale. Expect noisy small-sample numbers; the point is that
the loop runs on this hardware and the machinery is real, not the absolute
scores. See [../../docs/model-development-playbook.md](../../docs/model-development-playbook.md)
for where this goes next.

## Layout

| File | Role |
| --- | --- |
| `selfedit.py` | Pull N SQuAD passages+QA, generate implications with the base model → `data/` |
| `train.py` | QLoRA SFT — `--variant implications` or `--variant passage` → `adapters/<variant>/` |
| `eval.py` | Closed-book QA (no passage in context) for base / both adapters → EM + F1 table |

Everything is configurable via flags; defaults mirror the paper's knowledge-
incorporation setting where practical (LoRA r=64 α=128, lr 3e-4, ~2–3
epochs) on a small base model (`Qwen/Qwen2.5-1.5B-Instruct`).

## Run

```bash
cd experiments/seal-lora
uv venv && uv pip install -e .        # or: pip install -e . in any venv
# GPU discipline (16 GB card shared with the serving stack):
#   trellis/stop.sh if running; ollama ps → ollama stop <model> for anything
#   resident; nvidia-smi should show close to 0 MiB used before training.
python selfedit.py                    # ~minutes: downloads model + SQuAD slice
python train.py --variant implications
python train.py --variant passage     # control
python eval.py                        # prints the before/after table
```

Artifacts (`data/`, `adapters/`, `results/`) are git-ignored; the scripts
and this README are the versioned part.

## Honest-reporting rules

- `eval.py` prints all three columns (base, passage-control, implications)
  with question counts — never quote the treatment number without the
  control next to it.
- At this scale (default 8 passages, ~40 questions) a few points of EM/F1
  is noise. Directional agreement with the paper is a success; silence or
  inversion is a finding to record, not to hide.
- Record measured runtime + peak VRAM in
  [../../docs/guidance/local-finetuning-feasibility.md](../../docs/guidance/local-finetuning-feasibility.md)
  after each meaningful run.
