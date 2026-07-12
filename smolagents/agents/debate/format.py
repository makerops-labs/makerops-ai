"""Shared round-output contract for the debate personas.

The round files are the personas' only channel to each other AND the final
artifact a human reads, so the format is enforced twice: this module's
contract text is appended to every persona's instructions (the ask), and
check_round_prose is registered as a final_answer_check on every persona
(the enforcement — smolagents re-prompts the persona with the raised
message instead of accepting a malformed answer). jobs.py additionally
sanitizes whatever still gets through (code-fence unwrapping) before a
round file is written, as a deterministic backstop.
"""

import re

ROUND_CONTRACT = (
    "OUTPUT CONTRACT — your final answer is written to a file that the "
    "OTHER debaters read as their input next turn and that a human reads "
    "verbatim at the end, so its format is not optional: the entire answer "
    "must be plain markdown prose. First line: a one-line abstract (25 "
    "words or fewer, no heading marker). Then a blank line. Then your full "
    "argument as prose — short paragraphs and bullet lists are fine. Never "
    "output Python code, JSON, dicts, tool-call syntax, code fences, or "
    "your own reasoning about tools/instructions; a code snippet is "
    "allowed ONLY if the debate goal is itself about code and you are "
    "quoting a short example inside an otherwise-prose argument. Write TO "
    "the other debaters and the human observer, never to the orchestrator "
    "that invoked you. SUBMISSION: you must deliver the answer by CALLING "
    "the final_answer tool with your complete text as its argument — "
    "writing the answer as a plain chat message submits NOTHING and the "
    "turn is wasted; when your argument is ready, your one and only next "
    "action is that final_answer call."
)

# Appended to a persona's instructions ONLY when it runs as a raw
# completion (config.DEBATE_RAW_PERSONAS): last-position override of the
# two agent-mode assumptions that break a raw run. Without the tools line,
# a tool-trained model (gpt-oss) reads the persona's "use your web tool"
# hint literally, emits a tool call into the void, and the completion ends
# with an EMPTY visible answer — thoughts only, done_reason=stop — which
# reads as "persona produced no usable round". Without the submission
# line, ROUND_CONTRACT's final_answer-call instruction makes it type out
# pseudo tool-call syntax instead of prose.
RAW_MODE_NOTE = (
    "RAW MODE OVERRIDE — this run gives you NO tools: no web search, no "
    "browsing, no final_answer tool, nothing to call. Any instruction "
    "above about using or calling tools does not apply; never emit or "
    "type out a tool call. Argue entirely from the debate material given "
    "to you and your own knowledge, and be honest when a fact would need "
    "checking you cannot do here. Your plain-text message IS the "
    "submission: write the round directly as your answer, in the OUTPUT "
    "CONTRACT format (one-line abstract, blank line, prose argument)."
)

# Leading tokens that mean the model answered with code/data instead of
# prose. Checked against the first non-empty line only — a fence or snippet
# deeper inside a prose argument is legitimate quoting per the contract.
_CODE_OPENERS = ("```", "{", "[", "def ", "class ", "import ", "from ",
                 "print(", "return ", "<?", "<html")


def check_round_prose(final_answer, memory, agent=None) -> bool:
    """final_answer_check: reject answers that open as code/JSON or leak
    tool syntax, with corrective feedback so the persona retries."""
    text = (final_answer if isinstance(final_answer, str)
            else str(final_answer)).strip()
    problem = None
    if not text:
        problem = "the answer is empty"
    else:
        first_line = text.splitlines()[0].strip()
        if any(first_line.startswith(tok) for tok in _CODE_OPENERS):
            problem = ("the answer opens as code/JSON instead of prose "
                       f"(first line starts with {first_line[:30]!r})")
        elif re.search(r"final_answer\s*\(", text):
            problem = "the answer leaks tool-call syntax (final_answer(...))"
        elif len(first_line.split()) > 40:
            problem = ("the first line must be a one-line abstract of 25 "
                       "words or fewer, then a blank line, then the "
                       "argument")
    if problem is None:
        return True
    raise Exception(
        f"Your answer violates the OUTPUT CONTRACT: {problem}. Rewrite it "
        "as plain markdown prose: first line a one-line abstract (25 words "
        "or fewer), blank line, then your full argument in prose — no "
        "code, JSON, dicts, code fences, or tool syntax.")
