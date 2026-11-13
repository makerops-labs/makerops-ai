"""Shared fixtures for the mcp-tools safety-policy tests.

These tests need no network and no running services: every write executor is
replaced by an in-memory spy, outbound HTTP is blocked, and all state
(approvals, audit log, provenance registry) lives in a per-test temp dir.
"""

import os
import sys
import tempfile
from pathlib import Path

# `tools.config` reads the environment at import time, so point it at a
# throwaway data dir before any test module imports `tools`.
_SESSION_DATA = tempfile.mkdtemp(prefix="mcptools-test-")
os.environ["MCPTOOLS_DATA_DIR"] = _SESSION_DATA
os.environ.setdefault("APPROVALS_TOKEN", "test-token")
for _name in ("APPROVAL_GATE_EXEMPT", "APPROVAL_FORCE_GATE", "APPROVAL_NOTIFY_WEBHOOK"):
    os.environ.pop(_name, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import pytest  # noqa: E402

from tools import config, policy  # noqa: E402


class ExecutorSpy:
    """Stands in for a real write executor and records every call."""

    def __init__(self, result: str = "done"):
        self.calls: list[dict] = []
        self.result = result

    def __call__(self, params: dict) -> str:
        self.calls.append(params)
        return self.result


@pytest.fixture(autouse=True)
def isolated_policy(tmp_path, monkeypatch):
    """Fresh approvals/audit/provenance store and policy config per test."""
    monkeypatch.setattr(policy, "APPROVALS_DIR", tmp_path / "approvals")
    monkeypatch.setattr(policy, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(policy, "PROVENANCE_FILE", tmp_path / "provenance.json")
    monkeypatch.setattr(config, "APPROVAL_GATE_EXEMPT", set())
    monkeypatch.setattr(config, "APPROVAL_FORCE_GATE", set())
    monkeypatch.setattr(config, "APPROVAL_NOTIFY_WEBHOOK", "")
    monkeypatch.setattr(config, "APPROVAL_TTL_HOURS", 24.0)
    monkeypatch.setattr(policy, "_EXECUTORS", dict(policy._EXECUTORS))
    yield tmp_path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if anything under test tries a real HTTP request."""

    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during a unit test")

    # Block the real socket transports only; Starlette's in-process
    # TestClient uses its own transport and keeps working.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked)


@pytest.fixture
def spy_executor(monkeypatch):
    """Register a spy executor for a domain.tool; returns the spy."""

    def _register(domain: str, tool: str, result: str = "done") -> ExecutorSpy:
        spy = ExecutorSpy(result)
        policy.register_executor(domain, tool, spy)
        return spy

    return _register


@pytest.fixture
def notifications(monkeypatch):
    """Capture webhook notifications instead of POSTing them."""
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(policy, "_notify", lambda event, payload: sent.append((event, payload)))
    return sent
