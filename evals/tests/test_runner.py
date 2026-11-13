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
