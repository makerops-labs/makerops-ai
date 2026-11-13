"""Repair the input schemas of MCP tools after mcpadapt converts them.

mcpadapt 0.1.19 (smolagents' MCP adapter) drops two pieces of each MCP
tool's JSON schema:

- It ignores the schema's ``required`` list and never sets smolagents'
  ``nullable`` flag. smolagents treats every non-nullable input as
  **required**, both when validating a call and in the schema it shows the
  model. So every parameter with a default (``status="active"``,
  ``draft=True``, ``max_results=10``) became mandatory.
- For an optional parameter (``mailbox_id: int | None = None`` →
  ``anyOf: [integer, null]``) it adds ``type: "string"`` because there's no
  top-level type. Validation then rejected the correct integer ("has type
  'integer' but should be 'string'") and also demanded the argument.

Observed in the T4 eval baseline (2026-11-13): agents could not call
``freescout_list_conversations`` or ``inventree_list_stock`` at all, and
looped sending empty strings for the integer ids. This module is pure (no
smolagents import) so it can be unit-tested without the agent runtime.
"""

from __future__ import annotations


def normalize_input(spec: dict) -> dict:
    """Return a corrected copy of one smolagents input spec.

    - ``anyOf``: the non-null branches become the ``type`` (one → a string,
      several stay a list, as smolagents allows).
    - A ``default`` means the parameter is optional → ``nullable: True``.
      A null branch without a default is still required (pydantic omits
      ``default`` for required fields), so it stays required.
    - Everything else (description, enum, items, ...) is kept unchanged.
    """
    out = dict(spec)
    branches = out.get("anyOf")
    if isinstance(branches, list) and branches:
        types = [b.get("type", "string") for b in branches if isinstance(b, dict)]
        non_null = [t for t in types if t != "null"]
        # A null branch alone doesn't make a parameter optional
        # (`x: int | None` with no default is still required); only a
        # `default` does, handled below.
        if non_null:
            out["type"] = non_null[0] if len(non_null) == 1 else non_null
        # smolagents re-derives the type from anyOf when it builds the
        # model-facing schema; keep the branches consistent with `type`.
        out["anyOf"] = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"] or branches
        if len(out["anyOf"]) == 1:
            out.pop("anyOf")
    if "default" in out:
        out["nullable"] = True
    return out


def normalize_inputs(inputs: dict[str, dict]) -> dict[str, dict]:
    """Corrected copy of a tool's whole ``inputs`` mapping."""
    return {name: normalize_input(spec) for name, spec in inputs.items()}
