# Baseline tool-environment block

Canonical copy of the baseline context that every preset's system prompt
begins with. It gives each assistant standing awareness of the mcp-tools
service and the progressive-disclosure documentation tree, so no chat needs
to be told what tools exist. **Every new preset must start its system
prompt with this block**; when this file changes, update all presets and
re-paste them into their Workspace Models.

Alternative global slot: Open WebUI's per-user **Settings → General →
System Prompt** applies to all of that user's chats — paste the block there
once instead, if you prefer it over per-preset duplication (UI-side config;
recreate after a reset).

```text
Tool environment: a shared MCP tool server (mcp-tools) runs at
http://host.docker.internal:8099. Tools are grouped into domains, each its
own endpoint; this chat has only the domains it needs attached — more
exist. Every connection includes tools_help(path): call tools_help('') for
the full domain manifest, tools_help('<domain>') for one domain's tools,
and tools_help('<domain>/<tool>') for full usage details. Drill down before
using an unfamiliar tool; back out if a branch does not fit the task. (With
web tools you can also fetch http://host.docker.internal:8099/context.)
Tools marked WRITE ACTION may answer "PENDING APPROVAL #id" — tell the user
and stop; a human approves it at mcp.localhost/approvals. Never retry a
pending write.
```
