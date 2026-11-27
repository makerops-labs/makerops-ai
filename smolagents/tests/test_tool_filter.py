"""Per-task tool filtering: selector ranking modes, failure fallback, and the
agent's per-run tool swap. No network: embeddings are a fake keyword model."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("smolagents")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the image runs from smolagents/

from smolagents import ToolCallingAgent, tool  # noqa: E402

from agents.tool_filter import ToolFilteringAgent, ToolSelector  # noqa: E402

VOCAB = ["stock", "part", "order", "email", "ticket", "wiki", "issue"]


def fake_embed(texts):
    """Bag-of-keywords vectors: similarity = shared vocabulary."""
    return [[float(w in t.lower()) + 1e-6 for w in VOCAB] for t in texts]


def T(name, description):
    return SimpleNamespace(name=name, description=description)


DOMAINS = {
    "inventree": [T("inv_search", "search part stock"), T("inv_po", "create purchase order for part"),
                  T("inv_adjust", "adjust stock of a part")],
    "freescout": [T("fs_reply", "reply to email ticket"), T("fs_list", "list email ticket")],
    "outline": [T("wiki_search", "search wiki")],
    "plane": [T("plane_issue", "create issue")],
}
ALWAYS = [T("current_datetime", "clock"), T("approval_status", "approval")]


def names(tools):
    return {t.name for t in tools}


def test_topk_returns_only_top_tools_plus_always():
    sel = ToolSelector(DOMAINS, always=ALWAYS, mode="topk", k=1, embed=fake_embed)
    chosen = names(sel.select("reply to the customer email"))
    assert chosen == {"fs_reply", "current_datetime", "approval_status"} or \
        chosen == {"fs_list", "current_datetime", "approval_status"}


def test_domain_mode_pulls_in_whole_domain_including_risky_tools():
    sel = ToolSelector(DOMAINS, always=ALWAYS, mode="domain", k=1, embed=fake_embed)
    chosen = names(sel.select("how much stock of part EN-100?"))
    # every inventree tool stays visible (incl. the write the task may need to decline)
    assert {"inv_search", "inv_po", "inv_adjust"} <= chosen
    assert not chosen & {"fs_reply", "fs_list", "wiki_search", "plane_issue"}
    assert {"current_datetime", "approval_status"} <= chosen


def test_shared_tools_are_not_candidates_twice():
    shared = T("tools_help", "help")
    domains = {"a": [shared, T("x", "stock")], "b": [shared, T("y", "email")]}
    sel = ToolSelector(domains, always=[shared], mode="topk", k=5, embed=fake_embed)
    assert set(sel.candidates) == {"x", "y"}


def test_embedding_failure_exposes_everything():
    def boom(_):
        raise ConnectionError("ollama down")
    sel = ToolSelector(DOMAINS, always=ALWAYS, mode="topk", k=1, embed=boom)
    assert len(sel.select("anything")) == sum(len(v) for v in DOMAINS.values()) + len(ALWAYS)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        ToolSelector(DOMAINS, mode="nope", embed=fake_embed)


# --- agent integration: tools swap per fresh run, never on continuation ---

@tool
def search_stock(part: str) -> str:
    """Search part stock.

    Args:
        part: part name
    """
    return part


@tool
def reply_email(text: str) -> str:
    """Reply to an email ticket.

    Args:
        text: reply body
    """
    return text


def _agent(monkeypatch):
    seen = []
    monkeypatch.setattr(ToolCallingAgent, "run",
                        lambda self, task, *a, **k: seen.append(set(self.tools)) or "ok")
    selector = ToolSelector({"inv": [search_stock], "fs": [reply_email]},
                            mode="topk", k=1, embed=fake_embed)
    agent = ToolFilteringAgent(tools=[search_stock, reply_email],
                               model=SimpleNamespace(model_id="fake"), selector=selector)
    return agent, seen


def test_agent_filters_per_run_and_keeps_final_answer(monkeypatch):
    agent, seen = _agent(monkeypatch)
    agent.run("check stock of part X")
    agent.run("reply to the email ticket")
    assert seen[0] == {"search_stock", "final_answer"}
    assert seen[1] == {"reply_email", "final_answer"}


def test_agent_keeps_tools_on_continuation(monkeypatch):
    agent, seen = _agent(monkeypatch)
    agent.run("check stock of part X")
    agent.run("now reply to the email ticket", reset=False)
    assert seen[1] == seen[0]


def test_no_selector_means_no_filtering(monkeypatch):
    seen = []
    monkeypatch.setattr(ToolCallingAgent, "run",
                        lambda self, task, *a, **k: seen.append(set(self.tools)) or "ok")
    agent = ToolFilteringAgent(tools=[search_stock, reply_email],
                               model=SimpleNamespace(model_id="fake"))
    agent.run("check stock")
    assert seen[0] == {"search_stock", "reply_email", "final_answer"}
