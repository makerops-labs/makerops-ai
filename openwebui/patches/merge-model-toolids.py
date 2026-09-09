#!/usr/bin/env python3
"""Idempotent in-container patch for Open WebUI middleware.

Problem: Open WebUI 0.11.1 applies a Workspace Model's default `skillIds`
server-side (utils/middleware.py, in `process_chat_payload`) but does NOT do
the same for `toolIds`. Tool selection is left entirely to the frontend, which
only populates `tool_ids` in the chat request when the model is switched *in
the chat* — a chat opened directly on a preset, a cloned/continued thread, or a
hard refresh all POST with no `tool_ids`, so the model runs with zero tools.
Symptom: "n8n Architect" (and intermittently Researcher etc.) reports it has no
access to its MCP tools even though the preset has them attached.

Fix: mirror the existing `skill_ids` merge for `tool_ids` — when the request
carries no explicit tool selection, fall back to the model's configured
`meta.toolIds`. Only runs inside the `payload_tools is None` branch downstream,
so `tools: []` (explicit opt-out) is still respected.

This file is copied into the running container and executed by
`patches/apply.sh` (also called from `start.sh`). Safe to run repeatedly.

Exit codes: 0 = patch applied now / already present; 2 = anchor not found
(Open WebUI changed — re-check against upstream before shipping a new anchor).
"""

import sys

TARGET = "/app/backend/open_webui/utils/middleware.py"
MARKER = "# makerops-patch: merge model toolIds"
ANCHOR = "    tool_ids = form_data.pop('tool_ids', None)\n"
INSERT = (
    "    # makerops-patch: merge model toolIds. Upstream does this for skillIds\n"
    "    # (just below) but not toolIds, and the frontend only sends tool_ids on\n"
    "    # an explicit in-chat model switch — so a preset chat opened directly\n"
    "    # lands with no tools. Downstream this is read only inside the\n"
    "    # `payload_tools is None` branch, so `tools: []` opt-out still wins.\n"
    "    if not tool_ids:\n"
    "        tool_ids = list(\n"
    "            (model.get('info') or {}).get('meta', {}).get('toolIds', []) or []\n"
    "        ) or None\n"
)


def main() -> int:
    with open(TARGET, "r", encoding="utf-8") as fh:
        src = fh.read()

    if MARKER in src:
        print("ALREADY: middleware.py already carries the toolIds merge patch")
        return 0

    if ANCHOR not in src:
        print(f"ERROR: anchor not found in {TARGET}", file=sys.stderr)
        print("  Open WebUI's process_chat_payload has changed; re-derive the "
              "anchor from upstream before updating this patch.", file=sys.stderr)
        return 2

    src = src.replace(ANCHOR, ANCHOR + INSERT, 1)
    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(src)
    print("CHANGED: applied the toolIds merge patch to middleware.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
