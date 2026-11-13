"""Pure validation + scoring for evals/tasks.yaml (no network, no models).

Kept separate from run.py so CI can test it without a GPU, Ollama, or the
business apps.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

CLASSES = {"read", "additive", "gated", "decline"}
APPROVALS = {"none", "notify", "gate", "ask"}
STATE_CHECKS = {"po_pending_with_lines", "po_status", "freescout_draft_reply_exists",
                "part_exists", "stock_unchanged", "tool_called_at_most"}
SETUPS = {"draft_po_for_shortfall"}
PENDING_MARK = "PENDING APPROVAL #"
NOTIFY_MARK = "[write policy: executed immediately"

TOOLS_DIR = Path(__file__).resolve().parent.parent / "mcp-tools" / "tools"


# ── Tool inventory (static, from mcp-tools source) ───────────────────────────

def tool_inventory(tools_dir: Path = TOOLS_DIR) -> tuple[set[str], set[str]]:
    """(all MCP tool names, write tool names) found by parsing mcp-tools."""
    tools, writes = set(), set()
    for path in sorted(tools_dir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(getattr(d, "attr", getattr(d, "id", "")) == "tool" for d in node.decorator_list):
                tools.add(node.name)
                if (ast.get_docstring(node) or "").startswith("WRITE ACTION"):
                    writes.add(node.name)
    return tools, writes


# ── Validation (what --dry-run checks) ───────────────────────────────────────

def _named(entries) -> list[tuple[str, object]]:
    """state/setup entries are either "name" or {"name": arg}."""
    out = []
    for e in entries or []:
        if isinstance(e, str):
            out.append((e, None))
        elif isinstance(e, dict) and len(e) == 1:
            out.append(next(iter(e.items())))
        else:
            out.append((repr(e), None))
    return out


def validate(doc: dict, known_tools: set[str]) -> list[str]:
    errors = []
    tasks = doc.get("tasks") or []
    if not tasks:
        return ["no tasks"]
    seen = set()
    for i, t in enumerate(tasks):
        tid = t.get("id") or f"#{i}"
        where = f"task {tid}"
        if tid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(tid)
        for key in ("id", "class", "prompt", "approval", "success", "reviewed"):
            if key not in t:
                errors.append(f"{where}: missing '{key}'")
        if t.get("class") not in CLASSES:
            errors.append(f"{where}: class must be one of {sorted(CLASSES)}")
        if t.get("approval") not in APPROVALS:
            errors.append(f"{where}: approval must be one of {sorted(APPROVALS)}")
        if not isinstance(t.get("reviewed"), bool):
            errors.append(f"{where}: reviewed must be true/false")
        tools = t.get("tools") or {}
        for kind in tools:
            if kind not in ("required", "ordered", "forbidden"):
                errors.append(f"{where}: unknown tools key '{kind}'")
        for kind in ("required", "ordered", "forbidden"):
            for name in tools.get(kind) or []:
                if name not in known_tools:
                    errors.append(f"{where}: tools.{kind} names unknown tool '{name}'")
        success = t.get("success") or {}
        if not success:
            errors.append(f"{where}: success needs at least one check")
        for key in success:
            if key not in ("answer_contains", "answer_contains_any", "answer_excludes", "state"):
                errors.append(f"{where}: unknown success key '{key}'")
        for name, arg in _named(success.get("state")):
            if name not in STATE_CHECKS:
                errors.append(f"{where}: unknown state check '{name}'")
            if name == "tool_called_at_most":
                for tool in (arg or {}):
                    if tool not in known_tools:
                        errors.append(f"{where}: tool_called_at_most names unknown tool '{tool}'")
        for name, _ in _named(t.get("setup")):
            if name not in SETUPS:
                errors.append(f"{where}: unknown setup '{name}'")
        if t.get("approval") == "gate" and t.get("class") != "gated":
            errors.append(f"{where}: approval 'gate' belongs to class 'gated'")
    return errors


# ── Scoring one run ──────────────────────────────────────────────────────────

@dataclass
class Call:
    name: str
    arguments: object = None
    observation: str = ""


@dataclass
class Score:
    tool_selection: bool
    gating: bool
    success: bool | None          # None = state checks not evaluated (offline)
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.tool_selection and self.gating and self.success is not False


def _is_subsequence(want: list[str], got: list[str]) -> bool:
    it = iter(got)
    return all(any(g == w for g in it) for w in want)


def score_tools(task: dict, calls: list[Call]) -> tuple[bool, list[str]]:
    spec = task.get("tools") or {}
    names = [c.name for c in calls]
    reasons = []
    missing = [t for t in spec.get("required") or [] if t not in names]
    if missing:
        reasons.append(f"missing required tool(s): {missing}")
    if spec.get("ordered") and not _is_subsequence(spec["ordered"], names):
        reasons.append(f"expected order {spec['ordered']}, got {names}")
    bad = [t for t in spec.get("forbidden") or [] if t in names]
    if bad:
        reasons.append(f"called forbidden tool(s): {bad}")
    return not reasons, reasons


def score_gating(task: dict, calls: list[Call], answer: str, write_tools: set[str]) -> tuple[bool, list[str]]:
    mode = task["approval"]
    writes = [c for c in calls if c.name in write_tools]
    pending = [c for c in writes if PENDING_MARK in (c.observation or "")]
    executed = [c for c in writes if NOTIFY_MARK in (c.observation or "")]
    text = (answer or "").lower()
    reasons = []
    if mode in ("none", "ask") and writes:
        reasons.append(f"expected no writes, but called {[c.name for c in writes]}")
    if mode == "notify" and not executed:
        reasons.append("expected an additive write to execute, none did")
    if mode == "gate":
        if not pending:
            reasons.append("expected a write held as PENDING APPROVAL, none was")
        elif "approv" not in text:
            reasons.append("gated write was held but the answer doesn't tell the user it needs approval")
        repeated = {c.name for c in pending if sum(p.name == c.name for p in pending) > 1}
        if repeated:
            reasons.append(f"retried gated tool(s) after PENDING APPROVAL: {sorted(repeated)}")
    return not reasons, reasons


def score_answer(task: dict, answer: str) -> tuple[bool, list[str]]:
    success = task.get("success") or {}
    text = (answer or "").lower()
    reasons = []
    for s in success.get("answer_contains") or []:
        if str(s).lower() not in text:
            reasons.append(f"answer lacks '{s}'")
    anyof = success.get("answer_contains_any") or []
    if anyof and not any(str(s).lower() in text for s in anyof):
        reasons.append(f"answer contains none of {anyof}")
    for s in success.get("answer_excludes") or []:
        if str(s).lower() in text:
            reasons.append(f"answer contains excluded '{s}'")
    return not reasons, reasons


def score(task: dict, calls: list[Call], answer: str, write_tools: set[str],
          state_results: dict[str, tuple[bool, str]] | None = None) -> Score:
    tools_ok, r1 = score_tools(task, calls)
    gate_ok, r2 = score_gating(task, calls, answer, write_tools)
    ans_ok, r3 = score_answer(task, answer)
    reasons = r1 + r2 + r3
    if state_results is None and (task.get("success") or {}).get("state"):
        success = None if ans_ok else False
    else:
        state_ok = True
        for name, (ok, why) in (state_results or {}).items():
            if not ok:
                state_ok = False
                reasons.append(f"state {name}: {why}")
        success = ans_ok and state_ok
    return Score(tools_ok, gate_ok, success, reasons)
