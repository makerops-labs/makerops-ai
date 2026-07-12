"""TPO-style thought scaffolds (arXiv:2410.10630).

Two prompt blocks that direct the CONTENT of a model's private thinking —
pattern-finding, intuitive leaps, draft-and-evaluate — plus the deterministic
marker-strip backstop for outputs that feed another turn. See
docs/guidance/thinking-before-answering.md.

Opt-in per agent: thought-leader roles only. Direction-follower agents
(dispatcher, manager, liaison, coder, ops) must NOT import these — the
evidence says precise/mechanical roles benefit least or regress, and the
manager already has its own planning mechanism.
"""

import re

THOUGHT_MARKER = "Here is my thought process:"
RESPONSE_MARKER = "Here is my response:"

# Shared closing: makes any forced leakage deterministically strippable.
_LEAK_PROTOCOL = (
    "The scratchpad is for you alone: the final answer must contain no "
    "thought-process section, no scratchpad headings, and no commentary "
    "about this procedure. If your interface ever forces your thoughts "
    f"into the visible output, open them with the exact line "
    f"'{THOUGHT_MARKER}' and open the answer with the exact line "
    f"'{RESPONSE_MARKER}' — everything before that line will be discarded."
)

THINK_FIRST = (
    "THINK BEFORE YOU ANSWER — a private scratchpad, in your reasoning, "
    "never in the answer. Before composing your final answer: "
    "(1) Zoom out — what broader pattern or class of problem is this an "
    "instance of, and what does that class usually imply (base rates, "
    "typical failure modes, how such situations usually play out)? "
    "(2) Leap — list 2-3 candidate conclusions, relations, or suggestions "
    "an experienced practitioner would intuit here, including at least one "
    "non-obvious connection to an adjacent domain; mark which are backed "
    "by your evidence and which remain hunches. "
    "(3) Draft your answer, then judge the draft: does it keep the "
    "required output format exactly, surface the genuinely useful "
    "insights (labeled as interpretation wherever unsourced), and omit "
    "the unsupported ones? "
    "All of this happens inside your private reasoning within a single "
    "working step — NEVER spend a step narrating thoughts, plans, or a "
    "draft as a plain message: a narrated draft submits nothing and "
    "wastes the step. Once your draft survives your own judgment, your "
    "one and only next action is to submit the finished answer (when you "
    "work through tool calls, that means one final_answer call carrying "
    "the complete answer). "
) + _LEAK_PROTOCOL

# Reviewer/auditor variant (the paper's "specific" draft+evaluate template).
DRAFT_AND_EVALUATE = (
    "THINK BEFORE YOU ANSWER — a private scratchpad, in your reasoning, "
    "never in the answer. First characterize the artifact: what class of "
    "work is it, and what does that class of work usually get wrong? Then "
    "draft your findings. Then re-review your own draft as a harsher "
    "reviewer would: for each draft finding, name the concrete input, "
    "state, or scenario that triggers it — drop any that fail this test. "
    "If the surviving findings point at a systemic, pattern-level "
    "weakness, state it as its own finding subject to the same test. Only "
    "surviving findings appear in the answer; never the draft. "
) + _LEAK_PROTOCOL

# Marker line, optionally #-prefixed or bolded, alone on its line.
_RESPONSE_RE = re.compile(
    r"^\s*(?:[#*]+\s*)?here is my response:?\s*(?:[*#]+\s*)?$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_thoughts(text: str) -> str:
    """Deterministic backstop: if a model leaked its scratchpad into the
    visible output using the markers above, keep only what follows the
    LAST response marker. Never LLM-based — this text can feed another
    agent's next turn.

    No marker → input returned verbatim, including the residual case where
    only THOUGHT_MARKER appears: without a response marker there is no
    reliable boundary, so don't guess (downstream format checks and retries
    remain the net there).
    """
    if not text:
        return text
    parts = _RESPONSE_RE.split(text)
    if len(parts) == 1:
        return text
    return parts[-1].strip() or text
