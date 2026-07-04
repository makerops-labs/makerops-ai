"""Shared HTTP helpers for the service tool modules.

Tools never raise: every helper returns either parsed data or an error string
starting with "ERROR:" so agent loops degrade gracefully instead of crashing.
"""

import json
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


def make_client(base_url: str, headers: dict[str, str] | None = None,
                timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers=headers or {}, timeout=timeout,
                        follow_redirects=True)


def request_json(client: httpx.Client, method: str, path: str, *,
                 service: str, token_hint: str = "",
                 **kwargs: Any) -> tuple[bool, Any]:
    """Perform a request expecting JSON. Returns (ok, data_or_error_string)."""
    try:
        resp = client.request(method, path, **kwargs)
    except httpx.ConnectError:
        return False, (f"ERROR: connection to {service} refused at {client.base_url} — "
                       f"is the service started?")
    except httpx.TimeoutException:
        return False, f"ERROR: request to {service} timed out."
    except httpx.HTTPError as exc:
        return False, f"ERROR: request to {service} failed: {exc}"

    if resp.status_code in (401, 403):
        hint = f" — check {token_hint}" if token_hint else ""
        return False, f"ERROR: {service} returned {resp.status_code}{hint}"
    if resp.status_code >= 400:
        body = resp.text[:300]
        return False, f"ERROR: {service} returned {resp.status_code}: {body}"
    if not resp.content:
        return True, {}
    try:
        return True, resp.json()
    except (json.JSONDecodeError, ValueError):
        return True, resp.text


def fmt(data: Any, max_chars: int = 6000) -> str:
    """Render API data as compact JSON for the model, truncated politely."""
    if isinstance(data, str):
        text = data
    else:
        text = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated at {max_chars} chars]"
    return text
