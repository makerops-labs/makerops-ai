"""Offline tests for agents/tool_schema.py (no smolagents import needed)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "tool_schema", Path(__file__).resolve().parents[1] / "agents" / "tool_schema.py")
tool_schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool_schema)
normalize_input = tool_schema.normalize_input
normalize_inputs = tool_schema.normalize_inputs

# Exactly what mcpadapt 0.1.19 produced for freescout_list_conversations
# during the 2026-11-13 baseline.
MANGLED = {
    "mailbox_id": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None,
                   "description": "see tool description", "type": "string"},
    "status": {"default": "active", "type": "string", "description": "see tool description"},
    "max_results": {"default": 10, "type": "integer", "description": "see tool description"},
}


def test_optional_int_becomes_nullable_integer():
    fixed = normalize_input(MANGLED["mailbox_id"])
    assert fixed["type"] == "integer" and fixed["nullable"] is True
    assert "anyOf" not in fixed
    assert fixed["description"] == "see tool description"


def test_defaulted_params_are_optional():
    fixed = normalize_inputs(MANGLED)
    assert all(spec.get("nullable") for spec in fixed.values())


def test_required_param_untouched():
    spec = {"type": "integer", "description": "conversation id"}
    assert normalize_input(spec) == spec


def test_union_of_two_types_keeps_both():
    spec = {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}], "type": "string"}
    fixed = normalize_input(spec)
    assert fixed["type"] == ["integer", "string"] and not fixed.get("nullable")
    assert [b["type"] for b in fixed["anyOf"]] == ["integer", "string"]


def test_input_not_mutated():
    before = {k: dict(v) for k, v in MANGLED.items()}
    normalize_inputs(MANGLED)
    assert MANGLED == before


def _smolagents_validate(inputs, arguments):
    """Mirror of smolagents 1.26 validate_tool_arguments (dict branch)."""
    for key, value in arguments.items():
        actual = {int: "integer", str: "string", bool: "boolean", float: "number",
                  type(None): "null"}[type(value)]
        expected = inputs[key]["type"]
        ok = actual == expected if isinstance(expected, str) else actual in expected
        if not ok and not (actual == "null" and inputs[key].get("nullable")):
            raise TypeError(f"{key}: {actual} != {expected}")
    for key, spec in inputs.items():
        if key not in arguments and not spec.get("nullable"):
            raise ValueError(f"Argument {key} is required")


def test_calls_that_failed_in_the_baseline_now_validate():
    fixed = normalize_inputs(MANGLED)
    _smolagents_validate(fixed, {"mailbox_id": 1, "status": "active", "max_results": 50})
    _smolagents_validate(fixed, {"status": "active", "max_results": 20})
    _smolagents_validate(fixed, {})


def test_required_optional_typed_param_stays_required():
    # `x: int | None` with no default: pydantic emits anyOf with null but no default.
    fixed = normalize_input({"anyOf": [{"type": "integer"}, {"type": "null"}], "type": "string"})
    assert fixed["type"] == "integer" and not fixed.get("nullable")
