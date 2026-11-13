"""Tiny stdlib HTTP helpers shared by seed.py and reset.py (no dependencies)."""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEMO_TAG = "makerops-demo"
CATEGORY = "MakerOps Demo"
# Categories can't be tagged; this exact description marks the demo one.
CATEGORY_MARKER = f"[demo] records created by demo/seed.py ({DEMO_TAG})"
LOCATION = "Demo Shop Shelf"
SUPPLIER = "Demo Supply Co."
MAILBOX = "MakerOps Demo"
CUSTOMER_EMAIL = "jordan@juniper-labs.example"
SUBJECT = "Order for 20 EN-100 enclosures"


def load_env() -> dict:
    """Read demo/.env (KEY=VALUE lines), then let real env vars override."""
    env = {}
    path = Path(__file__).with_name(".env")
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("INVENTREE_", "FREESCOUT_"))})
    missing = [k for k in ("INVENTREE_URL", "INVENTREE_API_TOKEN",
                           "FREESCOUT_URL", "FREESCOUT_API_KEY") if not env.get(k)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)} — copy demo/.env.example to demo/.env "
                 f"and fill it in (see demo/README.md).")
    return env


class Api:
    def __init__(self, base: str, headers: dict):
        self.base = base.rstrip("/")
        self.headers = {"Accept": "application/json", **headers}

    def call(self, method: str, path: str, body=None, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            **self.headers, **({"Content-Type": "application/json"} if data else {})})
        for attempt in range(8):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                return json.loads(raw) if raw.strip() else None
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 7:  # InvenTree throttles bursts
                    wait = float(exc.headers.get("Retry-After") or 5)
                    print(f"    (rate limited; waiting {wait:.0f}s)", file=sys.stderr)
                    time.sleep(wait)
                    continue
                detail = exc.read().decode(errors="replace")[:500]
                raise SystemExit(f"{method} {path} → HTTP {exc.code}: {detail}") from None

    def get(self, path, **params):
        return self.call("GET", path, params=params or None)

    def post(self, path, body):
        return self.call("POST", path, body)

    def patch(self, path, body):
        return self.call("PATCH", path, body)

    def delete(self, path, body=None):
        return self.call("DELETE", path, body)


def inventree(env) -> Api:
    return Api(env["INVENTREE_URL"], {"Authorization": f"Token {env['INVENTREE_API_TOKEN']}"})


def freescout(env) -> Api:
    return Api(env["FREESCOUT_URL"], {"X-FreeScout-API-Key": env["FREESCOUT_API_KEY"]})


def results(page):
    """InvenTree list endpoints return either a list or {"results": [...]}."""
    return page["results"] if isinstance(page, dict) else page


def find_one(api: Api, path: str, **params):
    """First record matching ALL params. Filters are re-checked client-side:
    some InvenTree list endpoints silently ignore unknown filter params (e.g.
    /api/bom/ ignores sub_part), which would otherwise match the wrong row."""
    hits = results(api.get(path, **params))
    for hit in hits:
        if all(str(hit.get(k)) == str(v) for k, v in params.items()):
            return hit
    return None


def find_mailbox(fs: Api):
    boxes = fs.get("/api/mailboxes")["_embedded"]["mailboxes"]
    return next((b for b in boxes if b["name"] == MAILBOX), None)


def demo_conversations(fs: Api, mailbox_id: int) -> list:
    page = fs.get("/api/conversations", mailboxId=mailbox_id, customerEmail=CUSTOMER_EMAIL,
                  pageSize=100)
    convs = page.get("_embedded", {}).get("conversations", [])
    # Never trust the server-side filter alone: if it were ignored, this would
    # return every conversation in the mailbox.
    return [c for c in convs if c.get("mailboxId") == mailbox_id
            and (c.get("customer") or {}).get("email") == CUSTOMER_EMAIL]
