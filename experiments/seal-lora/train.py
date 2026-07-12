"""Step 2 — QLoRA SFT on one data variant:

    --variant implications   the self-edit data (SEAL treatment)
    --variant passage        the raw passages (paper's control)

Hyperparameters default to the paper's knowledge-incorporation setting
(LoRA r=64 alpha=128 on attention+MLP projections, lr 3e-4, 3 epochs —
paper used 2 epochs/batch 10 at 50-passage scale; a toy set benefits from
one more pass). Training is plain causal-LM on the raw statements/passages,
matching the paper's continued-pretraining-style inner loop (no chat
template — knowledge injection, not instruction tuning).

Writes adapters/<variant>/ plus a small train-report.json (loss, runtime,
peak VRAM) for the feasibility doc.
"""

import argparse
import json
import time

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import DataLoader, Dataset

from common import ADAPTERS_DIR, DATA_DIR, DEFAULT_MODEL, load_model, read_jsonl


class TextDataset(Dataset):
    def __init__(self, texts: list[str], tokenizer, max_len: int = 512):
        self.enc = [tokenizer(t, truncation=True, max_length=max_len,
                              return_tensors="pt") for t in texts]

    def __len__(self):
        return len(self.enc)

    def __getitem__(self, i):
        ids = self.enc[i]["input_ids"][0]
        return {"input_ids": ids, "labels": ids.clone()}


def collate(batch, pad_id: int):
    max_len = max(len(b["input_ids"]) for b in batch)
    input_ids, labels, attention = [], [], []
    for b in batch:
        ids = b["input_ids"]
        pad = max_len - len(ids)
        input_ids.append(torch.cat([ids, torch.full((pad,), pad_id, dtype=ids.dtype)]))
        labels.append(torch.cat([b["labels"], torch.full((pad,), -100, dtype=ids.dtype)]))
        attention.append(torch.cat([torch.ones_like(ids), torch.zeros(pad, dtype=ids.dtype)]))
    return {"input_ids": torch.stack(input_ids), "labels": torch.stack(labels),
            "attention_mask": torch.stack(attention)}


def load_texts(variant: str) -> list[str]:
    if variant == "passage":
        return [p["passage"] for p in read_jsonl(DATA_DIR / "passages.jsonl")]
    rows = read_jsonl(DATA_DIR / "implications.jsonl")
    return [imp for r in rows for imp in r["implications"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=("implications", "passage"), required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--rank", type=int, default=64)
    ap.add_argument("--alpha", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()

    texts = load_texts(args.variant)
    print(f"variant={args.variant}: {len(texts)} training texts")

    model, tokenizer = load_model(args.model)
    model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(
        r=args.rank, lora_alpha=args.alpha, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    ds = TextDataset(texts, tokenizer)
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=True,
                    collate_fn=lambda b: collate(b, pad_id))
    optim = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad), lr=args.lr)

    torch.cuda.reset_peak_memory_stats()
    start = time.time()
    model.train()
    losses = []
    for epoch in range(args.epochs):
        for step, batch in enumerate(dl):
            batch = {k: v.to(model.device) for k, v in batch.items()}
            loss = model(**batch).loss
            loss.backward()
            optim.step()
            optim.zero_grad()
            losses.append(loss.item())
        print(f"epoch {epoch + 1}/{args.epochs} mean loss "
              f"{sum(losses[-len(dl):]) / len(dl):.4f}")

    out_dir = ADAPTERS_DIR / args.variant
    model.save_pretrained(out_dir)
    report = {
        "variant": args.variant, "model": args.model, "texts": len(texts),
        "rank": args.rank, "alpha": args.alpha, "lr": args.lr,
        "epochs": args.epochs, "final_loss": losses[-1],
        "runtime_s": round(time.time() - start, 1),
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
    }
    (out_dir / "train-report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
