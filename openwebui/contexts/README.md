# LLM Context Presets

Predefined contexts for interacting with the local models. Each file in this
directory defines one context: what it is for, which base model to use, which
mcp-tools domains it gets, and a ready-to-paste system prompt. Open WebUI
stores workspace models in its database, so these files are the git-tracked
source of truth — recreate from here after a reset, and back-port any prompt
tuning you do in the UI.

## Creating a context model (once per preset)

1. Make sure the tool server connection(s) the preset needs exist:
   **Admin Settings → External Tools → Add Connection** → type **MCP
   (Streamable HTTP)** → URL `http://host.docker.internal:8099/mcp/<domain>/`
   (one connection per domain the preset lists — per-domain scoping keeps
   tool lists short, which local models need).
2. **Workspace → Models → New Model**:
   - **Name**: the preset's context name (e.g. "Research Assistant").
   - **Base model**: as listed in the preset.
   - **System prompt**: paste from the preset file.
   - **Tools**: tick the connections listed in the preset.
   - **Advanced params → Function calling: Native** (recommended for the
     qwen3.5/qwen3.6 leads; revert to Default if tool calls get unreliable
     on a given base model).
3. Save. The context now appears in the chat model picker.

## Presets

| Context | Base model | Tool domains |
| --- | --- | --- |
| [Research Assistant](research-assistant.md) | qwen3.5:9b | web |
| [Ops Assistant](ops-assistant.md) | qwen3.5:9b | outline, inventree, plane, n8n, freescout, triggerdev, approvals |
| [Knowledge Curator](knowledge-curator.md) | qwen3.5:9b | outline, web, approvals |
| [Inventory Manager](inventory-manager.md) | qwen3.5:9b | inventree, approvals |
| [Coding Assistant](coding-assistant.md) | qwen3.6:35b | web |
| [Studio](studio.md) | qwen3.5:9b | comfyui, drawio |
| [Code Auditor](code-auditor.md) | gpt-oss:20b | web (optional) |
| [General Auditor](general-auditor.md) | gemma4:12b | web (optional) |

### Baseline tool-environment block

Every preset's system prompt **starts with the shared baseline block** from
[_baseline.md](_baseline.md) — it gives each assistant standing awareness of
mcp-tools and the `tools_help()` documentation tree without per-chat
prompting. New presets must include it; when `_baseline.md` changes, update
every preset and re-paste the prompts into their Workspace Models. (The
per-user alternative — Settings → General → System Prompt — is described in
`_baseline.md`.)

Base models follow the lead-per-domain hierarchy in [README.md](../../README.md):
leads produce work, the auditor presets give second opinions from
same-expertise, lower-benchmark models (including a different lineage) to
catch the lead's blind spots.

The same contexts exist in smolagents: web_researcher ≈ Research Assistant,
ops ≈ Ops Assistant, coder ≈ Coding Assistant. For the narrower ones
(Inventory Manager, Knowledge Curator), scaffold an equivalent agent with
`agent_create` if you want it in the agent workspace too.
