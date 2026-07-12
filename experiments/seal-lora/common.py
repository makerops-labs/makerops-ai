"""Shared bits: model loading, paths, SQuAD answer normalization/scoring."""

import json
import re
import string
from collections import Counter
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
ADAPTERS_DIR = HERE / "adapters"
RESULTS_DIR = HERE / "results"

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def bnb_config() -> BitsAndBytesConfig:
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )


def load_model(model_id: str = DEFAULT_MODEL, quantized: bool = True):
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config() if quantized else None,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    return model, tokenizer


def chat_generate(model, tokenizer, user_msg: str, max_new_tokens: int = 512,
                  temperature: float = 0.7) -> str:
    messages = [{"role": "user", "content": user_msg}]
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt",
        return_dict=True,
    ).to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else None,
            pad_token_id=tokenizer.eos_token_id,
        )
    prompt_len = inputs["input_ids"].shape[1]
    return tokenizer.decode(out[0][prompt_len:], skip_special_tokens=True)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


# ── SQuAD-style scoring (standard normalization: lowercase, strip articles,
# punctuation, extra whitespace) ─────────────────────────────────────────────

def _normalize(text: str) -> str:
    text = text.lower()
    text = "".join(ch for ch in text if ch not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def exact_match(prediction: str, gold_answers: list[str]) -> float:
    pred = _normalize(prediction)
    return float(any(pred == _normalize(g) for g in gold_answers))


def f1(prediction: str, gold_answers: list[str]) -> float:
    pred_tokens = _normalize(prediction).split()
    best = 0.0
    for gold in gold_answers:
        gold_tokens = _normalize(gold).split()
        common = Counter(pred_tokens) & Counter(gold_tokens)
        overlap = sum(common.values())
        if overlap == 0:
            continue
        precision = overlap / len(pred_tokens)
        recall = overlap / len(gold_tokens)
        best = max(best, 2 * precision * recall / (precision + recall))
    return best
