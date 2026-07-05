# makerops-ai

**Private** agentic AI ecosystem layered on the public
[makerops-core](https://github.com/makerops-labs/makerops-core) stack.
Deliberately split from core (2026-07-04, public history scrubbed): the user
wants to slow AI adoption/job displacement — only well-known foundational
tools stay public. **Never move or commit this repo's content into
makerops-core**, and keep any core-side reference local-only (core's
`.git/info/exclude`, never its tracked `.gitignore`).

## Services (each a self-contained compose project, core conventions apply)

| Service | Port | Notes |
| --- | --- | --- |
| openwebui | 8080 | Chat UI. Workspace-model presets live in `openwebui/contexts/*.md` (git source of truth; recreate in UI by hand). All presets start with `contexts/_baseline.md`. |
| smolagents | 8090 | Agent workspace (Gradio). Agents in `smolagents/agents/`; code is bind-mounted — `docker restart smolagents` reloads it, rebuild only on lockfile change. |
| searxng | 8098 | Private metasearch; JSON API backs web tools. |
| mcp-tools | 8099 | FastMCP tool server; per-domain endpoints `/mcp/<domain>/`; human write-approvals at `/approvals`; doc tree at `/context` (see below). |
| speech | 8091 STT / 8093 TTS | speaches (whisper) + Kokoro, CPU-only on purpose. |

Hermes Agent is host-level (not Docker): per-project memory profiles under
`~/.hermes/profiles/` — see `docs/hermes-setup.md`; never share a profile
across projects.

## Model hierarchy (canonical table in README.md)

Lead-per-domain: best benchmark performer that fits the hardware leads;
same-expertise lower-benchmark models (plus cross-lineage `gpt-oss:20b`)
review to catch blind spots. Currently: `qwen3.6:35b` coding,
`qwen3.5:9b`/`qwen3.5:9b-64k` general+vision, `qwen3-embedding:0.6b` RAG.
Switch leads on benchmark evidence (no local A/B gate); old lead becomes a
reviewer. On a switch update: `SMOLAGENTS_*_MODEL_ID` env vars,
`openwebui/contexts/*.md` base models, README table.

## Architecture facts that cost debugging time

- **Tool docs are a progressive-disclosure tree**: `GET /context[/<domain>
  [/<tool>]]` on mcp-tools, mirrored by the `tools_help(path)` tool on every
  domain endpoint. smolagents injects the root manifest into every agent's
  instructions (`agents/context.py` → `with_baseline`; custom-agent template
  included). Long tool lists degrade local models — attach few domains,
  discover the rest via the tree.
- `tools_help` exists on EVERY domain endpoint → agents combining domains
  must merge with `agents/tools.get_domains_tools(*domains)` (dedup);
  plain concatenation crashes agent init on duplicate names.
- `docker compose restart` does NOT re-read `.env` — use
  `docker compose -p <name> up -d`. Inline comments after `=` in `.env`
  become the value.
- smolagents/mcpadapt `MCPClient` hangs forever on a 404 MCP URL —
  `agents/tools.py` pre-checks `/healthz`; keep that pattern.
- Write tools' docstrings start with `WRITE ACTION` and may return
  `PENDING APPROVAL #id` — surface it, never retry (policy in
  `mcp-tools/tools/policy.py`, tiers per user trust model).
- Open WebUI stores everything UI-side in its DB: presets, RAG embedding
  model (`qwen3-embedding:0.6b`), Audio (STT 8091 / TTS 8093), tool
  connections — the repo docs are recreate-from-git instructions
  (`docs/ai-setup-checklist.md` is the walkthrough).

## Dependencies on makerops-core (sibling checkout `../makerops-core`)

- **Ollama** (11434) serves all models; the `qwen3.5:9b-64k` derivative is
  created via Modelfile (checklist §1). **ComfyUI** (8188) backs the comfyui
  tool domain.
- **name-proxy** integration is drop-in only: copy `proxy/local-ai.conf.template`,
  `proxy/local-services.json`, `proxy/icons/ → html/local-icons/` into core
  (gitignored there); recreate proxy for route changes (`proxy/README.md`).
- Core is symlinked back at `makerops-core/ai/private` — navigation only;
  always run services from real paths.
- Core-side conventions (env files, WSL2 DNS/`network: host`, teardown
  patterns) are documented in core's `CLAUDE.md` and `docs/env-conventions.md`.

## Hardware envelope

RTX 4070 Ti SUPER 16 GB VRAM; WSL2 capped at 24 GB RAM (`.wslconfig`).
Models >16 GB (both coding models) partially offload to RAM — if a load is
OOM-killed (`signal: killed` during tensor load), free RAM or raise the cap.
Speech stays CPU-only to protect VRAM. Flash attention is on in Ollama.
