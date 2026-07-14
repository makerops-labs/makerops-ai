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
  # 64K-context variant of the coding lead — default chat / Task Dispatcher
  # base model. KV cache on top of a ~19-23 GB model can hit the 24 GB WSL2
  # RAM cap: after creating it, run a long prompt and check
  # `docker exec ollama ollama ps`; on OOM (signal: killed) recreate with
  # num_ctx 32000 instead.
  printf 'FROM qwen3.6:35b\nPARAMETER num_ctx 64000\n' | \
    docker exec -i ollama sh -c 'cat > /tmp/Modelfile && ollama create qwen3.6:35b-64k -f /tmp/Modelfile'
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
      `web`, `approvals`, `comfyui`, `drawio`, `agents`, `speech`, `trellis`
      mount until you add tokens below (the last two degrade gracefully
      while their backing service is stopped).
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
      for gemma-class models). **API key: any non-empty value (e.g.
      `no-key`)** — an empty key makes Open WebUI (≤0.10.2) send an illegal
      empty `Bearer` header (trailing space) and the connection fails
      before any request is sent.
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
      as a Workspace Model (recipe in that README): Task Dispatcher,
      Researcher (structured, sourced research briefs — the direct-chat
      face of the smolagents `researcher` agent), Investment Strategist
      (sourced, risk-weighted investment assessments — the direct-chat
      face of the smolagents `investment_strategist` agent; needs the
      `project` domain connection and the registered `investments`
      project), Research Assistant,
      Ops Assistant, Knowledge Curator, Inventory Manager, Coding
      Assistant, Studio, Code Auditor, General Auditor.
      Each becomes a named entry in the chat model picker with its system
      prompt and tool scope baked in. (Debate Moderator is set up
      separately in §5h, once the agent job queue and debate system are
      running.)
- [ ] Make the default chat agent-aware: set `qwen3.6:35b-64k` as your
      default model and paste the baseline block
      ([openwebui/contexts/_baseline.md](../openwebui/contexts/_baseline.md))
      into **Settings → General → System Prompt** — then any chat knows the
      tool domains and the agent workforce without a preset.
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

## 5b-2. TRELLIS (image-to-3D, optional)

- [ ] Build + start: `trellis/start.sh` (first build compiles CUDA
      extensions — 20–40 min; first start then downloads ~5 GB of weights:
      wait for `curl -s localhost:8094/healthz | jq` → `weights_ready:true`).
- [ ] Warm-up generation (also JIT-compiles nvdiffrast — allow ~10 min):
      `curl -s -F image=@photo.png localhost:8094/generate`, poll
      `curl localhost:8094/jobs/<id>`, then download `/jobs/<id>/model.glb`.
- [ ] Agent path: ask the smolagents studio agent (or the Open WebUI Studio
      preset) to make a 3D model from an image URL — the GLB lands under
      `mcp.localhost/files/models/`.
- [ ] Stop when done: `trellis/stop.sh` — a generation needs most of the
      16 GB card, so the service is start-on-demand only.

## 5c. Hermes Agent (persistent memory)

- [ ] Install and configure per [docs/hermes-setup.md](hermes-setup.md) —
      including the per-project profile convention that keeps project
      contexts isolated.
- [ ] Baseline tool awareness per profile: register the profile's
      mcp-tools domains and teach it the baseline block once (see
      "Baseline tool awareness" in [docs/hermes-setup.md](hermes-setup.md)).
- [ ] Verify isolation: two profiles, one distinguishing fact each, confirm
      neither recalls the other's fact.

## 5d. Agent task dispatch (background jobs)

- [ ] Recreate mcp-tools so it mounts the shared job queue (new compose
      volume): `cd mcp-tools && docker compose -p mcp-tools up -d`. Check
      `curl -s http://localhost:8099/healthz | jq .jobs` returns counts
      (not `null`), and restart smolagents (`docker restart smolagents`) so
      its job worker writes `roster.json`.
- [ ] Create the **"Agent Deliverables"** collection in Outline — agents
      publish durable documents there (dated names, job-id footer).
- [ ] Job notifications: point `SMOLAGENTS_NOTIFY_WEBHOOK` in
      `smolagents/.env` at an n8n webhook (the §6 workflow works — job
      events carry `event` = `job.completed` / `job.needs_clarification` /
      `job.needs_attention` / `job.failed`, plus `job_id`, `objective`,
      `summary`, `inbox_url`), then
      `cd smolagents && docker compose -p smolagents up -d` (recreate —
      `.env` changed).
- [ ] Dry-run: in the **Task Dispatcher** preset, ask for a small research
      task, confirm the brief, and let it dispatch. Watch
      `agent_job_status`, then check the report in the task inbox at
      <http://mcp.localhost/inbox> (same token/cookie as approvals).
- [ ] Long jobs run in segments: the manager keeps
      `data/smolagents/jobs/<id>/workspace/synopsis.md` as working memory
      and continues from it in a fresh context. Segment count shows on the
      inbox card; cap it with `SMOLAGENTS_MAX_SEGMENTS` (default 8).

## 5e. Self-improvement loop

The stack can review its own performance and propose code changes to
itself — every actual change is a human-reviewed diff at `/approvals`,
same as any other gated write. See the root [README.md](../README.md)
"Self-improvement loop" for the concept; this is the one-time setup.

- [ ] Start the redeploy service: `cd redeploy && ./start.sh`. First run
      generates a random `REDEPLOY_TOKEN` and prints it — copy that exact
      value into `mcp-tools/.env`'s `REDEPLOY_TOKEN` (both sides must
      match), then `cd mcp-tools && docker compose -p mcp-tools up -d`
      (recreate — `.env` and the new repo-root mount both need it).
      Verify: `curl -s http://localhost:8101/healthz`.
- [ ] Confirm the Outline **"AI"** collection exists (it's one of the
      defaults) — `maintainer`'s evaluation reports land there. No
      creation needed unless you deleted it.
- [ ] Create a **"Stack Improvements"** project in your primary Plane
      workspace (Projects → New Project) — `maintainer` files one issue
      per proposed improvement there. Note the workspace slug if it isn't
      already in `mcp-tools/.env`'s `PLANE_WORKSPACE_SLUGS`.
- [ ] The **Research Ledger** and **Research Query Log** Outline docs
      (external-trends-sweep bookkeeping — see root README's
      "Self-improvement loop") are **self-bootstrapping**: `maintainer`
      creates them itself in the AI collection the first time it doesn't
      find one. No manual creation step, unlike the Plane project above.
- [ ] Optional: to let `maintainer` include X/Twitter in its external
      sweep, get a Bearer token from an X developer account (Project →
      Keys and tokens → Bearer Token — **billed per read, ~$0.005-0.01/
      read, no free tier**) and set `X_API_BEARER_TOKEN` in
      `mcp-tools/.env`, then `cd mcp-tools && docker compose -p mcp-tools
      up -d` (recreate — plain `restart` doesn't re-read `.env`). Leave it
      empty to skip — the sweep works fine on the free engines alone
      (arxiv, github, scholar, stackoverflow, general web). Verify:
      `curl -s http://localhost:8099/healthz` should list `x` as mounted,
      not skipped.
      **Cost math** (confirmed live 2026-07-09: a 10-result call billed
      $0.05, i.e. the $0.005/read tier): `x_search_recent` defaults to and
      caps at 100 results/call, so one call costs **$0.50-$1.00**
      depending on which of X's two per-read rates it's billed at. A
      single sweep's brief spans up to four topic areas (smolagents, MCP,
      agent orchestration, prompt engineering); the Research Query Log's
      dedup check means most of those are skipped once a topic has been
      asked about in the last 7 days, but on a cold ledger (first run, or
      after a long gap) all four could go out fresh — **worst case ~$4.00
      per loop iteration** (4 calls × $1.00), typical steady-state cost
      once the log is populated is **one fresh call or fewer per
      iteration, ~$0.50 or less**. At a weekly cadence that's a few
      dollars a month at worst; there is no cross-run dollar budget
      tracker in this version — the Query Log itself is the only running
      proxy (count its `x_search_recent` lines to estimate spend).
- [ ] Optional recurring trigger: in n8n, a **Schedule Trigger** (weekly)
      node → call `agent_dispatch` on the agents MCP endpoint with a fixed
      brief ("Review the last 7 days of job and audit history; sweep
      external sources for new AI-tooling techniques against the Research
      Ledger and Query Log; research and propose improvements; file
      findings in Plane and Outline; audit: always"). On-demand dispatch
      works fine without this — set it up once you'd rather not remember
      to ask.
- [ ] **Dry-run the full loop**: ask a dispatch-capable chat (Task
      Dispatcher) to "review the stack's recent performance and propose
      improvements." Expected sequence: `maintainer` pulls
      `agent_job_history`/`agent_audit_history`, reads or bootstraps the
      Research Ledger and Query Log, and (via the manager) has
      `web_researcher` sweep external sources → an Outline report appears
      in the AI collection, and at least one Ledger entry gets logged for
      anything evaluated (even if rejected/deferred) → zero or more Plane
      issues appear in Stack Improvements (zero is a valid, honest outcome
      on a quiet history and a sparse research landscape — don't expect a
      proposal every time) → if a proposal is well-scoped, a diff appears
      at `/approvals` referencing the Plane issue. Running the dry-run a
      second time should show it skipping ledger-matched findings and
      query-log-matched searches rather than re-evaluating everything.
- [ ] **Dry-run a code-change approval**: propose (or wait for maintainer
      to propose) something trivial, review the diff at `/approvals`,
      approve it, and confirm: the file changed on disk, the correct
      container restarted (`docker inspect <service> --format
      '{{.State.StartedAt}}'` should be recent), and a `redeploy.completed`
      entry appears in "Recent activity."
- [ ] **Your ongoing responsibility**: pending code-change approvals
      expire after `APPROVAL_TTL_HOURS` (24h default) like any other gated
      action — review them or they're lost, not queued forever. A clean
      restart proves the change *runs*, not that it's *correct*; that
      judgment is what your review is for.

## 5f. Project workspaces

The stack can implement an already-approved solution's code and docs inside
a directory **you** create — see the root [README.md](../README.md)
"Project workspaces" for the concept; this is the one-time setup.

- [ ] Set `WORKSPACES_ROOT` in `mcp-tools/.env` to your absolute `~/workspace`
      path (project directories are its direct children, siblings of
      `~/workspace/makerops/` — not inside it). Then `cd mcp-tools && docker
      compose -p mcp-tools up -d` (recreate — new volume mount, a plain
      `restart` won't pick it up).
- [ ] Verify the mount: `docker exec mcp-tools ls /workspaces` should list
      your real `~/workspace` sibling directories.
- [ ] **Dry-run a prior-art read**: ask a dispatch-capable chat to list an
      existing sibling directory under `~/workspace` (one you never
      registered) — confirm reads work without any registration step.
- [ ] Create a real (or throwaway) directory, e.g. `mkdir ~/workspace/test-app`.
- [ ] **Dry-run registration + a write**: ask a model to call
      `project_register(project="test-app", ...)`, then write a file into
      it. Confirm: the write executes immediately (notify tier, not
      `PENDING APPROVAL`), the file lands on disk, and `PROJECT_CONTEXT.md`
      was seeded automatically at the project root.
- [ ] **Dry-run a full dispatch**: `agent_dispatch(..., project="test-app")`
      for a small, concrete task. Expected sequence: the manager reads
      `PROJECT_CONTEXT.md` first, delegates to `coder`/`writer` as needed,
      the files land in `~/workspace/test-app/`, `PROJECT_CONTEXT.md` is
      updated to reflect the new state, and the job's final report
      references the project path.
- [ ] Confirm registering `makerops` itself (or anything under
      `~/workspace/makerops/`) is rejected — that subtree stays governed by
      `propose_code_change`/`redeploy` (5e above), not this domain.

## 5g. Sandboxed command execution

The stack can run bounded shell commands (tests, linters, builds, `git`,
package installs) confined to one registered project directory — see the
root [README.md](../README.md) "Sandboxed command execution" for the
concept; this is the one-time setup.

- [ ] `cd sandbox && ./start.sh`. First run generates a random
      `SANDBOX_TOKEN` and builds the ephemeral-container runtime image
      (`runtime.Dockerfile`) — copy the token into `mcp-tools/.env`'s
      `SANDBOX_TOKEN` (both sides must match), set `WORKSPACES_ROOT` in
      `sandbox/.env` to the **same** absolute path as `mcp-tools/.env`'s,
      then `cd ../mcp-tools && docker compose -p mcp-tools up -d` (recreate
      — new env vars). Verify: `curl -s http://localhost:8102/healthz`.
- [ ] **Dry-run a raw command**: register a test project (per 5f), then ask
      a dispatch-capable chat to run something trivial in it via
      `project_run_command` (e.g. `echo hi && ls`) — confirm it executes
      immediately (notify tier) and the output comes back accurately.
- [ ] **Dry-run isolation**: ask it to run `ls /var/run/docker.sock` and
      `which docker` in the sandbox — both should fail; there is no Docker
      access from inside a sandboxed command.
- [ ] **Dry-run a real workflow**: ask it to write a small module with a
      test, then actually run the test suite (`pip install pytest -q &&
      python3 -m pytest -q`) via `project_run_command` and report the real
      result — confirm the reported pass/fail matches what's really on
      disk, not an assumption.
- [ ] **Your ongoing responsibility**: this is notify-tier, not gated —
      review what ran via the audit log (`/approvals` "Recent activity")
      at your own pace, the same way you already do for other notify-tier
      writes.

## 5h. Debates (multi-persona argument)

Three fixed personas (entrepreneur, critic, monitor) argue a goal over
several rounds, one turn at a time in series — see the root
[README.md](../README.md) "Debate system" for the concept. This reuses the
agent job queue's mechanism (§5d), so complete that section first.

- [ ] Pull the debate-only models if you haven't already for the reviewer
      pool/task dispatch: `docker exec ollama ollama pull qwen3.6:35b-64k`
      (create the derivative per §1 if not already done) and
      `docker exec ollama ollama pull gpt-oss:20b` (~13 GB).
- [ ] Create the critic's context-bumped derivative — the base model
      serves at Ollama's 4k default, which truncates a debate turn
      mid-answer (same reason the qwen leads have -64k variants):
      `docker exec ollama sh -c 'printf "FROM gpt-oss:20b\nPARAMETER
      num_ctx 32768\n" > /tmp/mf && ollama create gpt-oss:20b-32k -f /tmp/mf'`
- [ ] Recreate mcp-tools so it mounts the debate session store (new compose
      volume): `cd mcp-tools && docker compose -p mcp-tools up -d`. Check
      `curl -s http://localhost:8099/healthz | jq .domains` includes
      `"debate"`, and restart smolagents (`docker restart smolagents`) so
      its job worker builds the three debate personas alongside the general
      manager (the worker runs each persona directly — there is no
      orchestrator LLM in a debate turn).
- [ ] Create the **Debate Moderator** preset from
      [openwebui/contexts/debate-moderator.md](../openwebui/contexts/debate-moderator.md)
      (recipe in [openwebui/contexts/README.md](../openwebui/contexts/README.md))
      — base model `qwen3.6:35b-64k`, tool connections `debate` and `web`.
- [ ] Stop `trellis` if it's running — the entrepreneur/monitor personas
      default to `qwen3.6:35b-64k`, which hits the same RAM-starvation
      conflict documented for Task Dispatcher (§4) and this stack's System
      Requirements.
- [ ] **Dry-run**: in the Debate Moderator preset, propose a small, concrete
      idea; confirm it asks clarifying questions (mode, deliverables)
      rather than guessing, confirms the brief back before calling
      `debate_start`, and reports a session id. Watch `debate_status`
      progress through a few rounds; confirm the model actually swaps to
      `gpt-oss:20b` for critic turns (`docker exec ollama ollama ps` or
      Ollama's logs) and back for entrepreneur/monitor turns — this is the
      accepted VRAM-swap cost for cross-lineage decorrelation on an
      unattended background tool.
- [ ] Read `debate_manifest(session_id)` after a few rounds and confirm the
      one-line descriptions are actually useful for deciding what to read
      in full — that's the whole point of the manifest for a debate that
      runs long. Open a round file too and confirm it's plain markdown
      prose (abstract line, blank line, argument) — never raw python/JSON;
      the personas' output contract + the worker's fence-unwrap backstop
      exist precisely because local models drift into relaying code.
- [ ] **Let one debate finish** (e.g. `max_rounds=3`): confirm it passes
      through status `concluding` (one extra closing monitor turn — this
      is by design, it runs past max_rounds to write the report), lands
      `concluded`, and `debate_result(session_id)` returns a stand-alone
      human-readable synthesis (decision, surviving objections, next
      steps) — you should never need to read the raw rounds to know the
      outcome.
- [ ] **Crash-recovery dry-run** (optional but recommended once): restart
      smolagents mid-turn (`docker restart smolagents`), confirm
      `debate_status` shows `stuck` with a clear `stop_reason` rather than
      silently stalling, then `debate_resume` it and confirm the exact
      interrupted round re-runs with no gap in round numbering.

## 5i. Alexa voice control (optional)

Voice-control the stack from real Amazon Echo devices via a dedicated
liaison agent (`smolagents/agents/alexa_liaison.py`) that owns the whole
conversation — see [alexa-bridge/README.md](../alexa-bridge/README.md) for
the architecture and [alexa-voice-setup.md](alexa-voice-setup.md) for the
full manual walkthrough (Cloudflare Tunnel + Alexa Developer Console). The
code side (liaison agent, mcp-tools' `liaison` domain, the bridge service)
is already in place; this is the remaining manual setup checklist:

- [ ] Recreate mcp-tools so it mounts the liaison session store (new
      compose volume): `cd mcp-tools && docker compose -p mcp-tools up -d`.
      Check `curl -s http://localhost:8099/healthz | jq .domains` includes
      `"liaison"`, and restart smolagents (`docker restart smolagents`) so
      its job worker builds the liaison agent alongside manager/debate_manager.
- [ ] Follow [alexa-voice-setup.md](alexa-voice-setup.md) for the
      Cloudflare Tunnel setup, `alexa-bridge/start.sh`, and the Alexa
      Developer Console skill creation — in that order, since the skill's
      endpoint URL needs the tunnel's hostname to exist first.
- [ ] **Caveat, same shape as the name-proxy one above**: the private
      Cloudflare Tunnel ingress config
      (`makerops-core/remote_access/cloudflared/config/config.yml`) lives
      outside git, copied by hand from
      `proxy/cloudflared-config.yml.template` — rebuilding `makerops-core`
      from scratch means redoing that copy (see that template's own
      comments and `remote_access/cloudflared/README.md`).
- [ ] **Dry-run** (see `alexa-bridge/README.md`'s Verify section for the
      curl-based version first): from a real Echo device, ask something
      ambiguous, confirm the liaison asks exactly one clarifying question,
      answer it, then say "status", then say "goodbye" and confirm the
      session ends cleanly. Trigger a gated write action by voice and
      confirm "confirm"/"deny" resolves it via the same `/approvals` gate
      any other client uses — never an LLM's own judgment call.

## 5j. Devteam engagements (build an app from a product plan)

A lead-architect agent plus a specialist software team builds an entire
application in a registered project workspace, phase by phase with
sign-off gates and mid-run questions — see the root
[README.md](../README.md) "Devteam engagements" for the concept. Reuses
the agent job queue (§5d) and project workspaces (§5f + §5g), so complete
those first. Notifications (§6) are strongly recommended here — the whole
point is being pinged when the team needs you.

- [ ] Recreate mcp-tools so it mounts the devteam session store (new
      compose volume): `cd mcp-tools && docker compose -p mcp-tools up -d`
      (remember: `restart` never applies volume changes). Check
      `curl -s http://localhost:8099/healthz | jq .domains` includes
      `"devteam"`, and restart smolagents (`docker restart smolagents` —
      job queue idle first) so its worker builds the lead architect
      alongside manager/debate/liaison.
- [ ] Create the **App Builder** context model per
      [openwebui/contexts/app-builder.md](../openwebui/contexts/app-builder.md)
      (§4 walkthrough): tool connections `/mcp/devteam/` and
      `/mcp/project/`, base model `qwen3.6:35b-64k`, native function
      calling, native capabilities off.
- [ ] **Dry-run**: create and register a scratch project
      (`mkdir ~/workspace/devteam-demo`, then `project_register` from the
      App Builder chat), start a tiny engagement ("CLI todo app, Python,
      JSON-file storage, pytest"), and confirm: the requirements phase
      runs and gates (`awaiting_review`, notification arrives),
      `devteam_approve` advances to architecture, the architecture gate
      shows a milestone plan in `devteam_result`, and after approval the
      scaffold/milestone phases advance on their own. Also exercise
      `devteam_revise` once at a gate, and an intentionally vague plan
      ("build something for my shop") to see `awaiting_input` →
      `devteam_answer` resume.
- [ ] Engagements are long unattended model time: stop `trellis` first
      (same 35b RAM gotcha as §5h debates), and expect hours wall-clock
      for a real plan.

## 6. Write notifications (recommended)

- [ ] In n8n, create a workflow: **Webhook** node (POST, path e.g.
      `mcp-notify`) → **Send Email** (or ntfy/Telegram/etc.) using fields
      from the JSON body (`event`, `domain`, `tool`, `summary`, `changes`,
      `approvals_url`). Activate it. Devteam engagements (§5j) send
      `devteam.needs_input` (with a `questions` list), `devteam.milestone`
      (informational or gated — the `status` field distinguishes),
      `devteam.stuck`, and `devteam.completed` events through the same
      webhook (`SMOLAGENTS_NOTIFY_WEBHOOK` side, plus `devteam.completed`
      from mcp-tools on a final approval) — the default workflow works
      as-is; add per-event routing (e.g. push for `devteam.needs_input`,
      email digest for milestones) if the volume warrants it.
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
