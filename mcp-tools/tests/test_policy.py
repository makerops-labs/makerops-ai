"""Tiered write policy: gate-before vs notify-after, overrides, expiry."""

import time

import pytest

from tools import config, policy


def _call(kind, *, domain="demo", tool="demo_write", target_id=None, **kw):
    return policy.apply_policy(domain=domain, tool=tool, action_kind=kind,
                               summary=f"{kind} something", params={"x": 1},
                               target_id=target_id, **kw)


def _pending_id(result: str) -> str:
    assert result.startswith("PENDING APPROVAL #"), result
    return result.split("#", 1)[1].split(":", 1)[0]


# ── Gated actions never execute before approval ──────────────────────────────

@pytest.mark.parametrize("kind", ["delete", "effect"])
def test_destructive_kinds_are_held_and_do_not_execute(kind, spy_executor, notifications):
    spy = spy_executor("demo", "demo_write")
    result = _call(kind)
    assert result.startswith("PENDING APPROVAL #")
    assert spy.calls == [], "gated action executed before approval"
    action = policy.get_action(_pending_id(result))
    assert action["status"] == "pending"
    assert [e for e, _ in notifications] == ["action.pending"]


def test_update_of_user_content_is_gated(spy_executor):
    spy = spy_executor("demo", "demo_write")
    result = _call("update", target_id="doc-1")  # no provenance → user-owned
    assert result.startswith("PENDING APPROVAL #")
    assert spy.calls == []


def test_update_of_agent_created_content_is_notify(spy_executor):
    spy = spy_executor("demo", "demo_write")
    policy.record_created("demo", "doc-1")
    result = _call("update", target_id="doc-1")
    assert not result.startswith("PENDING APPROVAL")
    assert len(spy.calls) == 1


def test_update_without_target_id_is_gated(spy_executor):
    spy = spy_executor("demo", "demo_write")
    assert _call("update").startswith("PENDING APPROVAL #")
    assert spy.calls == []


def test_unknown_action_kind_falls_back_to_gate(spy_executor):
    spy = spy_executor("demo", "demo_write")
    assert _call("frobnicate").startswith("PENDING APPROVAL #")
    assert spy.calls == []


def test_unregistered_tool_is_refused_not_executed():
    result = _call("create", tool="never_registered")
    assert result.startswith("ERROR: no executor registered")
    assert policy.list_actions() == []


# ── Additive actions execute and notify ──────────────────────────────────────

def test_create_executes_immediately_and_notifies(spy_executor, notifications):
    spy = spy_executor("demo", "demo_write", result="created ok")
    result = _call("create")
    assert result.startswith("created ok")
    assert "executed immediately" in result
    assert spy.calls == [{"x": 1}]
    assert [e for e, _ in notifications] == ["action.completed"]
    assert policy.read_audit()[0]["event"] == "action.completed"


def test_create_records_provenance_from_executor_result(spy_executor):
    spy_executor("demo", "demo_write", result="OBJECT_ID=42\nmade it")
    result = _call("create", created_object_id_from_result=True)
    assert result.startswith("made it")
    assert policy.is_agent_owned("demo", "42")


def test_failed_notify_execution_is_not_reported_as_success(spy_executor, notifications):
    spy_executor("demo", "demo_write", result="ERROR: upstream said no")
    assert _call("create") == "ERROR: upstream said no"
    assert notifications == []

def test_notify_executor_crash_is_audited_not_raised(notifications):
    def boom(params):
        raise RuntimeError("upstream exploded")

    policy.register_executor("demo", "demo_write", boom)
    result = _call("create")
    assert result == "ERROR: demo.demo_write failed: upstream exploded"
    assert notifications == [], "a crashed write must not be reported as completed"
    entry = policy.read_audit()[0]
    assert entry["event"] == "action.failed" and "upstream exploded" in entry["error"]

# ── Per-tool overrides from env ──────────────────────────────────────────────

@pytest.mark.parametrize("entry", ["demo", "demo.demo_write"])
def test_force_gate_upgrades_notify_to_gate(entry, spy_executor, monkeypatch):
    monkeypatch.setattr(config, "APPROVAL_FORCE_GATE", {entry})
    spy = spy_executor("demo", "demo_write")
    assert _call("create").startswith("PENDING APPROVAL #")
    assert spy.calls == []


@pytest.mark.parametrize("entry", ["demo", "demo.demo_write"])
def test_gate_exempt_downgrades_effect_to_notify(entry, spy_executor, monkeypatch):
    monkeypatch.setattr(config, "APPROVAL_GATE_EXEMPT", {entry})
    spy = spy_executor("demo", "demo_write")
    assert not _call("effect").startswith("PENDING APPROVAL")
    assert len(spy.calls) == 1


def test_gate_exempt_never_applies_to_delete(spy_executor, monkeypatch):
    monkeypatch.setattr(config, "APPROVAL_GATE_EXEMPT", {"demo", "demo.demo_write"})
    spy = spy_executor("demo", "demo_write")
    assert _call("delete").startswith("PENDING APPROVAL #")
    assert spy.calls == []


def test_override_for_other_tool_does_not_leak(spy_executor, monkeypatch):
    monkeypatch.setattr(config, "APPROVAL_GATE_EXEMPT", {"demo.other_tool"})
    spy = spy_executor("demo", "demo_write")
    assert _call("effect").startswith("PENDING APPROVAL #")
    assert spy.calls == []


def test_overrides_are_parsed_from_env_strings():
    # Mirrors config.py's parsing of comma-separated env values.
    raw = " inventree , freescout.freescout_reply ,, "
    parsed = {e.strip() for e in raw.split(",") if e.strip()}
    assert parsed == {"inventree", "freescout.freescout_reply"}


# ── Approval lifecycle ───────────────────────────────────────────────────────

def test_approve_executes_exactly_once(spy_executor):
    spy = spy_executor("demo", "demo_write")
    action_id = _pending_id(_call("effect"))
    ok, _ = policy.resolve_action(action_id, approve=True)
    assert ok and spy.calls == [{"x": 1}]
    assert policy.get_action(action_id)["status"] == "approved"
    ok, msg = policy.resolve_action(action_id, approve=True)
    assert not ok and "already approved" in msg
    assert len(spy.calls) == 1


def test_reject_never_executes(spy_executor):
    spy = spy_executor("demo", "demo_write")
    action_id = _pending_id(_call("effect"))
    ok, _ = policy.resolve_action(action_id, approve=False)
    assert ok and spy.calls == []
    assert policy.get_action(action_id)["status"] == "rejected"
    assert not policy.resolve_action(action_id, approve=True)[0]
    assert spy.calls == []


def test_approved_overwrite_re_gates_future_overwrites(spy_executor):
    spy = spy_executor("demo", "demo_write")
    policy.record_created("demo", "doc-1")  # agent-owned → notify
    action_id = _pending_id(_call("update", target_id="doc-9"))  # user-owned
    policy.resolve_action(action_id, approve=True)
    assert not policy.is_agent_owned("demo", "doc-9")
    assert _call("update", target_id="doc-9").startswith("PENDING APPROVAL #")
    assert len(spy.calls) == 1


def test_executor_exception_marks_action_failed(spy_executor):
    def boom(params):
        raise RuntimeError("tool bug")

    policy.register_executor("demo", "demo_write", boom)
    action_id = _pending_id(_call("effect"))
    ok, msg = policy.resolve_action(action_id, approve=True)
    assert not ok and "tool bug" in msg
    assert policy.get_action(action_id)["status"] == "failed"


# ── Expiry ───────────────────────────────────────────────────────────────────

def _age_action(action_id: str, hours: float) -> None:
    action = policy._load_action(action_id)
    action["created_ts"] = time.time() - hours * 3600
    policy._save_action(action)


def test_expired_approval_cannot_execute(spy_executor):
    spy = spy_executor("demo", "demo_write")
    action_id = _pending_id(_call("effect"))
    _age_action(action_id, config.APPROVAL_TTL_HOURS + 0.1)
    ok, msg = policy.resolve_action(action_id, approve=True)
    assert not ok and "expired" in msg
    assert spy.calls == []
    assert policy.get_action(action_id)["status"] == "expired"
    assert policy.list_actions(status="pending") == []


def test_approval_within_ttl_still_executes(spy_executor):
    spy = spy_executor("demo", "demo_write")
    action_id = _pending_id(_call("effect"))
    _age_action(action_id, config.APPROVAL_TTL_HOURS - 0.1)
    assert policy.resolve_action(action_id, approve=True)[0]
    assert len(spy.calls) == 1


def test_ttl_is_read_from_config(spy_executor, monkeypatch):
    monkeypatch.setattr(config, "APPROVAL_TTL_HOURS", 1.0)
    spy_executor("demo", "demo_write")
    action_id = _pending_id(_call("effect"))
    _age_action(action_id, 1.5)
    assert policy.get_action(action_id)["status"] == "expired"
