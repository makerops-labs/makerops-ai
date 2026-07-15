# Hardware Agents Guide (embedded_architect + kicad_specialist)

How to work with the two hardware-design agents in this stack, and what's
still ahead of them. This is the human-facing companion to
[docs/guidance/hardware-design-handoff.md](guidance/hardware-design-handoff.md)
(the agent-facing convention doc for the document schemas and phase/gate
discipline) — read that one if you're the one extending the agents, read
this one if you're the one using them.

## 1. What this is, and what it isn't yet

Two agents work together on a **hardware engagement**: a durable,
multi-phase session that takes you from "I want a device that does X" to a
design ready to send to a PCBA manufacturer.

- **embedded_architect** — the mind. Interviews you, architects the
  circuit (MCU/component selection, power budget, block topology,
  candidate BOM), and hands structured design documents to the specialist.
- **kicad_specialist** — the hands, currently document-only. Turns the
  architect's design intent into a KiCad-ready build plan: sheet layout,
  net list, footprint assignments, DRC/ERC expectations.

**This phase builds the engagement mechanism and both personas — it does
not install KiCad, and there is no real `kicad-cli` execution.** Every
phase's deliverables are Markdown documents, not schematic/PCB files. The
"Planned Manufacturing Outputs" section of every build plan is explicitly
marked intent-only until the tooling described in the Roadmap (§5) lands.
If you want gerbers today, you're one phase early — but the design
documents this phase produces are exactly what that later phase consumes.

## 2. The engagement lifecycle

An engagement moves through five phase kinds:

1. **requirements** *(gated)* — embedded_architect interviews you:
   functional needs, power/battery targets, environmental/mechanical
   constraints, cost ceiling, timeline. It asking you questions here is
   the system working as intended, not a stall.
2. **architecture** *(gated)* — produces the Embedded Design Brief
   (architecture overview, power budget with the arithmetic shown,
   candidate BOM checked against your local InvenTree stock, interface
   intent) plus a milestone plan — one milestone per functional block
   (power, MCU, sensing, radio, etc.).
3. **milestone** *(one per block, ungated by default)* — kicad_specialist
   turns one block into its slice of the KiCad Build Plan. Anything
   touching RF matching, power regulation, or other safety-relevant
   circuitry gets an extra pass from the auditor.
4. **fab-review** *(always gated)* — kicad_specialist assembles every
   block's build plan into one ready-for-fab package and does a final
   buildability/DFM self-review. This gate is never skipped, even with
   `gates=none`, because it's the checkpoint before a real manufacturing
   spend.
5. **docs** *(gated)* — finalizes the project's design record and
   `PROJECT_CONTEXT.md`.

Between gates, phases advance on their own — you're notified, not asked to
click through every milestone. Two things can happen mid-run:

- **`awaiting_input`** — the architect has a question only you can answer.
  You'll be notified (or asked live, in chat); answering resumes the
  *same* phase with your answer injected, never re-asked.
- **`awaiting_review`** — a gate. You get a summary of what was produced
  and where; you explicitly approve or send it back with feedback.
  Nothing advances past a gate without you.

**Feeding back real-world test results**: once you've had a prototype
board built and tested, the way to bring findings back into the design is
requesting a revision on the `fab-review` phase with what you found — the
same mechanism used for any other gate rework. If the engagement already
concluded, start a new one referencing the same project rather than
mutating a finished engagement.

## 3. How to start and drive one

### OpenWebUI (primary path)

Open the **Hardware Builder** preset. It interviews you into a concrete
brief, has you create and register the project directory
(`~/workspace/<project>`, a plain directory you create by hand — that's
the write authorization), starts the engagement, relays questions, and
summarizes gates for your sign-off. It never approves or revises on your
behalf — you always get the summary first.

For quick one-off questions that don't need a whole engagement ("check
this footprint", "what clearance does this trace width usually want"),
use the **KiCad Specialist** preset instead — a lightweight, standalone
chat with no engagement machinery attached.

### CLI / scripted access

There's no dedicated CLI binary in this stack — everything goes through
mcp-tools' HTTP/MCP endpoints. Two ways to drive an engagement from a
terminal:

**Directly against the `hardware` domain** (one-shot calls, scripted or
automation-friendly):

```bash
curl -s http://mcp.localhost/mcp/hardware/hardware_status \
  -H 'Content-Type: application/json' \
  -d '{"engagement_id": "hardware-..."}'
```

Every transition (`hardware_start`, `hardware_answer`, `hardware_approve`,
`hardware_revise`, `hardware_resume`, `hardware_cancel`) is callable the
same way — see `mcp-tools/tools/hardware_domain.py` for exact signatures,
or `tools_help('hardware')` from any MCP client for the live docs.

**Against OpenWebUI's OpenAI-compatible chat API**, if you'd rather drive
the Hardware Builder conversationally from a script:

```bash
curl -s http://localhost:8080/api/chat/completions \
  -H 'Authorization: Bearer <your-openwebui-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"model": "Hardware Builder", "messages": [{"role": "user", "content": "..."}]}'
```

The tradeoff: direct `hardware_*` calls are one-shot and precise but you
do the brief-refining and status-summarizing yourself; the chat API gets
you the Hardware Builder's intake interview and plain-English status
summaries, at the cost of a conversational round-trip.

### Direct agent-to-agent delegation

`embedded_architect` already carries `kicad_specialist` as a managed
sub-agent — asking the architect for a full pass (via `agent_dispatch` or
the manager) can traverse both without you wiring it up by hand. This is
separate from the formal engagement mechanism above; it's a one-shot,
non-gated delegation, useful for a quick "what would this look like"
sanity check rather than a real multi-phase build.

## 4. Where the artifacts live

Everything lands in the registered project directory
(`~/workspace/<project>`), not in this repo:

- `docs/REQUIREMENTS.md`, `docs/ARCHITECTURE.md` — the requirements and
  architecture phase deliverables.
- `build-plans/YYYY-MM-DD-<topic>.md` — one KiCad Build Plan per block
  (and the assembled fab-review package).
- `PROJECT_CONTEXT.md` — kept current at every phase; read this first if
  you're picking a project back up.

The exact document schemas (what each heading means, what stays
addressable-by-section) live in
[docs/guidance/hardware-design-handoff.md](guidance/hardware-design-handoff.md)
— that's the one to read if a document looks wrong, not this guide.

## 5. Roadmap (what's deliberately deferred)

In rough order of dependency:

1. **Install KiCad v10 and add a headless `kicad-cli`-wrapping mcp-tools
   `kicad` domain.** KiCad v10 isn't in Ubuntu's default `apt` repo (which
   only offers 7.0.11) — use the KiCad PPA, a Flatpak, or an AppImage.
   `kicad-cli` is fully headless (no GUI needed): ERC/DRC, and export of
   gerbers/BOM/STEP/pick-and-place, all runnable as a shell command. The
   natural home for this is the existing `project_run_command`/sandbox
   containment (same pattern every other CLI-execution tool in this stack
   already uses) rather than a new always-on service. Once this lands,
   "Planned Manufacturing Outputs" stops being a plan and starts being a
   file.
2. **Code-first circuit generation** (SKiDL or atopile) as a path from a
   KiCad Build Plan's net list/footprint tables to an actual KiCad project
   — script-to-schematic rather than hand-editing, and naturally
   git-friendly/agent-friendly. This is also the realistic answer to
   "architect and design circuits *in* KiCad": headless `kicad-cli` alone
   validates and exports, it doesn't author a schematic from scratch.
3. **A KiCad v10 IPC-API desktop plugin.** KiCad v10 introduced a new
   IPC-based external API (replacing the old SWIG scripting console) that
   lets an external process connect to a *running* KiCad session and
   read/modify the open document. This is the mechanism for genuinely
   talking to `kicad_specialist` from inside the KiCad desktop app — a
   plugin that adds a panel/action, connects over the IPC API, and calls
   out to the specialist for review/assist duties (run DRC on demand,
   explain a flagged net) rather than full autonomous editing. Flagged as
   the highest-uncertainty item on this list: the API is new, sparsely
   documented, and nothing in this stack has touched it yet — expect this
   to need real exploration time, not just wiring.
4. **A parts-sourcing domain** beyond local InvenTree stock — distributor
   availability/pricing (Octopart/DigiKey/Mouser-style APIs) would let
   embedded_architect's BOM stock-check extend past "do we already have
   this" to "can we get this, and for how much." Needs API credentials you
   provide; not started.
5. **Future fine-tuning.** Once there's real engagement history to
   distill from, `docs/model-development-playbook.md` and
   [docs/guidance/local-finetuning-feasibility.md](guidance/local-finetuning-feasibility.md)
   are the existing groundwork this would build on — same "evidence
   before abstraction" discipline the guidance library already applies to
   every other roadmap item deferred for the same reason.

## 6. Known limitations this phase

- No real ERC/DRC — footprint and net-list correctness is
  kicad_specialist's best-effort judgment, not a tool-verified fact.
- No real manufacturing outputs — no gerbers, no pick-and-place file, no
  STEP model exist anywhere until Roadmap item 1 lands.
- No live part pricing or availability beyond whatever's already in your
  local InvenTree stock.
- Footprint assignments are confidence-flagged but unverified against real
  footprint libraries — treat "confirmed from datasheet" as "the model
  read a datasheet," not as a guarantee.
- The hardware engagement's engine (`smolagents/agents/jobs.py`'s hardware
  section) is a deliberate fork of the devteam engagement code, not a
  shared implementation — see that file's comments if you're modifying
  either one, so a fix to one doesn't quietly need to happen twice.
