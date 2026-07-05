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

## Setup

The complete, ordered walkthrough is
**[docs/ai-setup-checklist.md](docs/ai-setup-checklist.md)** — work it top to
bottom; each phase is independently useful. In outline:

1. Start Ollama (in makerops-core) and pull the models from the hierarchy
   table, including the `qwen3.5:9b-64k` derivative (checklist §1).
2. Start SearXNG, then mcp-tools (note the approvals URL+token it prints),
   then Open WebUI / smolagents / speech. Each `start.sh` creates `.env`
   from `.env.example` on first run.
3. Add service API tokens to `mcp-tools/.env` one at a time (checklist §2) —
   domains without a token simply stay unmounted.
4. Do the UI-side wiring in Open WebUI (checklist §3–4): web search, tool
   connections, RAG embedding model, audio, and the workspace-model presets
   from [openwebui/contexts/](openwebui/contexts/) (git is the source of
   truth; the UI stores them in its DB).
5. Optional: name-proxy drop-ins ([proxy/README.md](proxy/README.md)) and
   Hermes ([docs/hermes-setup.md](docs/hermes-setup.md)).

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

### Using the stack day to day

- **Chat** at <http://localhost:8080> (or `openwebui.localhost`): pick a
  workspace-model preset (Research Assistant, Ops Assistant, Coding
  Assistant, …) rather than a bare model — presets carry the right system
  prompt, tool scope, and baseline context. Attach an image to any
  qwen3.5/qwen3.6 chat for vision; use the mic/speaker buttons once speech
  is wired.
- **Agents** at <http://localhost:8090> (or `agents.localhost`): give the
  manager a task; it delegates to web_researcher / coder / ops / auditor.
  Ask for a "review" or "second opinion" to trigger the multi-model audit.
- **Second opinions**: paste task + artifact into the Code Auditor or
  General Auditor preset (manual), or let the smolagents auditor consult the
  reviewer pool (automated). Reviewers are deliberately weaker,
  different-lineage models — weigh their findings, don't auto-apply.
- **Write actions** (wiki edits, stock adjustments, …) may answer
  `PENDING APPROVAL #id`: review and approve at
  <http://mcp.localhost/approvals>. Additive writes notify; destructive ones
  gate — tune per tool in `mcp-tools/.env`.

### Tool discovery (progressive disclosure)

mcp-tools publishes a documentation tree so agents (and humans) can discover
tools without carrying the whole catalog in context:

| Level | HTTP | From any agent |
| --- | --- | --- |
| Domain manifest | `GET :8099/context` | `tools_help('')` |
| One domain's tools | `GET :8099/context/<domain>` | `tools_help('<domain>')` |
| Full usage for one tool | `GET :8099/context/<domain>/<tool>` | `tools_help('<domain>/<tool>')` |

Every agent gets the root manifest as baseline context automatically:
smolagents injects it into all agents' instructions (`agents/context.py`),
Open WebUI presets start with [contexts/_baseline.md](openwebui/contexts/_baseline.md),
and Hermes profiles learn it once into persistent memory.

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

### Local integration with makerops-core

The two repos stay under one parent directory with strictly separate
version control; every cross-reference from the public repo is local-only:

- **Symlink**: `makerops-core/ai/private` → `../../makerops-ai`, excluded
  via `makerops-core/.git/info/exclude` (git's per-clone exclude file — it
  is never tracked, so the public repo carries no trace; do not use
  `.gitignore` for this, it is public). Navigation convenience only:
  **always run services from the real path** (`makerops-ai/<service>/start.sh`)
  so compose project directories stay canonical.
- **Proxy routes**: install the drop-in per [proxy/README.md](proxy/README.md).
- **One-window workflow**: open `makerops.code-workspace` in the parent
  directory (both repos as workspace folders; the symlink is excluded from
  search/watchers to avoid duplicates). A parent-level `CLAUDE.md` gives
  AI-assistant sessions the two-repo layout and the never-commit-to-core
  rule.

---

## Tips, Gotchas & Debugging

Hard-won specifics — check here before deep-diving (core-side basics like
`.env` inline comments and WSL2 DNS are in makerops-core's README):

- **`docker compose restart` does NOT re-read `.env`** — token/policy/model
  changes need `docker compose -p <project> up -d` (recreate). Code changes
  in smolagents/mcp-tools only need a restart (source is bind-mounted);
  rebuild only when `pyproject.toml`/`uv.lock` change.
- **First reply after a model switch is slow.** Only one model lives in VRAM
  at a time; swapping loads ~7–23 GB. `docker exec ollama ollama ps` shows
  what's loaded and the CPU/GPU split.
- **Large-model OOM signature**: `llama-server process has terminated:
  signal: killed` during load = not enough free system RAM for the VRAM
  overflow. Free RAM or raise the WSL2 cap (24 GB works for the current
  hierarchy on a 16 GB GPU).
- **A chat "has no tools"?** Tools attach per workspace-model, per-base-model
  (Admin Settings → Models), or per-chat (+ menu) — a bare-model thread has
  none. Old threads also bias the model toward its earlier "no tools"
  claims; test in a fresh thread. Set **Function calling: Native** for the
  qwen leads.
- **Domain missing from tools?** `curl :8099/healthz` — domains without an
  API token are skipped at startup (by design). Add the token to
  `mcp-tools/.env` and recreate.
- **MCP client hangs forever** → it's pointed at an unmounted domain (404s
  hang mcpadapt). smolagents pre-checks `/healthz` (`agents/tools.py`); keep
  that pattern in new consumers. Endpoints need the trailing slash
  (`/mcp/web/`); bare paths get a 307.
- **Agents combining several domains** must merge tools with
  `agents/tools.get_domains_tools(*domains)` — every endpoint carries
  `tools_help`, and duplicate tool names crash agent init.
- **Long tool lists degrade local models.** Attach few domains per
  agent/preset; let `tools_help` handle discovery. Prefer `/mcp/<domain>/`
  over the composed `/mcp/`.
- **Open WebUI settings live in its DB**, not in git — presets, embedding
  model, audio, connections are recreate-from-git per the checklist. Its
  web-search env vars seed the DB on first boot only.
- **Don't commit runtime state**: `.env` and `data/` are gitignored
  everywhere; committed config must not live in a `config/` dir (that glob
  is ignored).
- **Logs**: `docker compose -p <project> logs -f`; agent traces can go to an
  OTLP collector via `OTEL_EXPORTER_OTLP_ENDPOINT` (smolagents `.env`).
- **Never commit this repo's content into makerops-core** — see
  [CLAUDE.md](CLAUDE.md) and the Local integration section above.

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
