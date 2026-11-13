"""Every model-facing write tool is routed through the policy layer.

The policy tests prove the gate works; these prove tools can't bypass it.
"""

import ast
import asyncio
from pathlib import Path

import pytest

from tools import policy

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"


def _write_tools():
    """(module, function) for every function whose docstring declares a write."""
    found = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (ast.get_docstring(node) or "").startswith("WRITE ACTION"):
                    found.append((path.name, node))
    return found


def _calls(fn_node) -> set[str]:
    names = set()
    for n in ast.walk(fn_node):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return names


def test_write_tools_exist():
    # Guards the guard: if the docstring convention changes, this test (and
    # the one below) would silently check nothing.
    assert len(_write_tools()) >= 20


@pytest.mark.parametrize("module,fn", [(m, f.name) for m, f in _write_tools()])
def test_write_tool_routes_through_apply_policy(module, fn):
    node = next(f for m, f in _write_tools() if m == module and f.name == fn)
    assert "apply_policy" in _calls(node), (
        f"{module}:{fn} is documented as a WRITE ACTION but never calls "
        f"policy.apply_policy — it would bypass approval gating")


def test_no_tool_hardcodes_a_delete_bypass():
    # Deletions must always gate; nothing may pass a non-literal action_kind
    # that could be steered to something weaker at runtime.
    for path in sorted(TOOLS_DIR.glob("*.py")):
        if path.name == "policy.py":
            continue
        for n in ast.walk(ast.parse(path.read_text())):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "apply_policy":
                kinds = [k.value for k in n.keywords if k.arg == "action_kind"]
                assert kinds, f"{path.name}:{n.lineno} apply_policy without action_kind"
                assert isinstance(kinds[0], ast.Constant), (
                    f"{path.name}:{n.lineno} action_kind is computed, not a literal")


# ── End-to-end through a real tool module (HTTP blocked by conftest) ────────

def _tool_fn(tool):
    return getattr(tool, "fn", tool)


def test_inventree_stock_adjustment_is_held_until_approved(spy_executor):
    from tools import inventree

    spy = spy_executor("inventree", "inventree_adjust_stock", result="adjusted")
    fn = _tool_fn(inventree.inventree_adjust_stock)
    result = fn(stock_item_id=7, quantity=3, action="remove", notes="demo")
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    assert result.startswith("PENDING APPROVAL #"), result
    assert spy.calls == [], "stock moved before a human approved it"

    action_id = result.split("#", 1)[1].split(":", 1)[0]
    assert policy.resolve_action(action_id, approve=True)[0]
    assert spy.calls == [{"stock_item_id": 7, "quantity": 3,
                          "action": "remove", "notes": "demo"}]
