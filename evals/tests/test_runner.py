"""Offline tests for run.py's resilience: setup retries, per-task saves,
resume, and infra errors kept out of the scores."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run  # noqa: E402


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    return tmp_path


def _proc(code, err=""):
    return subprocess.CompletedProcess([], code, stdout="", stderr=err)


def test_demo_retries_then_succeeds(results, monkeypatch):
    outcomes = iter([_proc(1, "TimeoutError: timed out"), _proc(0)])
    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: next(outcomes))
    run._demo("seed.py")  # no exception: second attempt worked


def test_demo_raises_setup_error_after_all_attempts(results, monkeypatch):
    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: _proc(1, "TimeoutError: timed out"))
    with pytest.raises(run.SetupError, match="timed out"):
        run._demo("seed.py", attempts=2)


def test_save_is_complete_json_and_resume_finds_it(results):
    path = run._results_path("qwen3.6:35b-64k", resume=False)
    run._save(path, "qwen3.6:35b-64k", [{"id": "a", "passed": True}])
    assert json.loads(path.read_text())["tasks"] == [{"id": "a", "passed": True}]
    assert run._results_path("qwen3.6:35b-64k", resume=True) == path
    assert not list(results.glob("*.tmp"))


def test_report_excludes_infra_errors(results, monkeypatch):
    task = lambda i, c, ok: {"id": i, "class": c, "passed": ok, "tool_selection": ok,  # noqa: E731
                             "gating": True, "success": ok, "latency_s": 10.0}
    run._save(results / "2026-11-13-m.json", "m", [
        task("t1", "read", True), task("t2", "read", False),
        {"id": "t3", "class": "gated", "infra_error": "seed failed", "passed": None},
    ])
    here = results / "here"
    here.mkdir()
    monkeypatch.setattr(run, "HERE", here)
    doc = {"tasks": [{"id": i, "reviewed": True} for i in ("t1", "t2", "t3")]}
    assert run.report(doc) == 0
    row = [ln for ln in (here / "RESULTS.md").read_text().splitlines() if ln.startswith("| `m`")][0]
    assert "| 50% |" in row and "2/3 (1 infra)" in row


def test_resume_matches_exact_model_and_current_tasks(results):
    run._save(results / "2026-11-13-qwen3.6_35b.json", "qwen3.6:35b",
              [{"id": "t1", "passed": True}, {"id": "gone", "passed": True},
               {"id": "t2", "infra_error": "x", "passed": None}])
    run._save(results / "2026-11-13-bar-qwen3.6_35b.json", "bar-qwen3.6:35b", [{"id": "t1"}])
    path = run._results_path("qwen3.6:35b", resume=True)
    assert path.name == "2026-11-13-qwen3.6_35b.json"
    rows = run._resumable_rows(path, "qwen3.6:35b", {"t1", "t2"})
    assert [r["id"] for r in rows] == ["t1"]          # stale task dropped, infra retried
    with pytest.raises(SystemExit):
        run._resumable_rows(path, "other:model", {"t1"})


def test_fresh_run_keeps_previous_file(results, monkeypatch):
    path = run._results_path("m", resume=False)
    run._save(path, "m", [{"id": "t1", "passed": True}])
    again = run._results_path("m", resume=False)
    assert again == path and not path.exists()
    assert json.loads(path.with_name(path.name + ".prev").read_text())["tasks"][0]["id"] == "t1"


def _stub_stack(monkeypatch, behaviours: dict):
    """Stand-ins for the agent runtime so run_live's loop runs offline.
    behaviours: task id → "ok" | "crash" | "setup-fail"."""
    import types
    from types import SimpleNamespace

    order = list(behaviours)        # tasks run in doc order
    seeds = []

    class Agent:
        def run(self, prompt, **kwargs):
            if behaviours[prompt] == "crash":
                raise ConnectionError("Ollama connection reset")
            return f"answer to {prompt}"

    agents_pkg = types.ModuleType("agents")
    agents_pkg.config = SimpleNamespace(GENERAL_MODEL_ID="")
    ops = types.ModuleType("agents.ops_agent")
    ops.build_ops_agent = Agent
    for name, mod in {"agents": agents_pkg, "agents.config": agents_pkg.config,
                      "agents.ops_agent": ops}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(sys, "path", list(sys.path))  # run_live prepends smolagents/

    def demo(script, **kwargs):
        if script == "seed.py":
            seeds.append(script)
            task = order[len(seeds) - 1] if len(seeds) <= len(order) else None
            if behaviours.get(task) == "setup-fail":
                raise run.SetupError("demo/seed.py failed 3 times: TimeoutError")

    class State:
        def setup(self, name):
            pass

        def check(self, name, arg, calls):
            return True, ""

    monkeypatch.setattr(run, "_demo", demo)
    monkeypatch.setattr(run, "State", State)
    monkeypatch.setattr(run, "tool_inventory", lambda: (set(), set()))
    monkeypatch.setattr(run, "_pending", lambda: {})
    monkeypatch.setattr(run, "_reject", lambda ids: None)
    monkeypatch.setattr(run, "_capture", lambda agent: [])
    monkeypatch.setattr(run, "score", lambda *a: SimpleNamespace(
        passed=True, tool_selection=True, gating=True, success=True, reasons=[]))
    monkeypatch.setattr(run, "ROOT", run.RESULTS_DIR)  # relative_to() in log lines


def _doc(*ids):
    return {"tasks": [{"id": i, "class": "read", "prompt": i} for i in ids]}


def test_run_live_records_infra_errors_and_keeps_going(results, monkeypatch):
    _stub_stack(monkeypatch, {"t1": "ok", "t2": "crash", "t3": "setup-fail", "t4": "ok"})
    out = run.run_live(_doc("t1", "t2", "t3", "t4"), "m", only=None)
    rows = {r["id"]: r for r in json.loads(out.read_text())["tasks"]}
    assert rows["t1"]["passed"] is True and rows["t4"]["passed"] is True
    assert rows["t2"]["passed"] is None and "ConnectionError" in rows["t2"]["infra_error"]
    assert rows["t3"]["passed"] is None and "seed.py" in rows["t3"]["infra_error"]


def test_run_live_resume_retries_only_infra_rows(results, monkeypatch):
    behaviours = {"t1": "ok", "t2": "crash"}
    _stub_stack(monkeypatch, behaviours)
    out = run.run_live(_doc("t1", "t2"), "m", only=None)
    first_t1 = json.loads(out.read_text())["tasks"][0]
    behaviours["t2"] = "ok"                      # the stack is healthy again
    run.run_live(_doc("t1", "t2"), "m", only=None, resume=True)
    rows = {r["id"]: r for r in json.loads(out.read_text())["tasks"]}
    assert rows["t1"] == first_t1                # scored task not re-run
    assert rows["t2"]["passed"] is True and "infra_error" not in rows["t2"]
