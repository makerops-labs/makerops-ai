# AI Tool-Access Setup Checklist

Everything you (the human) need to do to give the local LLMs access to the
stack's services, internet search, and the WAN. Work top to bottom; each
phase is independently useful, so you can stop at any point and come back.

## 1. Start the AI core

- [ ] Start Ollama and pull the models (leads + reviewer pool + embeddings —
      see the model hierarchy table in [README.md](../README.md)):

  ```bash
  ../makerops-core/ai/ollama/start.sh
  # Leads
  docker exec ollama ollama pull qwen3.6:35b          # coding (~23 GB)
  docker exec ollama ollama pull qwen3.5:9b           # general + vision (~6.6 GB)
  # 64K-context variant used by agents and Hermes
  printf 'FROM qwen3.5:9b\nPARAMETER num_ctx 64000\n' | \
    docker exec -i ollama sh -c 'cat > /tmp/Modelfile && ollama create qwen3.5:9b-64k -f /tmp/Modelfile'
  # Reviewer pool (multi-model audit)
  docker exec ollama ollama pull qwen3-coder:30b      # ~19 GB
  docker exec ollama ollama pull gemma4:12b           # ~7.6 GB
  docker exec ollama ollama pull gpt-oss:20b          # ~13 GB
  # Embeddings for Open WebUI RAG
  docker exec ollama ollama pull qwen3-embedding:0.6b
  ```

- [ ] Start SearXNG: `searxng/start.sh`, then confirm
      `curl -s 'http://localhost:8098/search?q=test&format=json' | jq '.results[0].title'`
      returns a result.
- [ ] Start the tool server: `mcp-tools/start.sh`. Note the **approvals
      URL with token** it prints — open it once per browser (it sets a
      cookie). Check `curl -s http://localhost:8099/healthz | jq` — only
      `web`, `approvals`, `comfyui`, `drawio`, `agents` mount until you add
      tokens below.
- [ ] Enable the private AI routes on makerops-core's reverse proxy so
      `search.localhost` and `mcp.localhost` resolve: install the drop-in
      template per [proxy/README.md](../proxy/README.md). (The public
      landing page at `root.localhost` does not list the private services.)

## 2. Service API tokens → `mcp-tools/.env`

For each service you want the LLMs to reach, create a token in its UI, paste
it into `mcp-tools/.env`, then recreate the container so it re-reads the
env file (`cd mcp-tools && docker compose -p mcp-tools up -d` — a plain
`restart` does **not** apply `.env` changes) and re-check `/healthz` (the
domain should appear in `domains`).

- [ ] **Outline** — Settings → **API & Apps** → New API key →
      `OUTLINE_API_TOKEN`. If your Outline runs on a port other than 3001,
      also fix `OUTLINE_URL`.
- [ ] **InvenTree** — user menu (top right) → Settings → **Security** →
      API Tokens → Add → `INVENTREE_API_TOKEN`.
- [ ] **Plane** — avatar → Profile Settings → **API tokens** → Add →
      `PLANE_API_KEY`. Also set `PLANE_WORKSPACE_SLUG` (the first path
      segment of your workspace URL, e.g. `http://localhost:8100/<slug>/`).
      Verify: `curl -s -H "X-API-Key: $KEY" http://localhost:8100/api/v1/workspaces/<slug>/projects/ | jq`.
- [ ] **n8n** — Settings → **n8n API** → Create an API key → `N8N_API_KEY`.
- [ ] **trigger.dev** — project → **API Keys** → secret key (`tr_...`) →
      `TRIGGERDEV_SECRET_KEY`.
- [ ] **FreeScout** (optional, paid) — install the
      [API & Webhooks module](https://freescout.net/module/api-webhooks/)
      (~$19 one-time), then Manage → API & Webhooks → generate key →
      `FREESCOUT_API_KEY`. Skip this and the domain simply stays unmounted.
- [ ] **ComfyUI** (optional) — no token, but if you want a specific model
      checkpoint used for `comfyui_generate_image`, set `COMFYUI_CHECKPOINT`
      (otherwise the first available checkpoint is used).

## 3. Open WebUI

- [ ] Start it: `openwebui/start.sh` (create the admin account on first
      visit).
- [ ] **If your instance existed before this setup**, the new web-search
      env vars won't apply (they seed the DB on first boot only). Set them
      in **Admin Settings → Web Search**: enable, engine `searxng`, query URL
      `http://host.docker.internal:8098/search?q=<query>&format=json`.
- [ ] Test: toggle the web-search globe in a chat and ask something current —
      citations should appear.
- [ ] Connect the tool server: **Admin Settings → External Tools → Add
      Connection** → type **MCP (Streamable HTTP)** → URL
      `http://host.docker.internal:8099/mcp/` (all tools) and/or per-domain
      URLs like `.../mcp/web/`, `.../mcp/outline/` (smaller lists — better
      for gemma-class models).
- [ ] Test: in a chat with tools enabled, ask "search InvenTree for parts
      matching resistor" and watch `docker logs mcp-tools -f` for the call.
- [ ] Enable RAG embeddings: **Admin Settings → Documents** → Embedding
      Model Engine `Ollama` (`http://host.docker.internal:11434`), embedding
      model `qwen3-embedding:0.6b`. (Changing this later requires
      re-indexing any documents already uploaded.)
- [ ] Test RAG: upload a document in a chat, ask something answerable only
      from it, and confirm the answer cites the document.

## 4. Context models (predefined LLM contexts)

- [ ] Create each preset from [openwebui/contexts/](../openwebui/contexts/)
      as a Workspace Model (recipe in that README): Research Assistant,
      Ops Assistant, Knowledge Curator, Inventory Manager, Coding Assistant,
      Studio, Code Auditor, General Auditor. Each becomes a named entry in
      the chat model picker with its system prompt and tool scope baked in.
- [ ] Every preset's system prompt starts with the shared baseline block
      ([openwebui/contexts/_baseline.md](../openwebui/contexts/_baseline.md) — standing
      awareness of mcp-tools and the tools_help documentation tree). When
      presets change, re-paste the updated prompts into the existing
      Workspace Models.
- [ ] Test the review loop: have Coding Assistant produce a small function,
      then paste the task + code into Code Auditor and confirm it returns
      severity-ordered findings (or a clean bill) rather than a rewrite.

## 5. smolagents

- [ ] Restart to pick up the new agents: `smolagents/start.sh` (no rebuild
      needed). The startup log shows which MCP domains each agent got.
- [ ] Test at <http://localhost:8090>: "Ask web_researcher what the latest
      Raspberry Pi OS release is" (should hit SearXNG — check
      `docker logs searxng`), then "Ask ops to list open issues in Plane".
- [ ] Try scaffolding: "Create an agent called price_watcher that uses the
      web tools to track component prices." Review the generated file with
      `git diff smolagents/agents/custom/`, then
      `docker compose -p smolagents restart` to activate it.
- [ ] Test the auditor: "Ask auditor to review this code" with a small
      snippet — it should consult the coding reviewer pool
      (`qwen3-coder:30b`, `gpt-oss:20b`; models swap in VRAM, so this takes
      a few minutes) and return one merged findings report.

## 5b. Speech (voice in Open WebUI)

- [ ] Start the speech services: `speech/start.sh` (CPU-only — safe to
      leave running; first start downloads the Whisper model).
- [ ] Wire into Open WebUI (**Admin Settings → Audio**): Speech-to-Text
      engine `OpenAI`, URL `http://host.docker.internal:8091/v1`, key
      `no-key`, model `Systran/faster-whisper-small`; Text-to-Speech engine
      `OpenAI`, URL `http://host.docker.internal:8093/v1`, key `no-key`,
      voice `af_heart`.
- [ ] Test: use the microphone button in a chat and confirm transcription;
      tap the speaker icon on a reply and confirm audio.

## 5c. Hermes Agent (persistent memory)

- [ ] Install and configure per [docs/hermes-setup.md](hermes-setup.md) —
      including the per-project profile convention that keeps project
      contexts isolated.
- [ ] Baseline tool awareness per profile: register the profile's
      mcp-tools domains and teach it the baseline block once (see
      "Baseline tool awareness" in [docs/hermes-setup.md](hermes-setup.md)).
- [ ] Verify isolation: two profiles, one distinguishing fact each, confirm
      neither recalls the other's fact.

## 6. Write notifications (recommended)

- [ ] In n8n, create a workflow: **Webhook** node (POST, path e.g.
      `mcp-notify`) → **Send Email** (or ntfy/Telegram/etc.) using fields
      from the JSON body (`event`, `domain`, `tool`, `summary`, `changes`,
      `approvals_url`). Activate it.
- [ ] Put the production webhook URL in `mcp-tools/.env`:
      `APPROVAL_NOTIFY_WEBHOOK=http://host.docker.internal:5678/webhook/mcp-notify`,
      then `cd mcp-tools && docker compose -p mcp-tools up -d`.
- [ ] Test: ask a model to create a wiki page — you should get a notification
      summarizing the change (notify tier, executes immediately).

## 7. Approval flow dry-run

- [ ] Ask a model to modify a wiki document **you** wrote. The tool should
      answer `PENDING APPROVAL #<id>`.
- [ ] Open <http://mcp.localhost/approvals>, review the itemized changes and
      diff, click **Approve & execute**, and confirm the document changed.
      (Reject one too, to see that path.)

## 8. Ongoing tuning

- [ ] As trust grows, exempt domains/tools from gating in
      `mcp-tools/.env`, e.g.
      `APPROVAL_GATE_EXEMPT=inventree.inventree_adjust_stock,n8n.n8n_run_webhook`
      — or tighten with `APPROVAL_FORCE_GATE=outline`. Apply with
      `cd mcp-tools && docker compose -p mcp-tools up -d`.
- [ ] Tune the context-model system prompts in Open WebUI as you learn what
      each model does well; keep the source-of-truth copies in
      `openwebui/contexts/` up to date.
- [ ] Optionally tune SearXNG engines/weights in
      `searxng/settings.yml`.
- [ ] Review the audit trail occasionally at
      <http://mcp.localhost/approvals> (Recent activity) or
      `mcp-tools/data/mcp-tools/audit.jsonl`.
