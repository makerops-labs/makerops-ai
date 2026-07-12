"""Step 3 — closed-book QA eval: ask every passage's questions WITHOUT the
passage in context, for each condition:

    base            the untouched base model
    passage         base + raw-passage control adapter
    implications    base + self-edit (implications) adapter

Prints an EM/F1 table and writes results/eval.json. Honest-reporting rule:
all conditions always shown together; the treatment number means nothing
without the base and control beside it.
"""

import argparse
import json

from peft import PeftModel

from common import (ADAPTERS_DIR, DATA_DIR, DEFAULT_MODEL, RESULTS_DIR,
                    chat_generate, exact_match, f1, load_model, read_jsonl)

QA_PROMPT = ("Answer the question with the shortest possible factual answer "
             "(a name, date, number, or phrase). No explanation.\n"
             "Question: {question}")


def score_condition(model, tokenizer, passages: list[dict]) -> dict:
    em_scores, f1_scores = [], []
    for p in passages:
        for q in p["questions"]:
            pred = chat_generate(model, tokenizer,
                                 QA_PROMPT.format(question=q["q"]),
                                 max_new_tokens=32, temperature=0.0)
            pred = pred.strip().splitlines()[0] if pred.strip() else ""
            em_scores.append(exact_match(pred, q["answers"]))
            f1_scores.append(f1(pred, q["answers"]))
    n = len(em_scores)
    return {"n": n, "em": round(100 * sum(em_scores) / n, 1),
            "f1": round(100 * sum(f1_scores) / n, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    passages = read_jsonl(DATA_DIR / "passages.jsonl")
    results: dict[str, dict] = {}

    model, tokenizer = load_model(args.model)
    results["base"] = score_condition(model, tokenizer, passages)
    print(f"base: {results['base']}")

    for variant in ("passage", "implications"):
        adapter_dir = ADAPTERS_DIR / variant
        if not adapter_dir.is_dir():
            print(f"({variant}: no adapter at {adapter_dir}, skipping)")
            continue
        adapted = PeftModel.from_pretrained(model, adapter_dir)
        results[variant] = score_condition(adapted, tokenizer, passages)
        print(f"{variant}: {results[variant]}")
        adapted = adapted.unload()  # strip adapter, back to clean base

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "eval.json").write_text(json.dumps(results, indent=1))

    print("\n| condition | n | EM | F1 |\n| --- | --- | --- | --- |")
    for name, r in results.items():
        print(f"| {name} | {r['n']} | {r['em']} | {r['f1']} |")
    print(f"\nwrote {RESULTS_DIR / 'eval.json'}")


if __name__ == "__main__":
    main()
