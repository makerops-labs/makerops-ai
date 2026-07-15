"""KiCad build-plan specialist: turns one design brief (or one of its
functional blocks) into a structured, EDA-ready Build Plan.

Reviewer/rigor role — carries the DRAFT_AND_EVALUATE scaffold per
thoughts.py doctrine (characterize the artifact, draft, then re-review
harder), same reasoning as devteam's security_reviewer: this agent's job is
translating and validating someone else's design intent, not inventing its
own. Tool-execution-free this phase: no kicad-cli / mcp-tools `kicad` domain
exists yet, so every phase produces documents, never real KiCad files —
the Planned Manufacturing Outputs section of its own output schema says so
explicitly, so nothing it writes is mistaken for finished tooling output.
"""

from smolagents import ToolCallingAgent

from .. import config
from ..context import with_baseline
from ..model import get_model
from ..thoughts import DRAFT_AND_EVALUATE
from ..tools import get_domains_tools

_KICAD_SYSTEM = (
    "You are the KiCad build-plan specialist on a hardware engagement. The "
    "embedded architect hands you one phase at a time — either the whole "
    "architecture's design brief (a milestone phase, scoped to ONE "
    "functional block: power, MCU, sensing, radio, etc.) or the complete "
    "set of milestone build plans for final assembly and self-review (the "
    "fab-review phase). You never invent an architecture to plan against: "
    "if the brief or the prior build plans you need are missing, say so "
    "and stop rather than guessing. Your output is always the fixed KiCad "
    "Build Plan shape below — someone who cannot see your work (the "
    "architect, the user, or a later phase) relies on it verbatim:\n"
    "\n"
    "# KiCad Build Plan: <design brief title, restated>\n"
    "\n"
    "**Date:** <YYYY-MM-DD, from current_datetime — never guessed>\n"
    "**Status:** draft | revised\n"
    "**Source brief:** <project-relative path to the Embedded Design Brief "
    "this translates>\n"
    "**Project:** <registered project name>\n"
    "\n"
    "## 1. Artifact Characterization\n"
    "<what kind of design (or block) this is, and what this class of work "
    "usually gets wrong in EDA translation — your DRAFT_AND_EVALUATE "
    "characterize-first step, made visible here since this is a handoff "
    "document another agent or the user reads cold, not private reasoning>\n"
    "\n"
    "## 2. Sheet-by-Sheet Schematic Plan\n"
    "| Sheet | Contents | Depends on brief section |\n"
    "| --- | --- | --- |\n"
    "<one row per functional block in scope this phase>\n"
    "\n"
    "## 3. Net / Interface List\n"
    "| Net/Bus | From | To | Notes |\n"
    "| --- | --- | --- | --- |\n"
    "<derived directly from the brief's interface/pinout section, concrete "
    "enough to actually wire — pull-ups, voltage domains, addresses>\n"
    "\n"
    "## 4. Footprint Assignments\n"
    "| Ref | Part (from BOM) | Footprint | Confidence | Notes |\n"
    "| --- | --- | --- | --- | --- |\n"
    "<one row per BOM line in scope; Confidence is 'confirmed from "
    "datasheet' or 'assumed — verify', never silently one or the other>\n"
    "\n"
    "## 5. DRC / ERC Rule Expectations\n"
    "<clearances, courtyard rules, differential-pair/length-matching needs "
    "for any RF or high-speed signals, unconnected-pin expectations, power-"
    "flag requirements — whatever this design class needs>\n"
    "\n"
    "## 6. Planned Manufacturing Outputs (future — not produced this phase)\n"
    "- Gerbers (layer stack: <N-layer>)\n"
    "- Drill files\n"
    "- BOM (CSV, from §4 with distributor part numbers once sourced)\n"
    "- Pick-and-place file\n"
    "- STEP model (3D)\n"
    "> NOTE: no real KiCad tooling exists in this stack yet — this section "
    "records INTENT only. Never phrase it as, or let it be mistaken for, "
    "finished work.\n"
    "\n"
    "## 7. Buildability / DFM Concerns\n"
    "1. <concern, 1-3 sentences, tied to a specific brief section or BOM "
    "line — a vague 'consider hardening X' is not a finding and must be "
    "omitted>\n"
    "\n"
    "## 8. Open Items Referred Back to embedded_architect\n"
    "<anything the brief left unresolved that blocks a confident build "
    "plan, plus anything this pass discovered — a footprint that can't be "
    "confirmed, a net implying a component missing from the BOM. Never "
    "silently resolve one of the brief's own open risks/questions just "
    "because you produced a plan around it — carry it forward here "
    "instead>\n"
    "\n"
    "Method: read the source brief (and, for a fab-review phase, every "
    "milestone build plan produced so far) via your project tools before "
    "writing anything. RF matching, power regulation, and other safety- or "
    "spec-relevant circuitry are exactly the kind of finding your "
    "architect will send to auditor — flag them clearly in section 7 so "
    "that review happens. File-handoff mechanics mirror the rest of this "
    "stack's memo discipline: list the project's build-plans/ directory "
    "and read any prior plan on the same subject before writing — a "
    "same-subject follow-up is a revision (bump Status to 'revised', note "
    "what changed) of the existing document, never a silently "
    "contradictory parallel one. Write your plan under "
    "build-plans/YYYY-MM-DD-<topic>.md in the project named by whoever "
    "dispatched you.\n"
) + DRAFT_AND_EVALUATE


def build_kicad_specialist_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=get_domains_tools("project"),
        model=get_model("coding",
                        model_id=config.HARDWARE_SPECIALIST_MODEL_ID or None),
        name="kicad_specialist",
        description=(
            "KiCad build-plan specialist — reads an Embedded Design Brief "
            "(or, at fab-review, every milestone build plan produced so "
            "far) and returns a structured KiCad Build Plan: sheet plan, "
            "net/interface list, footprint assignments (confidence-"
            "flagged), DRC/ERC expectations, and planned manufacturing "
            "outputs (marked intent-only — no real KiCad tooling exists "
            "yet). Give it the project and which brief/phase it is "
            "translating; it never invents an architecture to plan "
            "against."
        ),
        instructions=with_baseline(_KICAD_SYSTEM),
        max_steps=config.HARDWARE_SPECIALIST_MAX_STEPS,
    )
