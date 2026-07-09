"""X (Twitter) recent-search tool. Unlike every other tool in this server,
this one costs real money per call — X's API lost its free tier in
February 2026; reads are billed per-post (~$0.005-0.01/read as of 2026, no
free search quota). Used by the self-improvement loop's periodic research
sweep (see smolagents/agents/maintainer_agent.py) to check X for AI-tooling
developments alongside the free engines (arxiv, github, scholar,
stackoverflow — via the web domain), which SearXNG cannot reach directly
(no Twitter/X engine exists in its default engine set)."""

import httpx
from fastmcp import FastMCP

from . import config
from .client import DEFAULT_TIMEOUT

mcp = FastMCP(
    "x",
    instructions=(
        "X (Twitter) recent search (posts from the last 7 days only). "
        "COSTS REAL MONEY per call (~$0.005-0.01 per read, no free tier) — "
        "use narrow, specific queries, and only during the periodic "
        "self-improvement research sweep or when explicitly asked about X "
        "content. Check the Research Query Log (Outline, AI collection) "
        "first — a query already run against X within the last 7 days "
        "would just re-fetch data already paid for."))
required_env = "X_API_BEARER_TOKEN"

# The endpoint's own range (verified against X's API docs): min 10, max 100,
# default 10. Cost is per-read regardless of call count, so always request
# the max — there is no reason to under-ask.
_MIN_RESULTS = 10
_MAX_RESULTS = 100


@mcp.tool
def x_search_recent(query: str, max_results: int = 100) -> str:
    """Search X (Twitter) posts from the last 7 days (X's recent-search
    endpoint — nothing older is reachable here). COSTS REAL MONEY per call
    (~$0.005-0.01 per read, no free tier) — use one narrow, specific query
    per call; check the Research Query Log first to avoid re-paying for a
    query already run recently. max_results: 10-100 (always request the
    max, 100, unless there's a specific reason not to — cost is per-read
    regardless of how many calls it takes to reach the same total)."""
    max_results = max(_MIN_RESULTS, min(max_results, _MAX_RESULTS))
    try:
        resp = httpx.get(
            f"{config.X_API_URL}/2/tweets/search/recent",
            params={"query": query, "max_results": max_results,
                   "tweet.fields": "created_at,author_id",
                   "expansions": "author_id", "user.fields": "username"},
            headers={"Authorization": f"Bearer {config.X_API_BEARER_TOKEN}"},
            timeout=DEFAULT_TIMEOUT)
    except httpx.ConnectError:
        return "ERROR: connection to the X API refused."
    except httpx.TimeoutException:
        return "ERROR: X API request timed out."
    if resp.status_code == 401:
        return "ERROR: X API returned 401 — check X_API_BEARER_TOKEN."
    if resp.status_code == 429:
        return ("ERROR: X API rate limit hit — do not immediately retry "
                "(a retry may still be billed). Try again later.")
    if resp.status_code >= 400:
        return f"ERROR: X API returned {resp.status_code}: {resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return f"ERROR: unexpected X API response: {resp.text[:300]}"

    posts = data.get("data", [])
    if not posts:
        return f"No recent (last 7 days) posts found for query: {query}"

    users = {u["id"]: u.get("username", "unknown")
            for u in data.get("includes", {}).get("users", [])}
    lines = [f"{len(posts)} recent post(s) for query {query!r} "
            f"(7-day window, billed as {len(posts)} read(s)):"]
    for post in posts:
        username = users.get(post.get("author_id"), "unknown")
        url = f"https://x.com/{username}/status/{post.get('id')}"
        text = (post.get("text") or "").replace("\n", " ")[:280]
        lines.append(f"- @{username} ({post.get('created_at', '')}): {text}\n  {url}")
    return "\n".join(lines)
