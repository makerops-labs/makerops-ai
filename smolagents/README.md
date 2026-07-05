# smolagents — AI Agent Workspace

smolagents is Hugging Face's minimal agent framework. This service is both a **Python workspace** for authoring your own agents and a **Docker service** that runs them behind a Gradio chat UI — all backed by the local Ollama server, so nothing leaves the host.

It ships with five starter agents (models follow the lead-per-domain hierarchy in [README.md](../README.md)):

| Agent | Model | Role |
| --- | --- | --- |
| `manager` | `qwen3.5:9b-64k` | Orchestrator served by the UI — plans tasks, prepares documents, delegates to the others |
| `web_researcher` | `qwen3.5:9b-64k` | Web search + page reading (smolagents toolkit tools) |
| `coder` | `qwen3.6:35b` | Writes and executes Python for data work and programming tasks |
| `ops` | `qwen3.5:9b-64k` | Operates the business stack via mcp-tools (wiki, inventory, projects, automation, helpdesk) |
| `auditor` | reviewer pool | Independent multi-model review of finished work (see below) |

- **Docs:** <https://huggingface.co/docs/smolagents>
- **GitHub:** <https://github.com/huggingface/smolagents>

---

## Attribution

**smolagents** is open-source software developed and maintained by [Hugging Face](https://huggingface.co) and the [smolagents contributors](https://github.com/huggingface/smolagents/graphs/contributors), made freely available under the [Apache 2.0 License](https://github.com/huggingface/smolagents/blob/main/LICENSE).

---

## Prerequisites

Ollama must be running with the lead models (and, for the auditor, the
reviewer pool) pulled before agents can run:

```bash
cd ../../makerops-core/ai/ollama && ./start.sh
docker exec ollama ollama pull qwen3.6:35b       # coding lead (~23 GB, MoE 3B active)
docker exec ollama ollama pull qwen3.5:9b        # general lead (~6.6 GB)
# 64K-context variant the agents use (Ollama's default context is too small):
printf 'FROM qwen3.5:9b\nPARAMETER num_ctx 64000\n' | docker exec -i ollama sh -c 'cat > /tmp/Modelfile && ollama create qwen3.5:9b-64k -f /tmp/Modelfile'
# Reviewer pool for the auditor:
docker exec ollama ollama pull qwen3-coder:30b   # ~19 GB
docker exec ollama ollama pull gemma4:12b        # ~7.6 GB
docker exec ollama ollama pull gpt-oss:20b       # ~13 GB
```

See [makerops-core/ai/ollama/README.md](../../makerops-core/ai/ollama/README.md) for Ollama setup and model management.

---

## Local Access

| | |
| --- | --- |
| **Web UI** | <http://localhost:8090> |
| **Via name-proxy** | <http://agents.localhost> |

---

## Setup

### Start

```bash
./start.sh
```

On first run this copies `.env.example` → `.env` (no secrets to generate), builds the image, and starts the container. Open <http://localhost:8090> and give the manager agent a task.

---

## Dev workspace

Agent code lives in [`agents/`](agents/) and is a normal uv-managed Python project — you can iterate without Docker at all:

```bash
uv sync                                                    # one-time: create .venv
OLLAMA_API_BASE=http://localhost:11434/v1 uv run python app.py
```

To add an agent, drop a `build_*_agent()` factory module in `agents/` (see `web_agent.py` for the pattern), get its LLM from `agents.model.get_model("coding" | "general")`, and wire it into `manager.py`'s `managed_agents` list.

**The container bind-mounts `agents/` and `app.py`**, so code edits only need a restart — no rebuild:

```bash
docker restart smolagents
```

Rebuild only when `pyproject.toml`/`uv.lock` change:

```bash
uv sync && ./start.sh   # start.sh always rebuilds the image
```

---

## Baseline tool awareness

Every agent's `instructions` automatically end with a **Tool environment**
section (`agents/context.py`): the root of the mcp-tools documentation tree
(`GET /context`) — one line per domain — plus guidance to drill down with the
`tools_help(path)` tool that every domain endpoint carries. Agents know what
exists across the whole stack without carrying the full tool catalog in
context, and inspect a tool's full usage doc before first use. If mcp-tools
is down at startup a static fallback is used (agents keep working).

Custom agents scaffolded by `agent_create` get the same wrapper
(`with_baseline`). Scaffolds created before this convention can be upgraded
by re-scaffolding or by hand-wrapping their `instructions=` with
`with_baseline(...)` from `..context`.

Agents that combine several domains must merge tools with
`tools.get_domains_tools(*domains)` — every domain endpoint carries
`tools_help`, and smolagents requires unique tool names per agent.

---

## Executor safety

smolagents `CodeAgent`s execute model-written Python. The stance here:

- **In the container** (normal service use): the default local executor is fine — the container is the sandbox. Code mounts are read-only, only `/data` is writable, and the only network dependency is Ollama. The Docker socket is deliberately **not** mounted.
- **On the host venv**: the agents keep a minimal `additional_authorized_imports` list (no `os`, `subprocess`, or `shutil`), and smolagents' interpreter blocks unauthorized imports. For untrusted or long-autonomy runs from the host, pass `executor_type="docker"` to `CodeAgent` so generated code runs in a throwaway container instead.

---

## MCP tools (mcp-tools)

Agents load their tools from the shared MCP tool server
([mcp-tools](../mcp-tools/)) when it is running:

- **web_researcher** uses the `web` domain (SearXNG-backed `web_search` +
  content-type-aware `fetch_url`) and falls back to the stock DuckDuckGo
  tools when the server is down.
- **ops** (new) operates the business stack: Outline, InvenTree, Plane, n8n,
  FreeScout, trigger.dev, ComfyUI, draw.io. Only domains with an API token
  configured on mcp-tools contribute tools; the rest are skipped with a log
  line. Write tools follow the human approval policy described in the
  [mcp-tools README](../mcp-tools/README.md) — a gated write returns
  `PENDING APPROVAL #id` and the ops agent reports it instead of retrying.
- **manager** holds the `agents` domain (`agent_create`, `agent_list`,
  `agent_read`) so it can scaffold new specialist agents.

### Multi-model review (auditor)

The `auditor` agent implements the reviewer-pool convention: the lead model
of a domain produces work, and same-expertise models with lower benchmark
scores review it to catch the lead's blind spots — including `gpt-oss:20b`,
whose different lineage (OpenAI vs Qwen/Gemma) decorrelates the review.
Ask the manager for a "review" or "second opinion" on an artifact and it
delegates to the auditor, which queries each model in the domain's pool
sequentially (Ollama swaps one model in VRAM at a time) and merges the
findings into one severity-ordered report. Pools are configured via
`SMOLAGENTS_CODING_REVIEW_MODEL_IDS` / `SMOLAGENTS_GENERAL_REVIEW_MODEL_IDS`
in `.env`.

### Custom agents

`agent_create` (callable from any MCP client, including the manager itself)
scaffolds a new agent module into `agents/custom/<name>.py` from a fixed
template — review it with `git diff`, edit it by hand freely. The manager
auto-discovers every `build_*_agent()` in that package at startup:

```bash
docker compose -p smolagents restart   # pick up new custom agents
```

A custom module that fails to import is skipped with a log line, never fatal.

---

## Files

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Single-container stack definition (built from `Dockerfile`) |
| `Dockerfile` | Bakes the uv-managed dependency set; code is bind-mounted over it |
| `pyproject.toml` / `uv.lock` | Python project — smolagents with toolkit/openai/mcp/telemetry/gradio extras |
| `agents/` | Agent package: config, model factory, telemetry, and the three starter agents |
| `app.py` | Gradio UI entry point (serves the manager agent on port 7860) |
| `.env.example` | Configuration template |
| `start.sh` | Build image and start |
| `stop.sh` | Stop (data preserved) |
| `teardown.sh` | Full wipe with confirmation |

---

## Architecture

```text
Browser
  └─► localhost:8090  (TCP) → Gradio UI
          └─► smolagents  (built from ./Dockerfile)
                ├─► manager agent  (qwen3.5:9b-64k — + agent scaffolding tools)
                │     ├─► web_researcher  (qwen3.5:9b-64k — web search + page reading)
                │     ├─► coder  (qwen3.6:35b — sandboxed Python execution)
                │     ├─► ops  (qwen3.5:9b-64k — wiki/inventory/projects/automation/helpdesk)
                │     ├─► auditor  (reviewer pool — multi-model second opinions)
                │     └─► agents/custom/*  (auto-discovered custom agents)
                ├─► host.docker.internal:11434/v1  → Ollama OpenAI-compatible API
                ├─► host.docker.internal:8099/mcp/<domain>/  → mcp-tools (tool server)
                └─► ./data/smolagents  → /data  (agent outputs, uploads)
```

---

## Cheat Sheet

### Logs

```bash
docker compose -p smolagents logs -f
```

### Change models

Edit `SMOLAGENTS_CODING_MODEL_ID` / `SMOLAGENTS_GENERAL_MODEL_ID` in `.env` (pull the new model in Ollama first), then:

```bash
./stop.sh && ./start.sh
```

### Run an agent one-off from the host

```bash
OLLAMA_API_BASE=http://localhost:11434/v1 uv run python -c \
  "from agents import build_manager_agent; print(build_manager_agent().run('your task here'))"
```

### Enable telemetry

Point `OTEL_EXPORTER_OTLP_ENDPOINT` in `.env` at an OTLP HTTP collector (e.g. a local [Arize Phoenix](https://github.com/Arize-ai/phoenix) instance) and restart — agent runs will be traced automatically.
