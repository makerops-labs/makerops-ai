# openwebui — LLM Chat Interface

Open WebUI is a self-hosted, ChatGPT-style interface for interacting with local language models served by Ollama. It provides conversation history, user accounts, multi-model switching, RAG (retrieval-augmented generation) over uploaded documents, and a built-in prompt library — all running entirely on-premise.

- **Home page / docs:** <https://openwebui.com>
- **GitHub:** <https://github.com/open-webui/open-webui>
- **Docker image:** `ghcr.io/open-webui/open-webui`

---

## Attribution

**Open WebUI** is open-source software developed and maintained by the [Open WebUI contributors](https://github.com/open-webui/open-webui/graphs/contributors), made freely available under the [MIT License](https://github.com/open-webui/open-webui/blob/main/LICENSE).

---

## Prerequisites

Ollama must be running before starting Open WebUI. Open WebUI connects to Ollama at `http://host.docker.internal:11434` by default — this resolves to the host machine from inside the container.

See [makerops-core/ai/ollama/README.md](../../makerops-core/ai/ollama/README.md) for Ollama setup and model management instructions.

---

## Local Access

| | |
| --- | --- |
| **Web UI** | <http://localhost:8080> |

---

## Setup

### Before first start

No configuration is required. On first run, `start.sh` will:

1. Copy `.env.example` → `.env`
2. Generate a `WEBUI_SECRET_KEY` for session signing
3. Pull the latest image and start the container

### Start

```bash
./start.sh
```

### First run

On your first visit to `http://localhost:8080`, Open WebUI will prompt you to create an admin account. The first account registered automatically receives admin privileges.

After signing in, verify the Ollama connection under **Settings → Connections** — the Ollama URL should show `http://host.docker.internal:11434` and report a successful connection. Any models already pulled in Ollama will appear in the model selector.

---

## Web search (via searxng)

`.env.example` enables web search backed by the local SearXNG instance
([searxng](../searxng/)) out of the box:

```text
ENABLE_WEB_SEARCH=true
WEB_SEARCH_ENGINE=searxng
SEARXNG_QUERY_URL=http://host.docker.internal:8098/search?q=<query>&format=json
```

Start `searxng` before using it. In a chat, toggle **Web Search** (the
globe icon under the message box) and ask something current — answers arrive
with source citations.

**PersistentConfig caveat:** Open WebUI copies these variables into its
database on **first boot only**. If your instance predates them, either set
them once in **Admin Settings → Web Search** (engine: `searxng`, query URL as
above), or add `ENABLE_PERSISTENT_CONFIG=false` to `.env` to make the
environment authoritative on every boot.

---

## Tools (via mcp-tools)

The shared MCP tool server ([mcp-tools](../mcp-tools/)) gives models
read/write access to the stack (Outline, InvenTree, Plane, n8n, ComfyUI,
FreeScout, draw.io, trigger.dev) plus `web_search`/`fetch_url`. Writes go
through the human approval policy described in its README.

To connect (Open WebUI ships native MCP streamable-HTTP support):

1. Start `mcp-tools` (and `searxng`).
2. **Admin Settings → External Tools → Add Connection**, type **MCP
   (Streamable HTTP)**, URL `http://host.docker.internal:8099/mcp/` — or a
   per-domain endpoint like `http://host.docker.internal:8099/mcp/web/` for a
   smaller tool list (recommended for local models generally; see the
   [context presets](contexts/README.md)).
3. Enable the tool server per-model (Workspace → Models → edit → Tools) or
   per-chat (the **+** integrations menu).
4. For tool-capable models (e.g. `qwen3.5:9b`, `qwen3.6:35b`), set
   **Function calling: Native** in the model's Advanced Params for reliable
   tool use.

> A model's **default tools** (set in Workspace → Models → Tools) only reach
> the model in stock Open WebUI (through 0.13.3) when you switch models *inside the
> chat* — a preset chat opened directly, or a cloned/continued thread, runs
> with no tools. The `patches/merge-model-toolids.py` runtime patch (applied
> by `start.sh`) fixes this by mirroring how Open WebUI already handles a
> model's default skills. See [patches/README.md](patches/README.md).

If your Open WebUI build predates native MCP support, run
[mcpo](https://github.com/open-webui/mcpo) in front of mcp-tools and add it as
an OpenAPI tool server instead.

---

## RAG embeddings (via Ollama)

Document uploads (RAG) need an embedding model. This is UI-side config —
Open WebUI stores it in its database, so recreate it from here after a
reset:

1. Pull the model once: `docker exec ollama ollama pull qwen3-embedding:0.6b`.
2. **Admin Settings → Documents** → Embedding Model Engine `Ollama`, URL
   `http://host.docker.internal:11434`, embedding model
   `qwen3-embedding:0.6b`.
3. Test: upload a document in a chat and ask something answerable only from
   it.

Changing the embedding model later requires re-indexing documents already
uploaded (Admin Settings → Documents → Reindex).

---

## Voice (via speech)

The [speech](../speech/) service provides OpenAI-compatible
speech-to-text (speaches / faster-whisper) and text-to-speech (Kokoro).
Also UI-side config, recreate from here:

1. Start it: `speech/start.sh`.
2. **Admin Settings → Audio**:
   - **Speech-to-Text**: engine `OpenAI`, URL
     `http://host.docker.internal:8091/v1`, key `no-key`, model
     `Systran/faster-whisper-small`.
   - **Text-to-Speech**: engine `OpenAI`, URL
     `http://host.docker.internal:8093/v1`, key `no-key`, voice `af_heart`.
3. Test: microphone button in a chat for STT; speaker icon on a reply for
   TTS.

---

## Scripts

### `./start.sh`

Creates `.env` from `.env.example` if missing, generates secrets, pulls the latest image, and starts the container.

```bash
./start.sh
```

### `./stop.sh`

Stops the container. All data (accounts, chat history, RAG documents) in the volume is preserved.

```bash
./stop.sh
```

Pass `--volumes` to also remove the data volume (destructive):

```bash
./stop.sh --volumes
```

### `./teardown.sh`

Interactive full teardown: shows what will be removed, prompts for confirmation, then deletes the container, volume, image, and network. **All user accounts and chat history will be deleted.**

```bash
./teardown.sh
```

---

## Files

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Single-container stack definition |
| `.env.example` | Configuration template |
| `start.sh` | Generate secrets, pull image, start, and apply `patches/` |
| `stop.sh` | Stop (volume preserved) |
| `teardown.sh` | Full wipe with confirmation |
| `patches/` | In-place source patches to the upstream image (re-applied on every `start.sh`; lost on image recreate). See [patches/README.md](patches/README.md). |

---

## Architecture

```text
Browser / API clients
  └─► localhost:8080  (TCP) → Open WebUI
          └─► openwebui  (ghcr.io/open-webui/open-webui:v0.13.3)
                ├─► host.docker.internal:11434  → Ollama REST API
                └─► openwebui data volume  (/app/backend/data)
                      ├─► SQLite database  (users, chats, settings)
                      └─► RAG document store
```

---

## Cheat Sheet

### Logs

```bash
docker compose -p openwebui logs -f
docker logs openwebui -f
```

### Shell access

```bash
docker exec -it openwebui bash
```

### Upgrade

The image is pinned to a `vX.Y.Z` tag in `docker-compose.yml` (the 0.11.x line
has shipped migration regressions, so upgrades are deliberate). To upgrade:

```bash
# 1. bump the `image:` tag in docker-compose.yml to the new release
# 2. back up the DB (root-owned; do it through a container):
docker run --rm -v "$PWD/data/openwebui:/d" alpine \
  cp /d/webui.db /d/webui.db.bak-$(date +%Y%m%d)
# 3.
./stop.sh && ./start.sh
```

Then check `docker logs openwebui` for Alembic migration errors and confirm
`curl -s localhost:8080/api/version`. Data in the volume is preserved across
upgrades. `start.sh` re-applies the `patches/` after the pull; if you upgrade
by hand, run `patches/apply.sh` yourself (or presets lose their tools — see
[patches/README.md](patches/README.md)). On a bad upgrade, restore the DB
backup and revert the tag.

### Reset admin password

If you are locked out, reset the admin account via the Open WebUI CLI:

```bash
docker exec -it openwebui bash
open-webui admin reset-password --email <your-email>
```

### Connect a different Ollama instance

Update `OLLAMA_BASE_URL` in `.env` to point to any Ollama-compatible endpoint, then restart:

```bash
./stop.sh && ./start.sh
```

### Connect to an OpenAI-compatible API

Open WebUI supports any OpenAI-compatible backend. Add the endpoint under **Settings → Connections → OpenAI API** in the web UI — no `.env` change required.
