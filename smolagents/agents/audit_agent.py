"""Audit agent: independent multi-model review of finished work.

Implements the reviewer-pool convention: each expertise domain has a lead
model that produces work and a pool of same-expertise, lower-benchmark
models that review it (see the model hierarchy table in README.md).
Reviews run sequentially because Ollama swaps one model in VRAM at a time.
"""

from openai import OpenAI
from smolagents import ToolCallingAgent, tool

from . import config
from .context import with_baseline
from .model import get_model

_REVIEWER_SYSTEM = (
    "You are an independent reviewer giving a second opinion on work "
    "produced by another AI model. Hunt for defects and blind spots: logic "
    "errors, missed edge cases, unstated assumptions, security or data-loss "
    "risks, and requirements the work does not meet. Report numbered "
    "findings ordered by severity. Every finding must name the concrete "
    "failure: the specific input, state, or scenario under which it breaks, "
    "and the specific requirement or precondition it violates — a vague "
    "'could be improved' or 'consider X' is not a finding and must be "
    "omitted. Do not rewrite the work. If you find nothing significant, "
    "say so."
)


@tool
def collect_reviews(domain: str, request: str) -> str:
    """Collect independent reviews of an artifact from the domain's reviewer models.

    Args:
        domain: "coding" for code artifacts, "general" for plans, documents,
            and other non-code work.
        request: The full review request: what the artifact was supposed to
            accomplish plus the complete artifact text.
    """
    pool = (config.CODING_REVIEW_MODEL_IDS if domain == "coding"
            else config.GENERAL_REVIEW_MODEL_IDS)
    client = OpenAI(base_url=config.OLLAMA_API_BASE,
                    api_key=config.OLLAMA_API_KEY)
    sections = []
    for model_id in pool:
        try:
            resp = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "system", "content": _REVIEWER_SYSTEM},
                          {"role": "user", "content": request}],
            )
            review = resp.choices[0].message.content or "(empty review)"
        except Exception as exc:  # noqa: BLE001 — one missing reviewer must not kill the audit
            review = f"(reviewer unavailable: {type(exc).__name__}: {exc})"
        sections.append(f"## Review by {model_id}\n\n{review}")
    return "\n\n".join(sections)


def build_audit_agent() -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=[collect_reviews],
        model=get_model("general"),
        name="auditor",
        description=(
            "Independent multi-model review of finished work. Give it the "
            "original task, the complete artifact (code, plan, or document), "
            "and whether it is coding or general work; it returns merged "
            "findings from the reviewer models."
        ),
        instructions=with_baseline(
            "Call collect_reviews exactly once, with domain='coding' for "
            "code or domain='general' otherwise, passing the task context "
            "and the full artifact verbatim. Then merge the reviews into "
            "one report: deduplicate overlapping findings, order by "
            "severity, name which reviewer raised each finding, and flag "
            "any disagreements between reviewers."
        ),
        max_steps=config.MAX_STEPS,
    )
