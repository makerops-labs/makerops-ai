# Open WebUI runtime patches

Open WebUI runs from the upstream `ghcr.io/open-webui/open-webui` image
(pinned to a `vX.Y.Z` tag in `docker-compose.yml`; currently `v0.13.3`) with
no Dockerfile of our own, so these are **in-place edits to the container's
Python source**, applied by `apply.sh` (which `start.sh` calls automatically).

- They survive `docker restart openwebui`.
- They do **not** survive `docker compose ... up -d` / `pull` (image recreate).
  Re-run `patches/apply.sh` after any recreate, or just re-run `start.sh`.
- Each patch script is idempotent (marker-guarded) and prints `CHANGED` /
  `ALREADY` / `ERROR`. `apply.sh` restarts the container only on `CHANGED`.
- On `ERROR: anchor not found`, Open WebUI changed upstream — re-derive the
  anchor from the current source before shipping a new version.

## Patches

### `merge-model-toolids.py`

Open WebUI (verified through 0.13.3) applies a Workspace Model's default **`skillIds`**
server-side in `utils/middleware.py:process_chat_payload`, but not its
**`toolIds`** — tool selection is left entirely to the frontend. The frontend
only puts `tool_ids` in the chat request when the model is switched *inside the
chat*; a chat opened directly on a preset, a cloned/continued thread, or a hard
refresh all POST with no `tool_ids`, so the model runs with **zero tools**.

Symptom: "n8n Architect" always (and Researcher etc. intermittently) reports it
has no access to its MCP tools despite the preset having them attached.

The patch mirrors the existing `skill_ids` merge: when the request carries no
explicit tool selection, fall back to the model's configured `meta.toolIds`. It
only takes effect in the downstream `payload_tools is None` branch, so an
explicit `tools: []` opt-out is still honoured.
