"""freescout_reply: drafts run at once as staff drafts; sends wait for approval."""

import pytest

from tools import freescout as fs
from tools import policy


def fn(tool):
    return getattr(tool, "fn", tool)


@pytest.fixture
def posts(monkeypatch):
    sent = []

    def fake_req(method, path, json=None, **_):
        sent.append((method, path, json))
        return True, {}

    monkeypatch.setattr(fs, "_req", fake_req)
    return sent


def test_draft_is_a_staff_message_saved_immediately(posts):
    out = fn(fs.freescout_reply)(conversation_id=42, text="We have 8 ready.")
    assert "Draft reply saved" in out
    [(method, path, payload)] = posts
    assert (method, path) == ("POST", "/api/conversations/42/threads")
    # FreeScout stores an unknown type such as "reply" as a CUSTOMER thread.
    assert payload["type"] == "message" and payload["state"] == "draft"


def test_send_waits_for_approval_then_publishes_a_staff_message(posts):
    out = fn(fs.freescout_reply)(conversation_id=42, text="Shipping today.", draft=False)
    assert out.startswith("PENDING APPROVAL #") and posts == []

    action_id = out.split("#", 1)[1].split(":", 1)[0]
    assert policy.resolve_action(action_id, approve=True)[0]
    [(_, path, payload)] = posts
    assert path == "/api/conversations/42/threads"
    assert payload["type"] == "message" and payload["state"] == "published"


def test_rejected_send_posts_nothing(posts):
    out = fn(fs.freescout_reply)(conversation_id=42, text="Shipping today.", draft=False)
    action_id = out.split("#", 1)[1].split(":", 1)[0]
    policy.resolve_action(action_id, approve=False)
    assert posts == []
