# Agent evaluation

Measures whether the stack's real `ops` agent
(`smolagents/agents/ops_agent.py`, all 7 of its tool domains attached)
handles the lead scenario correctly on local models. It scores four things
per task:

| Score | Meaning |
| --- | --- |
| **Tool selection** | The required tools were called, in the expected order where that matters, and no forbidden tool was called. |
| **Gating** | Writes stayed in their policy tier. A gated write came back `PENDING APPROVAL`, the agent told the user, and it didn't retry. Read-only and "should ask" tasks made no writes at all. |
| **Task success** | The answer contains the expected facts, and the live InvenTree/FreeScout state matches (e.g. a Pending PO with lids x12 and screws x30). |
| **Latency** | Wall-clock time per task. |

Tasks (`tasks.yaml`, 29) fall into four classes:
- **read:** lookups and shortfall maths;
- **additive:** draft PO, draft reply, new part;
- **gated:** placing a PO, stock changes, sending email;
- **decline:** ambiguous, unknown, or destructive requests that the agent
  should question rather than execute.

## Human checkpoint

Every task ships with `reviewed: false`. A human must check each expected
answer (the tools, tier and success checks) and flip it to `true`.
`run.py --report` **refuses** to write `RESULTS.md` while any task is
unreviewed: an eval whose answers were never checked by a person is weak
evidence.

## Running

```bash
# 1. Validate tasks.yaml against the real mcp-tools inventory (CI does this)
uv run --no-project --with pyyaml python evals/run.py --dry-run

# 2. Live run on the GPU host. Prerequisites: Ollama, mcp-tools on :8099 with
#    the InvenTree BOM/PO tools deployed, InvenTree + FreeScout, demo/.env.
#    Stop trellis first (RAM). Uses smolagents' own locked environment.
uv run --frozen --project smolagents --with pyyaml \
    python evals/run.py --model qwen3.6:35b-64k            # --only id1,id2 to subset

# 3. Comparison table from evals/results/*.json
uv run --no-project --with pyyaml python evals/run.py --report
```

Use the **context-extended model tags** (`-64k`/`-32k`). The `ops` agent's
instructions and tool schemas don't fit in Ollama's 4k default context. A
smoke run with base `qwen3.5:9b` made zero tool calls in 12 steps; the model
never saw the tool-call format.

Each task runs on a freshly reset and seeded demo (`demo/`). Approvals the
agent creates are rejected through the real `/approvals` endpoint afterwards,
so they never reach anyone's queue. Parts a task creates are deleted after
being checked.

## Files

- `tasks.yaml`: the tasks and their expected behavior.
- `scoring.py`: pure validation and scoring logic (unit-tested in
  `tests/`, no network).
- `run.py`: the CLI: dry run, live run, report.
- `results/<date>-<model>.json`: raw per-task results, including tool calls
  and answers.
- `RESULTS.md`: the generated comparison table (only after review).
