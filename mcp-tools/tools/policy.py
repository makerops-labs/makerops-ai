"""Tiered write policy: notify-after for additive changes, gate-before for
deletions, overwrites of user-owned content, and business-effect mutations.

Tiers
-----
- ``notify``: the tool executes immediately; a summary is appended to the
  audit log and POSTed to the notification webhook so the user can review.
- ``gate``: the action is stored as a pending approval; it executes only when
  the user approves it in the web UI at /approvals. Models can poll status
  but cannot approve.

Action kinds
------------
- ``create``: new content (doc, issue, part, image, agent, draft reply) → notify.
- ``update``: overwrite of an existing object → notify if the object is
  agent-owned per the provenance registry, gate otherwise (user-created or
  previously user-approved content).
- ``delete``: always gate.
- ``effect``: business-effect mutation (stock adjustment, workflow trigger,
  outbound reply) → gate.

``APPROVAL_GATE_EXEMPT`` downgrades gate→notify and ``APPROVAL_FORCE_GATE``
upgrades notify→gate for "domain" or "domain.tool" entries, so trust can be
tuned per tool without code changes.
"""

import difflib
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Callable

import httpx

from . import config

_LOCK = threading.Lock()

APPROVALS_DIR = config.DATA_DIR / "approvals"
AUDIT_LOG = config.DATA_DIR / "audit.jsonl"
PROVENANCE_FILE = config.DATA_DIR / "provenance.json"

# domain.tool → callable(params: dict) -> str. Registered by the tool modules;
# used both for immediate (notify) execution and deferred (gate) execution.
_EXECUTORS: dict[str, Callable[[dict], str]] = {}


def register_executor(domain: str, tool: str, fn: Callable[[dict], str]) -> None:
    _EXECUTORS[f"{domain}.{tool}"] = fn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Provenance registry ────────────────────────────────────────────────────────

def _load_provenance() -> dict:
    try:
        return json.loads(PROVENANCE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_provenance(data: dict) -> None:
    PROVENANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROVENANCE_FILE.write_text(json.dumps(data, indent=1))


def record_created(domain: str, object_id: str) -> None:
    """Mark an object as agent-created (overwrites of it stay in notify tier)."""
    with _LOCK:
        prov = _load_provenance()
        prov[f"{domain}:{object_id}"] = {"status": "agent", "created_at": _now_iso()}
        _save_provenance(prov)


def mark_user_approved(domain: str, object_id: str) -> None:
    """After the user approves an overwrite, the object re-gates future ones."""
    with _LOCK:
        prov = _load_provenance()
        prov[f"{domain}:{object_id}"] = {"status": "user-approved",
                                         "updated_at": _now_iso()}
        _save_provenance(prov)


def is_agent_owned(domain: str, object_id: str) -> bool:
    entry = _load_provenance().get(f"{domain}:{object_id}")
    return bool(entry) and entry.get("status") == "agent"


# ── Audit log & notifications ─────────────────────────────────────────────────

def _audit(event: str, **fields) -> None:
    entry = {"ts": _now_iso(), "event": event, **fields}
    with _LOCK:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")


def read_audit(limit: int = 50) -> list[dict]:
    try:
        lines = AUDIT_LOG.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _notify(event: str, payload: dict) -> None:
    """Fire-and-forget POST to the notification webhook (n8n → email/push)."""
    if not config.APPROVAL_NOTIFY_WEBHOOK:
        return
    body = {"event": event, "approvals_url": f"{config.MCPTOOLS_PUBLIC_URL}/approvals",
            **payload}

    def _post():
        try:
            httpx.post(config.APPROVAL_NOTIFY_WEBHOOK, json=body, timeout=5.0)
        except httpx.HTTPError as exc:
            _audit("notify.failed", error=str(exc))

    threading.Thread(target=_post, daemon=True).start()


# ── Pending approvals store ────────────────────────────────────────────────────

def _pending_path(action_id: str):
    return APPROVALS_DIR / f"{action_id}.json"


def _load_action(action_id: str) -> dict | None:
    try:
        return json.loads(_pending_path(action_id).read_text())
    except (OSError, ValueError):
        return None


def _save_action(action: dict) -> None:
    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    _pending_path(action["id"]).write_text(json.dumps(action, indent=1, default=str))


def _expire_if_stale(action: dict) -> dict:
    if action.get("status") == "pending":
        age_h = (time.time() - action.get("created_ts", 0)) / 3600
        if age_h > config.APPROVAL_TTL_HOURS:
            action["status"] = "expired"
            _save_action(action)
    return action


def list_actions(status: str | None = None) -> list[dict]:
    actions = []
    if APPROVALS_DIR.is_dir():
        for path in sorted(APPROVALS_DIR.glob("*.json"), reverse=True):
            try:
                action = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            action = _expire_if_stale(action)
            if status is None or action.get("status") == status:
                actions.append(action)
    return actions


def get_action(action_id: str) -> dict | None:
    action = _load_action(action_id)
    return _expire_if_stale(action) if action else None


def resolve_action(action_id: str, approve: bool) -> tuple[bool, str]:
    """Approve or reject a pending action (called only from the web UI)."""
    action = get_action(action_id)
    if action is None:
        return False, f"No such action {action_id}."
    if action["status"] != "pending":
        return False, f"Action {action_id} is already {action['status']}."

    if not approve:
        action["status"] = "rejected"
        action["resolved_at"] = _now_iso()
        _save_action(action)
        _audit("action.rejected", id=action_id, domain=action["domain"],
               tool=action["tool"], summary=action["summary"])
        return True, f"Action {action_id} rejected."

    executor = _EXECUTORS.get(f"{action['domain']}.{action['tool']}")
    if executor is None:
        return False, (f"No executor registered for {action['domain']}.{action['tool']} "
                       f"(is that domain still mounted?).")
    try:
        result = executor(action["params"])
    except Exception as exc:  # tool bug — record, don't lose the action
        action["status"] = "failed"
        action["result"] = f"ERROR: {exc}"
        action["resolved_at"] = _now_iso()
        _save_action(action)
        _audit("action.failed", id=action_id, domain=action["domain"],
               tool=action["tool"], error=str(exc))
        return False, f"Action {action_id} failed: {exc}"

    action["status"] = "approved"
    action["result"] = result[:2000]
    action["resolved_at"] = _now_iso()
    _save_action(action)
    if action.get("action_kind") == "update" and action.get("target_id"):
        mark_user_approved(action["domain"], action["target_id"])
    _audit("action.approved", id=action_id, domain=action["domain"],
           tool=action["tool"], summary=action["summary"],
           result=result[:300])
    return True, f"Action {action_id} approved and executed."


# ── Tier resolution & entry point ─────────────────────────────────────────────

def _matches(entries: set[str], domain: str, tool: str) -> bool:
    return domain in entries or f"{domain}.{tool}" in entries


def _resolve_tier(domain: str, tool: str, action_kind: str,
                  target_id: str | None) -> str:
    if action_kind == "delete":
        tier = "gate"
    elif action_kind == "create":
        tier = "notify"
    elif action_kind == "update":
        tier = "notify" if (target_id and is_agent_owned(domain, target_id)) else "gate"
    else:  # effect
        tier = "gate"

    if tier == "gate" and action_kind != "delete" and _matches(
            config.APPROVAL_GATE_EXEMPT, domain, tool):
        tier = "notify"
    if tier == "notify" and _matches(config.APPROVAL_FORCE_GATE, domain, tool):
        tier = "gate"
    return tier


def apply_policy(*, domain: str, tool: str, action_kind: str, summary: str,
                 params: dict, target_id: str | None = None,
                 changes: list[str] | None = None, diff: str | None = None,
                 created_object_id_from_result: bool = False) -> str:
    """Route a write action through the tiered policy. Returns the string the
    model sees. The actual work is the executor registered for domain.tool.
    """
    executor = _EXECUTORS.get(f"{domain}.{tool}")
    if executor is None:
        return f"ERROR: no executor registered for {domain}.{tool} (server bug)."

    tier = _resolve_tier(domain, tool, action_kind, target_id)

    if tier == "notify":
        try:
            result = executor(params)
        except Exception as exc:  # tool bug — audit it like the gated path does
            _audit("action.failed", domain=domain, tool=tool, summary=summary,
                   error=str(exc))
            return f"ERROR: {domain}.{tool} failed: {exc}"
        if result.startswith("ERROR:"):
            return result
        # Record provenance for newly created objects: the executor returns
        # "OBJECT_ID=<id>\n" as its first line when it created something.
        if created_object_id_from_result and result.startswith("OBJECT_ID="):
            first, _, rest = result.partition("\n")
            record_created(domain, first[len("OBJECT_ID="):].strip())
            result = rest or result
        elif action_kind == "create" and target_id:
            record_created(domain, target_id)
        _audit("action.completed", domain=domain, tool=tool, summary=summary,
               changes=changes or [], result=result[:300])
        _notify("action.completed", {"domain": domain, "tool": tool,
                                     "summary": summary, "changes": changes or []})
        return (f"{result}\n\n[write policy: executed immediately; the user was "
                f"notified with a summary of this change]")

    action_id = f"{int(time.time())}-{secrets.token_hex(3)}"
    action = {
        "id": action_id, "status": "pending", "domain": domain, "tool": tool,
        "action_kind": action_kind, "target_id": target_id, "summary": summary,
        "changes": changes or [], "diff": diff or "", "params": params,
        "created_at": _now_iso(), "created_ts": time.time(),
    }
    _save_action(action)
    _audit("action.pending", id=action_id, domain=domain, tool=tool, summary=summary)
    _notify("action.pending", {"id": action_id, "domain": domain, "tool": tool,
                               "summary": summary, "changes": changes or []})
    return (f"PENDING APPROVAL #{action_id}: {summary}. This action is held for "
            f"human review — the user must approve it at "
            f"{config.MCPTOOLS_PUBLIC_URL}/approvals before it runs. Tell the "
            f"user about the pending action; you can check its state with "
            f"approval_status(\"{action_id}\").")


def make_diff(old: str, new: str, label: str) -> str:
    """Unified diff for the approvals review UI (truncated to stay readable)."""
    diff = "\n".join(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(),
        fromfile=f"current/{label}", tofile=f"proposed/{label}", lineterm=""))
    if len(diff) > 20000:
        diff = diff[:20000] + "\n... [diff truncated]"
    return diff
