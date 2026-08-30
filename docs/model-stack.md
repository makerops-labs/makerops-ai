# Model stack reference

Snapshot of the installed Ollama models, what each is for, and when *not*
to reach for it. Assignments follow the lead-per-domain / reviewer-diversity
convention (see the hierarchy table in [../README.md](../README.md)): the
best benchmark performer that runs acceptably on this hardware leads a
domain; same-expertise models plus one cross-lineage model (`gpt-oss:20b`,
OpenAI) review to catch the lead's blind spots. Leads switch on published
benchmark evidence, not local A/B tests; the old lead becomes a reviewer.

Hardware envelope: RTX 4070 Ti SUPER (16 GB VRAM), WSL2 capped at 24 GB
RAM. Models >16 GB partially offload to CPU — cheap for MoE models (few
active parameters), expensive for dense ones. Stop `trellis` before loading
any `qwen3.6:35b*` model (host-RAM starvation; see CLAUDE.md).

Last updated: 2026-08-28.

## Installed models

| Model | Params / arch | Quant | Disk | Max ctx | Capabilities | Strengths | Weaknesses | Best for | Avoid for |
|---|---|---|---|---|---|---|---|---|---|
| `qwen3.6:35b` | 36B MoE, 3B active | Q4_K_M | 24 GB | 256K | text, vision, tools, thinking | Fast on this hardware despite CPU offload (MoE); 73.4% SWE-bench Verified; multimodal | Below 27b on every agentic coding benchmark; needs ~10 GB host RAM (trellis gotcha) | **Coding lead** — devteam coder, Coding Assistant preset; anywhere quality + speed both matter | Structure-precise document work where 27b's dense quality wins and latency doesn't matter |
| `qwen3.6:35b-64k` | same weights, num_ctx 64000 | Q4_K_M | shares 35b blobs | 64K pinned | text, vision, tools, thinking | Same model with a context floor Ollama's 4k default would otherwise break | Same as 35b; KV cache at 64k pushes the RAM cap | **General/agents/planning lead AND default chat/dispatch** — manager, web_researcher, debate entrepreneur/monitor, most presets | Quick light queries a 9b answers in a fraction of the time |
| `qwen3.6:27b` | 27B dense | Q4_K_M | 17 GB | 256K | text, vision, tools, thinking | Best coding quality in the stack as of 2026-08-08 | Superseded by `qwen3.8:27b-64k` below (2026-08-26) — nothing references this tag anymore | — | Still on disk, unreferenced; candidate for removal |
| `qwen3.8:27b-64k` | 27B dense, num_ctx 64000 | Q4_K_M | 20 GB | 64K pinned | text, vision, tools, thinking | Successor to `qwen3.6:27b` (2026-08-26): SWE-bench Pro 61.7% (vs 53.5%), Terminal-Bench 2.1 73.0% (vs 63.4%); dense structure-precision; native multi-token prediction | Dense + CPU offload = ~7-8 tok/s generation at 64k context (measured 2026-08-28, real research-brief prompt: 1215 tokens/165s) — slower than the 3.6 generation's ~14 tok/s, likely the larger KV cache; **the bare `qwen3.8:27b` tag is unusable for any real prompt** — its reasoning burns Ollama's 4k default context before ever producing content (`done_reason` never resolves to a real answer) | **Hardware/KiCad specialist** (pinned), **coding reviewer**, **devteam engineer phases**, KiCad Specialist + Researcher-adjacent presets — unattended quality-over-latency work | Interactive chat where a human is waiting seconds, not minutes, for an answer — confirm the tradeoff is acceptable before pointing a live chat preset at it |
| `qwen3.5:9b` | 9.7B dense | Q4_K_M | 6.6 GB | 256K | text, vision, tools, thinking | Fast, cheap, still at/near top of the <15B multimodal class; former general lead | Small-model report discipline needed (narrates instead of calling final_answer — scaffolds in place) | **Vision lead** + light presets (Research Assistant, Ops Assistant, Knowledge Curator, Inventory Manager, Studio); general reviewer | Multi-file coding, long-horizon planning, anything the 35b leads exist for |
| `qwen3.5:9b-64k` | same weights, num_ctx 64000 | Q4_K_M | shares 9b blobs | 64K pinned | text, vision, tools, thinking | Context floor for long light-preset sessions | Same as 9b | Long chats/documents on the light tier | Same as 9b |
| `gpt-oss:20b` | 20.9B MoE, 3.6B active | MXFP4 | 13 GB | 128K | text, tools, thinking | Only non-Qwen lineage in the stack → decorrelated blind spots; strong reasoning; fits VRAM entirely | Fumbles smolagents' tool-calling protocol (runs as RAW persona); raw-mode tool-mention footgun (empty output); no vision; 4k default ctx truncates long work | **Cross-lineage reviewer** in both audit pools; Code Auditor + General Auditor presets | Driving ToolCallingAgents; anything needing vision; long outputs on the base tag (use -32k) |
| `gpt-oss:20b-32k` | same weights, num_ctx 32768 | MXFP4 | shares 20b blobs | 32K pinned | text, tools, thinking | Same model without the 4k-context truncation | Same as 20b | **Debate critic** (RAW persona); long artifact reviews | Same as 20b |
| `qwen3-embedding:0.6b` | 0.6B | Q8_0 | 0.6 GB | 32K | embedding | Tiny, fast, good retrieval quality | Embeddings only | **RAG** — Open WebUI knowledge/embedding model | Anything generative |

## Removed models

| Model | Removed | Why |
|---|---|---|
| `qwen3-coder:30b` | 2026-07-16 | Superseded by the qwen3.6 generation; its hardware-specialist pin and coding-reviewer slot moved to `qwen3.6:27b` (higher benchmarks, smaller disk, adds vision). Freed 18.6 GB. |
| `gemma4:12b` | 2026-07-16 | Weak agentic benchmarks (17.4% SWE-bench Verified) and documented tool refusals; its cross-lineage general-auditor role was redundant with `gpt-oss:20b`, which now holds it. Freed 7.6 GB. |
| `qwen3.6:35b-32k` | 2026-07-16 | Orphaned num_ctx derivative — referenced by no preset, env var, or doc after the general lead standardized on `-64k`. |

## Evaluated and rejected (2026-07 research pass)

- **GLM-5.2** (744B MoE) / **Kimi K2.7 Code** (1T MoE) — top open coders,
  need 300+ GB; not runnable here.
- **Llama 4 Scout** (109B total) — ~60 GB at Q4; doesn't fit.
- **Gemma 4 26B-A4B** — fast but far behind on agentic quality; same
  agent-reliability issues as its 12B sibling.
- **Laguna XS 2.1** (Poolside 33B MoE, 3B active) — credible agentic-coding
  specialist (70.9% SWE-bench Verified, interleaved thinking between tool
  calls) but scores below both qwen3.6 variants and lacks vision; revisit
  if a point release overtakes them.
- **Granite 4.1 8B / Phi-4-reasoning-vision 15B** — peers of `qwen3.5:9b`,
  not upgrades.

## Evaluated and rejected (2026-08-08 research pass)

- **Qwen3.8-Max** (2.4T MoE, ~95B active) — Alibaba's new flagship
  (announced 2026-08-03); far past any local fit.
- **Kimi K2.6** (1T MoE, 32B active) / **Kimi K3** (2.8T MoE) — Moonshot's
  latest; both need hundreds of GB even quantized.
- **DeepSeek V3.2** (671B MoE) / **V4-Flash** (284B) / **V4-Pro** (1.6T) —
  all far past the hardware envelope; R2 still unreleased.
- **GLM-5.2** (744B MoE) — still the top open-weights coder per public
  benchmarks, still the same rejected size class as the July pass.
- **GPT-OSS-120b** (117B) — needs a single 80 GB GPU; `gpt-oss:20b`
  remains the only GPT-OSS variant that fits.
- **Devstral Small 2** (24B, ~15-19 GB at Q4_K_M) — fits the VRAM envelope
  but scores 68% SWE-bench Verified, below both `qwen3.6:35b` (73.4%) and
  `qwen3.6:27b` (77.2%). No win.
- **Llama 4 Maverick** (~400B) — too big; Scout (109B) already rejected in
  the July pass.
- **Gemma 4 31B dense** — trails `qwen3.5:27b` (predecessor of the current
  leads) on SWE-bench Verified per its own release benchmarks.

**Resolved from prior pending:** **Qwen3.8-27B** — announced alongside
Max, open weights targeted for the week of 2026-08-10. Not yet published
as of the 2026-08-08 pass; see the 2026-08-26 pass below for the outcome.

## Evaluated (2026-08-26 research pass)

- **Qwen3.8-27B** (dense, shipped 2026-08-14, Apache 2.0) — **recommended
  swap for the `qwen3.6:27b` slot** (hardware/KiCad specialist + coding
  reviewer). Identical architecture and footprint to `qwen3.6:27b`
  (same 64 layers/hidden size/hybrid Gated DeltaNet+attention layout;
  Q4_K_M still ~17 GB, still needs partial CPU offload on 16 GB VRAM) —
  a drop-in, not a re-plan. Same param count, all gains from post-training:
  SWE-bench Pro 53.5→61.7, Terminal-Bench 2.1 63.4→73.0, LiveCodeBench v6
  83.9→90.3, OSWorld-Verified 63.9→84.3. Adds native multi-token
  prediction, reported at 65 tok/s decode — but every fast number found is
  full-GPU-residency on a 24 GB card; this hardware's 27B-class bottleneck
  is CPU-offload latency (measured ~14 tok/s gen on the 3.6 dense model),
  which MTP doesn't obviously fix. Treat as a same-role upgrade, not a
  fix for the "too slow to lead agentic loops" weakness. Not yet pulled —
  swap requires `ollama pull qwen3.8:27b`, then updating
  `HARDWARE_SPECIALIST_MODEL_ID`, the coding-reviewer pool, and
  `openwebui/contexts/kicad-specialist.md` per the model hierarchy doc.
- **No Qwen3.8 MoE variant exists yet.** The community is requesting a
  `35B-A3B` successor (parallel to `qwen3.6:35b`, which actually leads
  coding/general here) but Alibaba hasn't shipped one — nothing to
  evaluate against the current leads this pass.
- **"Ox Alpha"** (stealth model, topped OpenRouter/OpenCode rankings
  starting 2026-08-20) — confirmed 2026-08-26 as a Z.ai GLM-family model;
  weights promised public 2026-08-28. Decode-speed fingerprinting by the
  community suggests ~40B active / ~744B total MoE (GLM-5V-Turbo class) —
  the same size class as **GLM-5.2**, already rejected in the 2026-07 pass
  for needing 300+ GB. Open-weighting it doesn't change that arithmetic.
  Not runnable here regardless of license; confirm official card once
  published and close this out rather than re-researching from scratch.
- **Kimi K3** (2.8T MoE, shipped 2026-07-27, 76.8% SWE-bench Verified) —
  same rejected size class as **Kimi K2.7 Code**/**Kimi K2.6** from prior
  passes; still needs hundreds of GB.

## Runtime note (2026-08-28): qwen3.8:27b needs the -64k derivative

The 2026-08-26 pass recommended `qwen3.8:27b` as a same-footprint upgrade
over `qwen3.6:27b` but didn't create a context derivative (`qwen3.6:27b`
had never needed one). Pointing the Researcher openwebui preset at the
bare tag surfaced a real bug: the model reasoned internally and returned
**no content** — `qwen3.8:27b`'s reasoning is verbose enough (this stack's
system prompts routinely run several hundred tokens, before tool schemas
or conversation history) to exhaust Ollama's 4k default context before
ever emitting an answer. This is the same class of bug already fixed
elsewhere in this stack (`qwen3.6:35b`, `qwen3.5:9b`, `gpt-oss:20b` all
needed `-64k`/`-32k` derivatives for the same reason) — it just hadn't
been hit for this specific model yet.

Fix: created `qwen3.8:27b-64k` (`ollama create` with `PARAMETER num_ctx
64000`, per `docs/ai-setup-checklist.md`'s convention) and repointed
every reference to `qwen3.8:27b` across the stack to the `-64k` tag —
`HARDWARE_SPECIALIST_MODEL_ID`, `DEVTEAM_ENGINEER_MODEL_ID`,
`CODING_REVIEW_MODEL_IDS`, the KiCad Specialist preset, and the Code
Auditor doc's suggested second-copy model. Verified fixed with a
research-brief-shaped prompt via native `/api/chat`: full, correctly
formatted content, `done_reason: stop`, no truncation
(`total_duration=165s` for `eval_count=1215` tokens, ~7-8 tok/s — slower
than the 3.6 generation's ~14 tok/s, plausibly the larger 64k KV cache).
**Takeaway for future model swaps in this stack: any newly pulled model
being used for real work needs a context-derivative check before being
trusted, not just a benchmark comparison** — a bare tag silently failing
this way (no error, no timeout, just an empty answer) is worse than an
outright crash.
