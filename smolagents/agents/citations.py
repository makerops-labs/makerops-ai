"""Deterministic citation gates for the research agents.

Prompt-level "never fabricate a source" was not enough: briefs landed with
dead links and URLs the model invented from memory. These
final_answer_checks reject such answers with corrective feedback so the
agent retries (external verification per docs/guidance — the model is
never the judge of its own citations):

- check_citations_observed — every cited URL must have appeared somewhere
  in the run's tool results (search output, fetched pages, tool args). A
  URL the agent never saw is a fabrication. Cheap; for the quick
  web_researcher.
- check_citations_fetched — every cited URL must have been SUCCESSFULLY
  fetched (fetch_url/visit_webpage without an error result) during the
  run. Catches fabrications AND dead links from stale search results; for
  the deep researcher, whose briefs are consumed sight-unseen.

Both checks are bypassed by smolagents' forced max-steps answer (as all
final_answer_checks are — see jobs.py), so they shape behavior within the
step budget rather than guaranteeing the exhaustion path.
"""

import re

# Scheme required — bare domains in prose are not checkable citations.
_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`]+")

_FETCH_TOOL_NAMES = {"fetch_url", "visit_webpage"}


def _normalize(url: str) -> str:
    """Collapse cosmetic variants (scheme, www, fragment, trailing junk) so
    they compare equal, without touching path/query — those are where
    fabrications live."""
    url = url.strip().rstrip(".,;:!?)]}\"'")
    url = url.split("#", 1)[0]
    url = re.sub(r"^https?://(www\.)?", "", url, flags=re.IGNORECASE)
    return url.rstrip("/")


def _urls_in(text: str) -> set[str]:
    return {_normalize(u) for u in _URL_RE.findall(text or "")}


def _iter_steps(memory):
    return getattr(memory, "steps", None) or []


def _observed_urls(memory) -> set[str]:
    """Every URL that appeared in tool observations or tool-call arguments
    during the run."""
    seen: set[str] = set()
    for step in _iter_steps(memory):
        seen |= _urls_in(getattr(step, "observations", "") or "")
        for call in getattr(step, "tool_calls", None) or []:
            seen |= _urls_in(str(getattr(call, "arguments", "")))
    return seen


def _fetched_urls(memory) -> set[str]:
    """URLs passed to a fetch tool in a step whose observations are not an
    error result. Parallel tool calls share one observations blob, so an
    error anywhere in the step conservatively disqualifies its fetches —
    the retry just fetches again."""
    fetched: set[str] = set()
    for step in _iter_steps(memory):
        observations = (getattr(step, "observations", "") or "").strip()
        if observations.startswith("ERROR") or not observations:
            continue
        for call in getattr(step, "tool_calls", None) or []:
            if getattr(call, "name", "") not in _FETCH_TOOL_NAMES:
                continue
            args = getattr(call, "arguments", None)
            url = args.get("url") if isinstance(args, dict) else str(args or "")
            fetched |= _urls_in(url if _URL_RE.search(url or "") else "")
    return fetched


def _answer_text(final_answer) -> str:
    return final_answer if isinstance(final_answer, str) else str(final_answer)


def check_citations_observed(final_answer, memory, agent=None) -> bool:
    """final_answer_check: every URL in the answer appeared in this run's
    tool results. Rejects invented links with the offending list."""
    cited = _urls_in(_answer_text(final_answer))
    unverified = cited - _observed_urls(memory)
    if not unverified:
        return True
    listing = ", ".join(sorted(unverified))
    raise Exception(
        f"CITATION CHECK FAILED — these URLs never appeared in your search "
        f"results or fetched pages this run: {listing}. You may only cite "
        "URLs you actually received from web_search or fetched yourself. "
        "Re-run the search to find a real source for each claim, or remove "
        "the claim; never construct a link from memory.")


def check_citations_fetched(final_answer, memory, agent=None) -> bool:
    """final_answer_check: every URL in the answer was successfully opened
    with a fetch tool this run — catches dead links, not just invented
    ones."""
    cited = _urls_in(_answer_text(final_answer))
    unfetched = cited - _fetched_urls(memory)
    if not unfetched:
        return True
    listing = ", ".join(sorted(unfetched))
    raise Exception(
        f"CITATION CHECK FAILED — you cite URLs you never successfully "
        f"opened this run: {listing}. Fetch each one with fetch_url before "
        "citing it: if it loads and supports the claim, resubmit the same "
        "brief; if it does not, replace the citation with a source that "
        "does or report the claim as unverifiable in Confidence & gaps. "
        "Never cite a link you have not read.")
