"""Step 1 — build the dataset: pull SQuAD passages + their QA pairs, then
generate the SEAL-style self-edit for each passage (the base model's own
implications of the passage). Outputs to data/:

    passages.jsonl      {id, title, passage, questions: [{q, answers}]}
    implications.jsonl  {id, implications: [str, ...]}

The implications prompt follows the paper's knowledge-incorporation setup
("list implications derived from the content"); generation uses the SAME
base model that will later be finetuned — the point of SEAL is the model
learning from its own restatements.
"""

import argparse
import re

from datasets import load_dataset

from common import DATA_DIR, DEFAULT_MODEL, chat_generate, load_model, write_jsonl

IMPLICATIONS_PROMPT = """Read the following passage, then list the implications \
that can be derived from its content. Write each implication as a single \
self-contained factual statement on its own line, understandable without the \
passage. Cover every distinct fact. Do not number them or add commentary.

Passage:
{passage}"""


def pick_passages(n_passages: int, min_questions: int) -> list[dict]:
    """Distinct SQuAD validation contexts, each with its deduped questions."""
    ds = load_dataset("rajpurkar/squad", split="validation")
    by_context: dict[str, dict] = {}
    for row in ds:
        entry = by_context.setdefault(
            row["context"],
            {"title": row["title"], "passage": row["context"], "questions": []})
        if row["question"] not in {q["q"] for q in entry["questions"]}:
            entry["questions"].append(
                {"q": row["question"], "answers": row["answers"]["text"]})
    ranked = sorted(by_context.values(),
                    key=lambda e: len(e["questions"]), reverse=True)
    chosen = [e for e in ranked if len(e["questions"]) >= min_questions][:n_passages]
    for i, entry in enumerate(chosen):
        entry["id"] = f"p{i:02d}"
    return chosen


def parse_implications(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        if len(line.split()) >= 4:  # drop headers/fragments
            lines.append(line)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--passages", type=int, default=8)
    ap.add_argument("--min-questions", type=int, default=5)
    args = ap.parse_args()

    passages = pick_passages(args.passages, args.min_questions)
    write_jsonl(DATA_DIR / "passages.jsonl", passages)
    total_q = sum(len(p["questions"]) for p in passages)
    print(f"selected {len(passages)} passages, {total_q} questions")

    model, tokenizer = load_model(args.model)
    rows = []
    for p in passages:
        text = chat_generate(model, tokenizer,
                             IMPLICATIONS_PROMPT.format(passage=p["passage"]),
                             max_new_tokens=512, temperature=0.7)
        implications = parse_implications(text)
        rows.append({"id": p["id"], "implications": implications})
        print(f"{p['id']}: {len(implications)} implications")
    write_jsonl(DATA_DIR / "implications.jsonl", rows)
    print(f"wrote {DATA_DIR / 'implications.jsonl'}")


if __name__ == "__main__":
    main()
