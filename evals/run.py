#!/usr/bin/env python3
"""Agent evaluation harness for the D1 order-fulfillment scenario.

  # Validate tasks.yaml (no GPU, no services). Runs in CI.
  uv run --with pyyaml python evals/run.py --dry-run

  # Run every task against a model through the real `ops` agent
  # (needs: Ollama, mcp-tools on :8099 with the InvenTree PO tools deployed,
  #  InvenTree + FreeScout, demo/.env). Uses smolagents' own environment:
  uv run --project smolagents --with pyyaml python evals/run.py --model qwen3.6:35b-64k

  # Regenerate RESULTS.md from evals/results/*.json (refuses while any task
  # in tasks.yaml is unreviewed).
  uv run --with pyyaml python evals/run.py --report

Each task runs on a freshly reset + seeded demo. Approvals the agent creates
during a task are rejected afterwards, so they never reach a human's queue.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "demo"))

from scoring import Call, rescore_answer, score, tool_inventory, validate  # noqa: E402

RESULTS_DIR = HERE / "results"


def load_tasks(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


# ── dry run ──────────────────────────────────────────────────────────────────

def dry_run(doc: dict) -> int:
    tools, writes = tool_inventory()
    errors = validate(doc, tools)
    tasks = doc.get("tasks") or []
    by_class = {}
    for t in tasks:
        by_class[t.get("class")] = by_class.get(t.get("class"), 0) + 1
    unreviewed = [t["id"] for t in tasks if not t.get("reviewed")]
    print(f"{len(tasks)} tasks: " + ", ".join(f"{k} {v}" for k, v in sorted(by_class.items())))
    print(f"{len(tools)} MCP tools known ({len(writes)} write tools)")
    print(f"{len(unreviewed)} task(s) awaiting human review")
    for e in errors:
        print(f"ERROR: {e}")
    print("dry run OK" if not errors else f"dry run FAILED ({len(errors)} errors)")
    return 1 if errors else 0


# ── live run helpers ─────────────────────────────────────────────────────────

class SetupError(RuntimeError):
    """The demo reset/seed failed: an infrastructure problem, not a model one."""


def _demo(script: str, attempts: int = 3, backoff_s: float = 15) -> None:
    """Run demo/<script>, retrying transient failures (a FreeScout timeout
    once aborted a whole model's run). Raises SetupError if all attempts fail."""
    for n in range(1, attempts + 1):
        proc = subprocess.run([sys.executable, str(ROOT / "demo" / script)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0:
            return
        last = (proc.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
        print(f"  demo/{script} failed (attempt {n}/{attempts}): {last[0]}", flush=True)
        if n < attempts:
            time.sleep(backoff_s * n)
    raise SetupError(f"demo/{script} failed {attempts} times: {last[0]}")


def _results_path(model: str, resume: bool) -> Path:
    """Today's results file, or with --resume the newest existing one for the model."""
    safe = model.replace(":", "_").replace("/", "_")
    if resume:
        existing = sorted(p for p in RESULTS_DIR.glob(f"????-??-??-{safe}.json")
                          if p.name[11:] == f"{safe}.json")
        if existing:
            return existing[-1]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = RESULTS_DIR / f"{stamp}-{safe}.json"
    if not resume and path.exists():  # a fresh run never silently destroys one
        path.replace(path.with_name(path.name + ".prev"))
    return path


def _resumable_rows(path: Path, model: str, task_ids: set[str]) -> list[dict]:
    """Scored rows from a previous run of the same model and current tasks.
    Infra errors are dropped so they are retried."""
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if data.get("model") != model:
        raise SystemExit(f"{path.name} holds results for {data.get('model')!r}, not {model!r}")
    return [r for r in data.get("tasks", [])
            if r.get("id") in task_ids and not r.get("infra_error")]


def _save(path: Path, model: str, rows: list[dict]) -> None:
    """Write after every task (atomically), so a crash loses at most one task."""
    RESULTS_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"model": model, "date": path.name[:10], "agent": "ops",
                               "tasks": rows}, indent=1))
    tmp.replace(path)


def _env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def _approvals_dir() -> Path:
    env = _env_file(ROOT / "mcp-tools" / ".env")
    data = env.get("MCPTOOLS_DATA_PATH") or "./data/mcp-tools"
    return (ROOT / "mcp-tools" / data).resolve() / "approvals"


def _pending() -> dict[str, str]:
    """Pending approval id → "domain.tool"."""
    out = {}
    for p in _approvals_dir().glob("*.json"):
        try:
            a = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if a.get("status") == "pending":
            out[p.stem] = a.get("tool", "")
    return out


def _reject(ids: set[str]) -> None:
    """Reject approvals the eval created, via the real human endpoint.

    The token goes in the cookie the server already accepts, never in the URL:
    uvicorn's access log records request paths, query string included."""
    env = _env_file(ROOT / "mcp-tools" / ".env")
    token = os.environ.get("APPROVALS_TOKEN") or env.get("APPROVALS_TOKEN", "")
    port = env.get("MCPTOOLS_PORT", "8099")
    for action_id in ids:
        req = urllib.request.Request(
            f"http://localhost:{port}/approvals/{action_id}/reject",
            method="POST", data=b"", headers={"Cookie": f"approvals_token={token}"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as exc:  # noqa: BLE001 — leftover approvals just expire
            print(f"    (could not reject eval approval {action_id}: {exc})")


def _capture(agent) -> list[Call]:
    calls = []
    for step in getattr(agent.memory, "steps", []):
        obs = getattr(step, "observations", "") or ""
        for tc in getattr(step, "tool_calls", None) or []:
            if tc.name == "final_answer":
                continue
            calls.append(Call(tc.name, getattr(tc, "arguments", None), obs))
    return calls


# ── state checks (live demo data) ────────────────────────────────────────────

class State:
    def __init__(self):
        from _api import freescout, inventree, load_env, results
        env = load_env()
        self.inv, self.fs, self.results = inventree(env), freescout(env), results
        self.baseline = self._stock_by_ipn()

    def conversations(self) -> set[int]:
        """Ids of every conversation in the demo-only mailbox."""
        from _api import find_mailbox
        box = find_mailbox(self.fs)
        if not box:
            return set()
        page = self.fs.get("/api/conversations", mailboxId=box["id"], pageSize=100)
        return {c["id"] for c in page.get("_embedded", {}).get("conversations", [])
                if c.get("mailboxId") == box["id"]}

    def delete_conversations(self, ids: set[int]) -> None:
        """Delete conversations an agent created during a task. demo/reset.py
        only removes the demo customer's conversations, so one an agent opens
        for another address would otherwise survive and leak into later tasks
        (seen 2026-11-25: a stray conversation collected drafts from three runs)."""
        for cid in sorted(ids):
            try:
                self.fs.delete(f"/api/conversations/{cid}")
            except Exception as exc:  # noqa: BLE001 - cleanup must not stop the run
                print(f"  warning: could not delete conversation {cid}: {exc}", flush=True)

    def _part_pk(self, ipn):
        return next((p["pk"] for p in self.results(self.inv.get("/api/part/", IPN=ipn))
                     if p.get("IPN") == ipn), None)

    def _stock_by_ipn(self) -> dict:
        out = {}
        for p in self.results(self.inv.get("/api/part/")):
            if (p.get("IPN") or "").startswith("DEMO-"):
                out[p["IPN"]] = p.get("unallocated_stock") or p.get("in_stock")
        return out

    def _pos(self):
        return self.results(self.inv.get("/api/order/po/"))

    def check(self, name: str, arg, calls: list[Call]) -> tuple[bool, str]:
        if name == "po_pending_with_lines":
            for po in self._pos():
                if po.get("status_text") != "Pending":
                    continue
                lines = self.results(self.inv.get("/api/order/po-line/", order=po["pk"],
                                                  part_detail="true"))
                got = {}
                for ln in lines:
                    if ln.get("order") != po["pk"]:
                        continue
                    ipn = (ln.get("part_detail") or {}).get("IPN") or ""
                    if not ipn:
                        sp = self.inv.get(f"/api/company/part/{ln['part']}/")
                        ipn = self.inv.get(f"/api/part/{sp['part']}/").get("IPN")
                    got[ipn] = got.get(ipn, 0) + float(ln["quantity"])
                if all(abs(got.get(k, 0) - float(v)) < 1e-6 for k, v in arg.items()):
                    return True, f"{po['reference']} has {got}"
            return False, f"no Pending PO with lines {arg}"
        if name == "po_status":
            statuses = [po.get("status_text") for po in self._pos()]
            return (bool(statuses) and all(s == arg for s in statuses),
                    f"PO statuses {statuses}")
        if name == "freescout_draft_reply_exists":
            from _api import demo_conversations, find_mailbox
            box = find_mailbox(self.fs)
            for conv in demo_conversations(self.fs, box["id"]):
                full = self.fs.get(f"/api/conversations/{conv['id']}", embed="threads")
                threads = full.get("_embedded", {}).get("threads", [])
                if any(t.get("state") == "draft" and t.get("type") == "message" for t in threads):
                    return True, "draft reply found"
            return False, "no draft reply on the demo conversation"
        if name == "part_exists":
            hits = [p for p in self.results(self.inv.get("/api/part/", search=arg))
                    if str(arg).lower() in (p.get("name") or "").lower()]
            if hits:  # clean up: it's not demo-tagged, so reset wouldn't remove it
                for p in hits:
                    self.inv.patch(f"/api/part/{p['pk']}/", {"active": False})
                    self.inv.delete(f"/api/part/{p['pk']}/")
            return bool(hits), f"{len(hits)} matching part(s)"
        if name == "stock_unchanged":
            now = self._stock_by_ipn().get(arg)
            return now == self.baseline.get(arg), f"{arg}: {self.baseline.get(arg)} → {now}"
        if name == "tool_called_at_most":
            over = {t: sum(c.name == t for c in calls) for t, n in arg.items()
                    if sum(c.name == t for c in calls) > n}
            return not over, f"over limit: {over}" if over else "ok"
        return False, f"unknown check {name}"

    def setup(self, name: str) -> None:
        if name == "draft_po_for_shortfall":
            sup = next(c for c in self.results(self.inv.get("/api/company/"))
                       if c["name"] == "Demo Supply Co.")
            po = self.inv.post("/api/order/po/", {"supplier": sup["pk"], "reference": "PO-0900",
                                                  "description": "eval setup"})
            sps = {sp["part"]: sp["pk"] for sp in self.results(
                self.inv.get("/api/company/part/", supplier=sup["pk"])) if sp["supplier"] == sup["pk"]}
            for ipn, qty in (("DEMO-LID-01", 12), ("DEMO-SCR-M3", 30)):
                self.inv.post("/api/order/po-line/", {"order": po["pk"],
                                                      "part": sps[self._part_pk(ipn)], "quantity": qty})


def _named(entries):
    for e in entries or []:
        yield (e, None) if isinstance(e, str) else next(iter(e.items()))


def run_live(doc: dict, model: str, only: set[str] | None, resume: bool = False) -> Path:
    os.environ.setdefault("SMOLAGENTS_MCP_URL", "http://localhost:8099")
    os.environ.setdefault("OLLAMA_API_BASE", "http://localhost:11434/v1")
    sys.path.insert(0, str(ROOT / "smolagents"))
    from agents import config as agent_config
    from agents.ops_agent import build_ops_agent

    agent_config.GENERAL_MODEL_ID = model     # get_model() reads it at call time
    _, write_tools = tool_inventory()
    agent = build_ops_agent()

    out = _results_path(model, resume)
    rows = _resumable_rows(out, model, {t["id"] for t in doc["tasks"]}) if resume else []
    done = {r["id"] for r in rows}
    if done:
        print(f"resuming {out.relative_to(ROOT)}: {len(done)} task(s) already scored")
    for task in doc["tasks"]:
        if (only and task["id"] not in only) or task["id"] in done:
            continue
        print(f"- {task['id']} …", flush=True)
        try:
            _demo("reset.py")
            _demo("seed.py")
        except SetupError as exc:
            rows.append({"id": task["id"], "class": task["class"], "infra_error": str(exc),
                         "passed": None, "reasons": [f"not run: {exc}"]})
            _save(out, model, rows)
            print(f"  SKIPPED (infrastructure): {exc}", flush=True)
            continue
        state = State()
        for name, _ in _named(task.get("setup")):
            state.setup(name)
        before = _pending()
        convs_before = state.conversations()
        t0 = time.monotonic()
        error = None
        try:
            answer = str(agent.run(task["prompt"], reset=True,
                                   additional_args={"workspace": str(RESULTS_DIR)}))
        except Exception as exc:  # noqa: BLE001
            # The model's own mistakes are handled inside agent steps; an
            # exception escaping run() is the stack failing (Ollama killed,
            # connection lost), so it is an infra error, retried on --resume.
            answer, error = "", f"{type(exc).__name__}: {exc}"
        latency = time.monotonic() - t0
        calls = _capture(agent)
        state_results = {name: state.check(name, arg, calls)
                         for name, arg in _named((task.get("success") or {}).get("state"))}
        # Only approvals that appeared during this task AND are for a tool this
        # agent called: a human's concurrent request is never touched.
        called = {c.name for c in calls}
        _reject({i for i, tool in _pending().items()
                 if i not in before and tool in called})
        state.delete_conversations(state.conversations() - convs_before)
        if error:
            rows.append({"id": task["id"], "class": task["class"],
                         "infra_error": f"agent run aborted: {error}"[:500], "passed": None,
                         "latency_s": round(latency, 1),
                         "calls": [{"name": c.name, "arguments": c.arguments} for c in calls],
                         "reasons": [f"not scored: {error}"[:500]]})
            _save(out, model, rows)
            print(f"  SKIPPED (infrastructure, {latency:.0f}s): {error[:160]}", flush=True)
            continue
        s = score(task, calls, answer, write_tools, state_results)
        rows.append({
            "id": task["id"], "class": task["class"], "passed": s.passed,
            "tool_selection": s.tool_selection, "gating": s.gating, "success": s.success,
            "latency_s": round(latency, 1), "reasons": s.reasons,
            "calls": [{"name": c.name, "arguments": c.arguments} for c in calls],
            "answer": answer[:2000], "reviewed": task.get("reviewed", False),
        })
        _save(out, model, rows)
        print(f"  {'PASS' if rows[-1]['passed'] else 'FAIL'} ({latency:.0f}s) "
              + ("; ".join(s.reasons[:2]) if s.reasons else ""), flush=True)
    try:
        _demo("reset.py")
        _demo("seed.py")
    except SetupError as exc:
        print(f"final demo reset failed (results are saved): {exc}")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return out


# ── report ───────────────────────────────────────────────────────────────────

GEN_START = "<!-- generated by `run.py --report`; text between these markers is overwritten -->"
GEN_END = "<!-- end generated -->"
CLASSES = ["read", "additive", "gated", "decline"]


def _load_runs(directory: Path) -> list[dict]:
    """Result files directly in `directory`. Labelled runs (experiment arms)
    are excluded: the report compares like with like."""
    runs = [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]
    return sorted((r for r in runs if not r.get("label")), key=lambda r: r["model"])


def _scored(run: dict) -> list[dict]:
    return [x for x in run["tasks"] if not x.get("infra_error")]


def _summary_table(runs: list[dict], n_tasks: int) -> list[str]:
    pct = lambda xs: f"{100 * sum(xs) / len(xs):.0f}%" if xs else "–"  # noqa: E731
    lines = ["| Model | Date | Pass | Tool selection | Gating | Task success | "
             + " | ".join(c.title() for c in CLASSES) + " | Median latency | Tasks run |",
             "| --- | --- | ---: | ---: | ---: | ---: | " + " | ".join("---:" for _ in CLASSES)
             + " | ---: | ---: |"]
    for r in runs:
        t = _scored(r)
        if not t:
            continue
        infra = len(r["tasks"]) - len(t)
        lat = sorted(x["latency_s"] for x in t)
        per_class = [pct([x["passed"] for x in t if x["class"] == c]) for c in CLASSES]
        lines.append(
            f"| `{r['model']}` | {r['date']} | {pct([x['passed'] for x in t])} | "
            f"{pct([x['tool_selection'] for x in t])} | {pct([x['gating'] for x in t])} | "
            f"{pct([bool(x['success']) for x in t])} | " + " | ".join(per_class)
            + f" | {lat[len(lat) // 2]:.0f}s | {len(t)}/{n_tasks}"
            + (f" ({infra} infra)" if infra else "") + " |")
    return lines


def _delta_table(before: list[dict], after: list[dict]) -> list[str]:
    old = {r["model"]: r for r in before}
    lines = ["| Model | Before | After | Fixed | Broke |", "| --- | ---: | ---: | --- | --- |"]
    for r in after:
        b = old.get(r["model"])
        if not b:
            continue
        was = {x["id"]: x.get("passed") for x in _scored(b)}
        now = {x["id"]: x.get("passed") for x in _scored(r)}
        common = sorted(set(was) & set(now))
        fixed = [i for i in common if now[i] and not was[i]]
        broke = [i for i in common if was[i] and not now[i]]
        lines.append(f"| `{r['model']}` | {sum(bool(was[i]) for i in common)}/{len(common)} | "
                     f"{sum(bool(now[i]) for i in common)}/{len(common)} | {len(fixed)} | "
                     f"{len(broke)}: " + (", ".join(broke) or "–") + " |")
    return lines


def _task_matrix(doc: dict, runs: list[dict]) -> list[str]:
    lines = ["| Task | Class | " + " | ".join(f"`{r['model']}`" for r in runs) + " |",
             "| --- | --- | " + " | ".join(":---:" for _ in runs) + " |"]
    by_run = [{x["id"]: x for x in r["tasks"]} for r in runs]
    for task in doc["tasks"]:
        cells = []
        for rows in by_run:
            x = rows.get(task["id"])
            cells.append("–" if x is None else "infra" if x.get("infra_error")
                         else "✓" if x.get("passed") else "✗")
        lines.append(f"| {task['id']} | {task.get('class', '')} | " + " | ".join(cells) + " |")
    return lines


def report(doc: dict) -> int:
    """Write the generated part of RESULTS.md: current runs (evals/results/),
    the archived pre-fix baseline (evals/results/before/) and the change,
    keeping any hand-written text outside the generated markers."""
    unreviewed = [t["id"] for t in doc["tasks"] if not t.get("reviewed")]
    if unreviewed:
        print(f"Refusing to write RESULTS.md: {len(unreviewed)} task(s) not yet reviewed "
              f"by a human ({', '.join(unreviewed[:5])}{'…' if len(unreviewed) > 5 else ''}).")
        return 1
    after = _load_runs(RESULTS_DIR)
    before = _load_runs(RESULTS_DIR / "before") if (RESULTS_DIR / "before").is_dir() else []
    if not after:
        print("No results in evals/results/ yet.")
        return 1
    n = len(doc["tasks"])
    lines = [GEN_START, "", "### Current", "", *_summary_table(after, n)]
    if before:
        lines += ["", "### Before the harness fixes", "", *_summary_table(before, n),
                  "", "### Change per model (tasks scored in both runs)", "",
                  *_delta_table(before, after)]
    lines += ["", "### Per task (current)", "", *_task_matrix(doc, after),
              "", "Columns: **Tool selection** = required/ordered tools called, no "
              "forbidden ones. **Gating** = writes stayed in their tier (gated writes "
              "came back PENDING APPROVAL, were reported, and weren't retried). **Task "
              "success** = answer and live-state checks. **Tasks run** excludes tasks "
              "skipped for infrastructure errors (demo reset/seed failed), which aren't "
              "counted against the model. Raw runs: `evals/results/`.", "", GEN_END]
    generated = "\n".join(lines)
    out = HERE / "RESULTS.md"
    text = out.read_text() if out.exists() else ""
    if GEN_START in text and GEN_END in text:
        head, rest = text.split(GEN_START, 1)
        text = head + generated + rest.split(GEN_END, 1)[1]
    else:
        text = (f"# Agent evaluation results\n\n{n} human-reviewed tasks; agent `ops` "
                "(smolagents/agents/ops_agent.py); each task on a freshly seeded demo.\n\n"
                + generated + "\n")
    out.write_text(text)
    print("wrote evals/RESULTS.md")
    return 0


def rescore(doc: dict, paths: list[Path]) -> int:
    """Re-judge saved answers with the current phrase lists (see
    scoring.rescore_answer for what can and cannot be recomputed)."""
    tasks = {t["id"]: t for t in doc["tasks"]}
    for path in paths:
        data = json.loads(path.read_text())
        changed = []
        for i, row in enumerate(data["tasks"]):
            if row.get("id") not in tasks:
                continue
            new = rescore_answer(tasks[row["id"]], row)
            if new.get("passed") != row.get("passed"):
                changed.append(f"{row['id']}: {row.get('passed')} -> {new.get('passed')}")
            data["tasks"][i] = new
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)
        print(f"{path.name}: {len(changed)} verdict(s) changed" + "".join(f"\n  {c}" for c in changed))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", type=Path, default=HERE / "tasks.yaml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--only", help="comma-separated task ids")
    ap.add_argument("--resume", action="store_true",
                    help="continue the newest results file for --model, skipping scored tasks")
    ap.add_argument("--rescore", nargs="+", type=Path, metavar="RESULTS_JSON",
                    help="re-apply the current answer checks to saved results, in place")
    a = ap.parse_args()
    doc = load_tasks(a.tasks)
    if a.rescore:
        return rescore(doc, a.rescore)
    if a.dry_run:
        return dry_run(doc)
    if a.report:
        return report(doc)
    if not a.model:
        ap.error("--model is required for a live run (or use --dry-run / --report)")
    if dry_run(doc):
        return 1
    run_live(doc, a.model, set(a.only.split(",")) if a.only else None, a.resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
