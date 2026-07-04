# makerops-ai

Private AI-agent ecosystem for the MakerOps stack: chat UI, agent workspace,
tool server, private web search, speech, and persistent-memory tooling —
everything that composes the foundational inference services into an agentic
system. Runs entirely on-premise; no API keys, no data leaving the host, no
per-token costs.

This repo is deliberately **private**. The intent is to keep well-known
foundational tools public in
[makerops-core](https://github.com/makerops-labs/makerops-core) (Ollama,
ComfyUI) while not accelerating the adoption of the agentic composition
built on top of them.

## Prerequisites (from makerops-core)

These services depend on the sibling checkout of `makerops-core`:

- **Ollama** (`makerops-core/ai/ollama`, port 11434) — serves every LLM here.
  Model pulls are listed in [docs/ai-setup-checklist.md](docs/ai-setup-checklist.md).
- **ComfyUI** (`makerops-core/ai/comfyui`, port 8188) — image generation,
  driven via mcp-tools.
- **name-proxy** (`makerops-core/infrastructure/name-proxy`) — optional
  `*.localhost` names for the services here; enable with the drop-in in
  [proxy/](proxy/) (install/uninstall = copy/delete one file).
- NVIDIA Container Toolkit for the GPU services (documented in
  makerops-core's `ai/README.md`).

## Services

| Service | Port | Purpose |
| ------- | ---- | ------- |
| [Open WebUI](https://openwebui.com) | [8080](http://localhost:8080) | Chat UI — conversation history, RAG, multi-model support, voice |
| [smolagents](https://github.com/huggingface/smolagents) | [8090](http://localhost:8090) | Agent workspace — planning, research, coding, ops, and audit agents with a Gradio UI |
| [SearXNG](https://github.com/searxng/searxng) | [8098](http://localhost:8098) | Private metasearch — web-search backend for Open WebUI and mcp-tools |
| MCP Tools | [8099](http://localhost:8099/healthz) | Shared MCP tool server — read/write tools for the business stack with human write-approvals |
| [Speech](speech/) | [8091](http://localhost:8091) STT / [8093](http://localhost:8093) TTS | speaches (faster-whisper) speech-to-text + Kokoro text-to-speech, CPU-only |

There is also one host-level (non-Docker) component:
[Hermes Agent](https://hermes-agent.nousresearch.com), a terminal agent with
persistent per-project memory that runs against Ollama — see
[docs/hermes-setup.md](docs/hermes-setup.md).

### Model hierarchy

The stack follows a **lead-per-domain** convention: each expertise domain has
one lead model (the best benchmark performer that runs on this hardware), and
multi-model review uses same-expertise models with *lower* benchmark scores as
supplementary reviewers to catch the lead's blind spots. Reviewer pools
deliberately include a different lineage (gpt-oss, OpenAI) so the models don't
share training blind spots.

| Domain | Lead | Reviewers |
| --- | --- | --- |
| Coding | `qwen3.6:35b` (73.4% SWE-bench Verified) | `qwen3-coder:30b`, `gpt-oss:20b` |
| General / agents / planning | `qwen3.5:9b` (`qwen3.5:9b-64k` for agent use) | `gemma4:12b`, `gpt-oss:20b` |
| Vision understanding | `qwen3.5:9b` / `qwen3.6:35b` (both natively multimodal) | — |
| Image generation | FLUX.1 (ComfyUI, in makerops-core) | — |
| Embeddings (RAG) | `qwen3-embedding:0.6b` | — |

The review workflow is exposed two ways: the **Code Auditor / General
Auditor** presets in [openwebui/contexts/](openwebui/contexts/) (manual), and
the smolagents **auditor** agent (automated — see
[smolagents/README.md](smolagents/README.md)). When a new model release beats
a lead on domain benchmarks and fits the hardware, the old lead becomes a
reviewer candidate and configs move on: `SMOLAGENTS_*_MODEL_ID` env vars, the
context presets, and this table.

### Startup order

Ollama first (in makerops-core, with the models from the hierarchy table
pulled), then SearXNG, then mcp-tools, then Open WebUI, smolagents, and/or
speech. SearXNG, mcp-tools, and speech have no GPU dependency and are safe to
leave running continuously. The full tool-access setup (API tokens, Open
WebUI connections, context presets, approval tuning) is walked through in
[docs/ai-setup-checklist.md](docs/ai-setup-checklist.md).

Each service directory is a self-contained Docker Compose project with its
own `start.sh` / `stop.sh` / `teardown.sh` and `.env.example`, following the
makerops-core conventions (including the WSL2 DNS workaround: explicit
`dns:` servers at runtime, `network: host` for image builds).

---

## Attribution

**Open WebUI** is open-source software developed and maintained by the [Open WebUI contributors](https://github.com/open-webui/open-webui/graphs/contributors), made freely available under the [MIT License](https://github.com/open-webui/open-webui/blob/main/LICENSE).

**smolagents** is open-source software developed and maintained by [Hugging Face](https://huggingface.co) and the [smolagents contributors](https://github.com/huggingface/smolagents/graphs/contributors), made freely available under the [Apache 2.0 License](https://github.com/huggingface/smolagents/blob/main/LICENSE).

**SearXNG** is open-source software developed and maintained by the [SearXNG contributors](https://github.com/searxng/searxng/graphs/contributors), made freely available under the [AGPL-3.0 License](https://github.com/searxng/searxng/blob/master/LICENSE).

**FastMCP** (used by the mcp-tools service) is open-source software developed and maintained by the [FastMCP contributors](https://github.com/jlowin/fastmcp/graphs/contributors), made freely available under the [Apache 2.0 License](https://github.com/jlowin/fastmcp/blob/main/LICENSE).

**speaches** is open-source software developed and maintained by the [speaches contributors](https://github.com/speaches-ai/speaches/graphs/contributors), made freely available under the [MIT License](https://github.com/speaches-ai/speaches/blob/master/LICENSE).

**Kokoro-FastAPI** is open-source software developed and maintained by the [Kokoro-FastAPI contributors](https://github.com/remsky/Kokoro-FastAPI/graphs/contributors), made freely available under the [Apache 2.0 License](https://github.com/remsky/Kokoro-FastAPI/blob/master/LICENSE); the underlying [Kokoro-82M model](https://huggingface.co/hexgrad/Kokoro-82M) is released under the Apache 2.0 License.

**Hermes Agent** is open-source software developed and maintained by [Nous Research](https://nousresearch.com) and the [hermes-agent contributors](https://github.com/NousResearch/hermes-agent/graphs/contributors), made freely available under the [MIT License](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE).

---

## System Requirements

Same GPU/RAM guidance as makerops-core's `ai/README.md`: requirements scale
with the models pulled in Ollama. Models larger than VRAM (the ~19–23 GB MoE
coding leads on a 16 GB GPU) partially offload to system RAM — on WSL2, raise
the memory cap in `.wslconfig` if a large model stalls or is OOM-killed
(24 GB works for the current hierarchy on a 16 GB GPU). The speech services
are CPU-only by design.
