"""The schema repair against the real libraries, not a hand-written mirror.

FastMCP builds the JSON schema → mcpadapt (smolagents' MCP adapter) turns it
into a smolagents Tool → normalize_inputs repairs it → smolagents' own
validate_tool_arguments judges the calls the baseline agents made. Also
checks get_domain_tools actually applies the repair.

Needs the smolagents runtime (`uv run --frozen --project smolagents pytest
smolagents/tests`); skipped where it isn't installed, e.g. the offline
`--no-project` run of test_tool_schema.py.
"""

import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("smolagents")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the image runs from smolagents/
pytest.importorskip("mcpadapt")

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcpadapt.smolagents_adapter import SmolAgentsAdapter  # noqa: E402
from smolagents.tools import validate_tool_arguments  # noqa: E402

from agents import tools as agent_tools  # noqa: E402
from agents.tool_schema import normalize_inputs  # noqa: E402


def _adapted_tool():
    server = FastMCP("t")

    @server.tool()
    def list_conversations(conversation_id: int | None, mailbox_id: int | None = None,
                           status: str = "active", max_results: int = 10) -> str:
        """Same shape as freescout_list_conversations, plus one required X|None."""
        return "ok"

    mcp_tool = asyncio.run(server.list_tools())[0]
    return SmolAgentsAdapter().adapt(lambda args: "ok", mcp_tool)


def _valid(tool, args) -> bool:
    try:
        validate_tool_arguments(tool, args)
        return True
    except (TypeError, ValueError):
        return False


def test_unrepaired_adapter_output_rejects_correct_calls():
    # Guards the premise: if a smolagents/mcpadapt upgrade fixes this
    # upstream, this test fails and the repair can be reconsidered.
    tool = _adapted_tool()
    assert not _valid(tool, {"conversation_id": 1, "mailbox_id": 1})


def test_repaired_schema_accepts_the_baseline_calls():
    tool = _adapted_tool()
    tool.inputs = normalize_inputs(tool.inputs)
    assert _valid(tool, {"conversation_id": 7, "mailbox_id": 1, "status": "active", "max_results": 50})
    assert _valid(tool, {"conversation_id": 7})           # defaulted args may be omitted
    assert not _valid(tool, {"mailbox_id": 1})            # required X|None stays required
    # Known limit: smolagents' single `nullable` flag means "may be omitted"
    # AND "may be null", so a required X|None can't also accept an explicit
    # None. No mcp-tools tool has that shape (all X|None params default).
    assert not _valid(tool, {"conversation_id": None})
    assert not _valid(tool, {"conversation_id": "7"})     # wrong type still rejected


def test_get_domain_tools_applies_the_repair(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_tools(self):
            return [_adapted_tool()]

    monkeypatch.setattr(agent_tools, "MCPClient", FakeClient)
    monkeypatch.setattr(agent_tools, "_mounted_domains", lambda: {"freescout"})
    monkeypatch.setattr(agent_tools, "_domain_tools_cache", {})
    monkeypatch.setattr(agent_tools, "_clients", [])
    [tool] = agent_tools.get_domain_tools("freescout")
    assert tool.inputs["mailbox_id"] == {**tool.inputs["mailbox_id"], "type": "integer", "nullable": True}
    assert _valid(tool, {"conversation_id": 7})


def test_get_domain_tools_keeps_a_tool_whose_schema_cannot_be_repaired(monkeypatch):
    class Odd:
        name = "odd"
        inputs = {"x": "not-a-dict"}  # normalize_input raises on this

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_tools(self):
            return [Odd()]

    monkeypatch.setattr(agent_tools, "MCPClient", FakeClient)
    monkeypatch.setattr(agent_tools, "_mounted_domains", lambda: {"d"})
    monkeypatch.setattr(agent_tools, "_domain_tools_cache", {})
    monkeypatch.setattr(agent_tools, "_clients", [])
    [tool] = agent_tools.get_domain_tools("d")
    assert tool.inputs == {"x": "not-a-dict"}
