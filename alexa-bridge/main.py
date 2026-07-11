"""Alexa custom-skill webservice endpoint: verifies each incoming request
(signature, timestamp, Application ID — see alexa/verify.py) then routes it
(see alexa/intents.py) to either a deterministic bridge-side action or the
smolagents alexa_liaison agent via mcp-tools. This is the ONE thing in this
stack meant to be reachable from the public internet — see
makerops-core/remote_access/cloudflared/ and
docs/alexa-voice-setup.md for how it gets there. Everything behind it
(mcp-tools, smolagents, Open WebUI) stays LAN-only.
"""

from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool

from alexa import intents, verify
from alexa.verify import VerifyError

app = FastAPI(title="alexa-bridge")


@app.post("/alexa")
async def alexa_webhook(request: Request):
    # Signature verification needs the exact raw bytes — read the body
    # before any JSON parsing touches it (see verify.py's module docstring).
    raw_body = (await request.body()).decode("utf-8")
    try:
        # verify_request does synchronous network I/O (cert chain fetch, on
        # a cache miss) and RSA verification — off the event loop so one
        # slow/cold verification can't stall other requests.
        envelope = await run_in_threadpool(
            verify.verify_request, dict(request.headers), raw_body)
    except VerifyError as exc:
        print(f"[alexa-bridge] request rejected: {exc}")
        return Response(status_code=401, content=str(exc))

    return await intents.handle(envelope)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
