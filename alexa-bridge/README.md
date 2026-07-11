# alexa-bridge — Amazon Alexa custom-skill backend

The one thing in this stack meant to be reachable from the public internet.
Amazon Alexa devices always round-trip through Amazon's cloud, even for
"local" commands — this service is the narrow, signature-verified endpoint
that cloud calls into. Everything it talks to (mcp-tools, smolagents, Open
WebUI) stays LAN-only; only this endpoint is exposed, via a Cloudflare
Tunnel in `makerops-core/remote_access/cloudflared/` — see
`docs/alexa-voice-setup.md` for the full setup walkthrough (Cloudflare +
Alexa Developer Console steps).

## Architecture

```
Echo device → Amazon Alexa cloud → Cloudflare Tunnel → this service (POST /alexa)
                                                            │
                              verify signature+timestamp+Application ID
                                                            │
                          deterministic intents ─────┬───── free-form utterance
                     (end session / confirm-deny /   │        (AskLiaisonIntent)
                      status / start-over)            │              │
                              │                        │              ▼
                  mcp-tools /approvals/{id}/{verb}      │    mcp-tools liaison_turn
                  mcp-tools agent_job_status ◄──────────┘    (smolagents alexa_liaison agent)
```

Deterministic voice commands never reach the liaison agent — see
`alexa/intents.py`. Confirming or denying a pending write-approval action
is the one that matters most: it calls mcp-tools' `/approvals/{id}/{verb}`
route directly, the same one its own web UI uses, so a gated action is
never approved by an LLM's guess at what "yes" means.

## Start

```bash
./start.sh
```

Creates `.env` from `.env.example` on first run. Set `APPROVALS_TOKEN` to
match `mcp-tools/.env`'s value immediately; `ALEXA_SKILL_APPLICATION_ID`
can stay empty until the skill exists in the Alexa Developer Console (see
`docs/alexa-voice-setup.md`), but must be set before the tunnel goes live —
it's the main defense against a leaked endpoint being replayed from an
unrelated skill.

## Signature verification

`alexa/verify.py` reimplements Amazon's documented request-verification
algorithm directly on the `cryptography` library's own X.509 verification
API, rather than using `ask-sdk-webservice-support`'s `RequestVerifier`:
that library's certificate-chain validation depends on
`certvalidator` → `oscrypto`, and `oscrypto` has a long-standing unfixed
bug parsing OpenSSL 3.x version strings with a two-digit patch number
(e.g. `"3.0.13"`, ubiquitous on any current Debian/Ubuntu base, including
this service's own `python:3.12-slim` image) — confirmed locally by
attempting to import it, not a theoretical concern. See that module's
docstring for the full explanation and how the replacement logic was
validated against a synthetic certificate chain before being deployed.

## Local dev route

`http://alexa.localhost/healthz` works once the private name-proxy
drop-in is installed (`../proxy/README.md`) — separate from the public
Cloudflare route, purely for local testing without the tunnel involved.

## Verify

```bash
curl -s http://localhost:8103/healthz | python3 -m json.tool
```

With `DEV_MODE=true` in `.env` (never in production — it skips signature
verification), POST a hand-crafted Alexa request JSON to `/alexa` to
exercise routing without a real Echo device or registered skill:

```bash
curl -s -X POST http://localhost:8103/alexa -H 'Content-Type: application/json' -d '{
  "version": "1.0",
  "session": {"new": true, "sessionId": "s1",
    "application": {"applicationId": "a"}, "user": {"userId": "test-user"}},
  "context": {"System": {"application": {"applicationId": "a"},
    "user": {"userId": "test-user"}}},
  "request": {"type": "LaunchRequest", "requestId": "r1",
    "timestamp": "2026-01-01T00:00:00Z", "locale": "en-US"}
}' | python3 -m json.tool
```

Once a real skill exists, the Alexa Developer Console's Simulator sends
genuine Amazon-signed requests — the only way to confirm signature
verification passes against the real thing rather than just synthetic
payloads (tail `docker logs alexa-bridge -f` while testing there).

## Files

| File | Purpose |
| --- | --- |
| `main.py` | FastAPI app: `POST /alexa`, `GET /healthz` |
| `alexa/verify.py` | Signature + timestamp + Application ID verification |
| `alexa/intents.py` | Deterministic-intent routing + liaison fallback |
| `alexa/mcp_client.py` | Thin client for mcp-tools' `liaison`/`agents` domains + the `/approvals` route |
| `alexa/config.py` | Environment-driven configuration |
| `interaction-model/en-US.json` | Alexa interaction model (paste into the Developer Console, or `ask deploy`) |
| `interaction-model/skill.json` | Skill manifest for `ask-cli` deploys (optional path) |

## Stop / Teardown

```bash
./stop.sh       # stop, keep the image
./teardown.sh   # interactive full removal
```
