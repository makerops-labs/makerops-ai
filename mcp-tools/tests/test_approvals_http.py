"""The human approval endpoints require the APPROVALS_TOKEN."""

import pytest
from starlette.testclient import TestClient

from tools import config, policy

TOKEN = "test-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "APPROVALS_TOKEN", TOKEN)
    import server  # imported lazily: builds the Starlette app at import time

    # No `with` block → the MCP lifespan (session managers) is not started;
    # the approval routes don't need it.
    return TestClient(server.app, follow_redirects=False)


@pytest.fixture
def pending(spy_executor):
    spy = spy_executor("demo", "demo_write")
    result = policy.apply_policy(domain="demo", tool="demo_write", action_kind="effect",
                                 summary="ship it", params={"x": 1})
    return result.split("#", 1)[1].split(":", 1)[0], spy


def test_approvals_page_requires_token(client):
    assert client.get("/approvals").status_code == 401
    assert client.get("/approvals?token=wrong").status_code == 401
    assert client.get(f"/approvals?token={TOKEN}").status_code == 200


def test_valid_token_sets_cookie_for_later_requests(client):
    resp = client.get(f"/approvals?token={TOKEN}")
    assert resp.cookies.get("approvals_token") == TOKEN
    assert client.get("/approvals").status_code == 200  # cookie jar carries it


@pytest.mark.parametrize("verb", ["approve", "reject"])
def test_resolve_without_token_is_refused_and_does_nothing(client, pending, verb):
    action_id, spy = pending
    resp = client.post(f"/approvals/{action_id}/{verb}")
    assert resp.status_code == 401
    assert spy.calls == []
    assert policy.get_action(action_id)["status"] == "pending"


def test_resolve_with_wrong_cookie_is_refused(client, pending):
    action_id, spy = pending
    client.cookies.set("approvals_token", "forged")
    assert client.post(f"/approvals/{action_id}/approve").status_code == 401
    assert spy.calls == []


def test_resolve_with_token_executes(client, pending):
    action_id, spy = pending
    resp = client.post(f"/approvals/{action_id}/approve?token={TOKEN}")
    assert resp.status_code == 303
    assert spy.calls == [{"x": 1}]


def test_empty_token_config_leaves_approvals_open(client, pending, monkeypatch):
    """Documents CURRENT behavior, reported in the PR as a finding.

    With APPROVALS_TOKEN unset/empty, `_authorized()` returns True, so anyone
    who can reach the port can approve gated actions (fail-open). start.sh
    generates a token from the GENERATE_ME placeholder, so this needs a
    misconfiguration to bite — but a safety gate should fail closed. Flip this
    assertion when the fail-closed fix lands.
    """
    monkeypatch.setattr(config, "APPROVALS_TOKEN", "")
    action_id, spy = pending
    assert client.post(f"/approvals/{action_id}/approve").status_code == 303
    assert spy.calls == [{"x": 1}]
