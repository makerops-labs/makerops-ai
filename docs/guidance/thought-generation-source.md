# Source: Thinking LLMs (arXiv:2410.10630)

**"Thinking LLMs: General Instruction Following with Thought Generation"** —
Tianhao Wu, Janice Lan, Weizhe Yuan, Jiantao Jiao, Jason Weston, Sainbayar
Sukhbaatar (Meta FAIR, UC Berkeley, NYU), October 2024.
<https://arxiv.org/abs/2410.10630>

Reference distillation backing [thinking-before-answering.md](thinking-before-answering.md).
Read this when you need the evidence or methodology detail; read the practice
doc when you need to act.

## Problem

Standard instruction-tuned LLMs answer directly, spending no explicit compute
on understanding the instruction, planning the response, or evaluating a draft
before committing to it. Chain-of-thought work had confined "thinking" to math
and logic; whether it helps *general* instruction following was open.

## Method — Thought Preference Optimization (TPO), three parts

1. **Thought prompting**: a system-level prompt makes the model write private
   thoughts before its answer, in a parseable format. Two templates:
   - *Generic*: "Write your thoughts after 'Here is my thought process:' and
     write your response after 'Here is my response:'" — thought content left
     free.
   - *Specific*: the thoughts must contain a **draft response and an
     evaluation of that draft** (separated by `<R>` markers) before the final
     response is written.
2. **Response-only judging**: a judge model (ArmoRM / Self-Taught Evaluator)
   scores *only the response part* — thoughts are hidden from the judge and
   the user. No thought-quality supervision exists or is needed; thoughts are
   optimized only through the responses they produce.
3. **Iterative DPO**: sample 8 thought+response pairs per instruction, build
   preference pairs from the highest/lowest-scoring responses, run 4 DPO
   iterations. Length-control normalization keeps responses from bloating, and
   format-parse failures are injected as rejected pairs.

**This stack adopts (1) and (2) at inference time only.** Part (3) is a
training loop we are not running (a future `experiments/` candidate alongside
seal-lora; see [local-finetuning-feasibility.md](local-finetuning-feasibility.md)).

## Key results (Llama-3-8B-Instruct base)

- AlpacaEval LC win rate 52.5% (+4.1 over the direct-response baseline trained
  with the same pipeline); Arena-Hard 37.3% (+4.3).
- **Gains concentrate in non-reasoning categories**: marketing, health,
  language/translation, research and general knowledge improved most —
  categories where the win comes from planning, instruction comprehension,
  and drafting, not calculation.
- Math *degrades or stays flat* (GSM8K declined; only 2.2% of the training
  corpus was math, but the direction matches other evidence that thought
  scaffolds pay off least on precise computation).
- Un-trained thought prompting alone initially *underperforms* direct answers
  — the raw model uses the thought slot badly. The lesson for inference-time
  transfer: don't just ask for "thoughts", direct their *content* (plan,
  draft, evaluate) — the specific template's structure is what survives
  without the training loop.

## Findings that transfer to this stack

- **Thoughts help general/judgment work, not arithmetic.** Apply scaffolds to
  researcher/strategist/reviewer/debater roles; leave routers, CRUD operators,
  and coding agents direct.
- **Hide the thoughts, judge the response.** Downstream consumers (a manager
  agent, the next debate turn, a report parser) must only ever see the clean
  response. Where output feeds another turn, leakage must be strippable by
  deterministic code, never by another LLM pass.
- **Draft + self-evaluation is the strongest thought content** for review-type
  tasks — it operationalizes "attack your own work before submitting it".
- **Parseable markers matter**: the paper injected format failures as negative
  examples; inference-time, the equivalent is an exact-marker convention plus
  a code-side strip backstop.

## Limitations

8B scale; judge-model dependent; the headline numbers require the DPO loop we
are not running, so inference-time gains here are expected to be smaller and
rest on the models' existing (native) thinking channels. Math/precision
regression is real — do not scaffold precise-computation roles. Thoughts cost
tokens and latency on every call.
