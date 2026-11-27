"""Per-model engine routing (Ollama vs the llama.cpp router) and the
tool_choice omission that keeps llama.cpp from runaway generations."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("smolagents")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the image runs from smolagents/

from smolagents.models import ChatMessage  # noqa: E402

from agents import config, model  # noqa: E402


@pytest.fixture
def routed(monkeypatch):
    monkeypatch.setattr(config, "LLAMACPP_MODELS", frozenset({"qwen3.6:35b-64k"}))
    monkeypatch.setattr(config, "LLAMACPP_API_BASE", "http://llama:8110/v1")
    monkeypatch.setattr(config, "OLLAMA_API_BASE", "http://ollama:11434/v1")


def test_listed_model_goes_to_llamacpp_without_colon(routed):
    assert model.route("qwen3.6:35b-64k") == ("http://llama:8110/v1", "qwen3.6-35b-64k")


def test_unlisted_model_stays_on_ollama_unchanged(routed):
    assert model.route("qwen3.5:9b-64k") == ("http://ollama:11434/v1", "qwen3.5:9b-64k")


def test_default_routes_everything_to_ollama(monkeypatch):
    monkeypatch.setattr(config, "LLAMACPP_MODELS", frozenset())
    assert model.route("qwen3.6:35b-64k")[1] == "qwen3.6:35b-64k"


def test_get_model_uses_route(routed):
    m = model.get_model(model_id="qwen3.6:35b-64k")
    assert m.model_id == "qwen3.6-35b-64k"
    assert str(m.client.base_url).rstrip("/") == "http://llama:8110/v1"


def test_raw_client_uses_route(routed):
    client, name = model.raw_client("qwen3.6:35b-64k")
    assert name == "qwen3.6-35b-64k"
    assert str(client.base_url).rstrip("/") == "http://llama:8110/v1"


def test_tool_choice_is_never_sent(routed):
    from smolagents import tool

    @tool
    def ping(x: str) -> str:
        """Ping.

        Args:
            x: anything
        """
        return x

    m = model.get_model(model_id="qwen3.6:35b-64k")
    msgs = [ChatMessage(role="user", content="hi")]
    with_tools = m._prepare_completion_kwargs(messages=msgs, tools_to_call_from=[ping])
    assert "tools" in with_tools and "tool_choice" not in with_tools
    assert "tool_choice" not in m._prepare_completion_kwargs(messages=msgs)
