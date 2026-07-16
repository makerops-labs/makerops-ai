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

Last updated: 2026-07-16.

## Installed models

| Model | Params / arch | Quant | Disk | Max ctx | Capabilities | Strengths | Weaknesses | Best for | Avoid for |
|---|---|---|---|---|---|---|---|---|---|
| `qwen3.6:35b` | 36B MoE, 3B active | Q4_K_M | 24 GB | 256K | text, vision, tools, thinking | Fast on this hardware despite CPU offload (MoE); 73.4% SWE-bench Verified; multimodal | Below 27b on every agentic coding benchmark; needs ~10 GB host RAM (trellis gotcha) | **Coding lead** — devteam coder, Coding Assistant preset; anywhere quality + speed both matter | Structure-precise document work where 27b's dense quality wins and latency doesn't matter |
| `qwen3.6:35b-64k` | same weights, num_ctx 64000 | Q4_K_M | shares 35b blobs | 64K pinned | text, vision, tools, thinking | Same model with a context floor Ollama's 4k default would otherwise break | Same as 35b; KV cache at 64k pushes the RAM cap | **General/agents/planning lead AND default chat/dispatch** — manager, web_researcher, debate entrepreneur/monitor, most presets | Quick light queries a 9b answers in a fraction of the time |
| `qwen3.6:27b` | 27B dense | Q4_K_M | 17 GB | 256K | text, vision, tools, thinking | Best coding quality in the stack: 77.2% SWE-bench Verified, Terminal-Bench 59.3, SkillsBench +15.5 over 35b; dense structure-precision | Dense + CPU offload = ~14 tok/s generation, ~62 tok/s prefill (measured 2026-07-16); slower still at long contexts | **Hardware/KiCad specialist** (pinned), **coding reviewer**, KiCad Specialist preset — unattended quality-over-latency work | Interactive chat or agentic loops with long prompts — prefill speed makes multi-step tool use painful |
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
