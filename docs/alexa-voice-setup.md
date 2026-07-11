# Alexa Voice Setup (Cloudflare Tunnel + Alexa Developer Console)

Manual, human-only steps to make the MakerOps stack voice-controllable
from real Amazon Echo devices. The code side — the `alexa_liaison` agent
(`smolagents/agents/alexa_liaison.py`), mcp-tools' `liaison` domain, and
the `alexa-bridge` service — is already built; see
[alexa-bridge/README.md](../alexa-bridge/README.md) for the architecture.
This doc is purely the runbook for the console/CLI steps that can't be
scripted, kept here so redoing them after a rebuild doesn't mean
re-deriving them from scratch.

Real Echo devices always round-trip through Amazon's cloud, even for
"local" commands — there is no way around this with a Custom Skill. The
setup below exposes exactly one narrow endpoint (`alexa-bridge`) to the
public internet via a Cloudflare Tunnel; everything behind it stays
LAN-only.

Do these in order — the Alexa skill's endpoint URL needs the tunnel's
hostname to already resolve.

## Prerequisites

- A Cloudflare account with your domain added as a zone (the same one
  `makerops-core/remote_access/cloudflare-ddns` already manages).
- `alexa-bridge/.env` created (`alexa-bridge/start.sh` does this on first
  run) with `APPROVALS_TOKEN` set to match `mcp-tools/.env`'s value.
- mcp-tools recreated with the `liaison` domain mounted and smolagents
  restarted to build the liaison agent — see checklist §5i in
  [ai-setup-checklist.md](ai-setup-checklist.md).

## 1. Cloudflare Tunnel

All commands run from `makerops-core/remote_access/cloudflared/`.

1. **Authenticate:**
   ```bash
   docker run --rm -it -v "$(pwd)/config:/etc/cloudflared" cloudflare/cloudflared \
     tunnel login
   ```
   Opens a browser to authorize against your Cloudflare account.
   *Verify:* `config/cert.pem` now exists.

2. **Create the tunnel:**
   ```bash
   docker run --rm -it -v "$(pwd)/config:/etc/cloudflared" cloudflare/cloudflared \
     tunnel create alexa-bridge
   ```
   *Verify:* prints a tunnel ID (UUID) and writes
   `config/<tunnel-id>.json` — note the ID for the next step.

3. **Supply the ingress config:**
   ```bash
   cp ../../../makerops-ai/proxy/cloudflared-config.yml.template config/config.yml
   ```
   Edit `config/config.yml`: replace `<TUNNEL_ID>` and `<CREDENTIALS_FILE>`
   with the values from step 2, and `<YOUR_DOMAIN>` with your actual
   domain. *Verify:* `cat config/config.yml` shows real values, no
   placeholders left.

4. **Route DNS:**
   ```bash
   docker run --rm -it -v "$(pwd)/config:/etc/cloudflared" cloudflare/cloudflared \
     tunnel route dns alexa-bridge alexa.<your-domain>
   ```
   *Verify:* Cloudflare dashboard → DNS shows a new CNAME record for
   `alexa.<your-domain>`.

5. **Start it:**
   ```bash
   ./start.sh
   ```
   *Verify:* `docker compose -p cloudflared logs -f` shows the tunnel
   connecting (look for "Registered tunnel connection").

6. **Verify the public hop** (once DNS has propagated — usually under a
   minute), from an external network (mobile data, not your home WiFi, so
   you're actually testing the public path):
   ```bash
   curl -s https://alexa.<your-domain>/healthz
   ```
   *Verify:* returns `{"status":"ok"}`. If this fails, check
   `alexa-bridge` is running (`curl -s http://localhost:8103/healthz`
   locally) before troubleshooting the tunnel.

## 2. Alexa Developer Console

1. **Amazon Developer account** — <https://developer.amazon.com>, same
   account signed into your Echo devices.

2. **Create the skill:** Alexa Developer Console → *Create Skill* →
   name it (e.g. "MakerOps") → Custom model → **"Provision your own"**
   backend (this skips Lambda scaffolding entirely — it's the self-hosted
   HTTPS endpoint path, not the default Lambda one).
   *Verify:* skill dashboard loads with an empty interaction model.

3. **Interaction model:** Build tab → JSON Editor → paste the contents of
   [alexa-bridge/interaction-model/en-US.json](../alexa-bridge/interaction-model/en-US.json)
   → Save Model → Build Model. (Alternative: `ask deploy` via `ask-cli` if
   you have it configured, using
   [skill.json](../alexa-bridge/interaction-model/skill.json) +
   the interaction model file.)
   *Verify:* "Build Model" succeeds with no errors; the invocation name
   shows as "maker ops".

4. **Endpoint:** Build tab → Endpoint → HTTPS →
   `https://alexa.<your-domain>/alexa` → SSL certificate type: **"My
   development endpoint has a certificate from a trusted certificate
   authority"** (true — Cloudflare Tunnel terminates TLS with a CA-signed
   cert automatically) → Save Endpoints.
   *Verify:* no validation error on save.

5. **Set the Application ID:** copy the Skill ID shown at the top of the
   console (format `amzn1.ask.skill.…`) into `alexa-bridge/.env`'s
   `ALEXA_SKILL_APPLICATION_ID`, then recreate the container (env changes
   need a recreate, not a restart):
   ```bash
   cd alexa-bridge && docker compose -p alexa-bridge up -d
   ```
   *Verify:* `docker logs alexa-bridge --tail 5` shows a clean startup, no
   crash.

6. **Enable testing:** Test tab → toggle from "Off" to **"Development"**.
   This alone makes the skill live on Echo devices signed into the same
   Amazon account — no separate publish step needed for personal use.
   *Verify:* the Test tab's simulator becomes usable.

## 3. Verification

Before touching a real device, the Test tab's Simulator sends genuine
Amazon-signed requests through the actual configured HTTPS endpoint — the
only way to confirm signature verification passes against the real thing,
not just synthetic payloads (see `alexa-bridge/README.md`'s Verify section
for the curl-based synthetic tests, which won't touch this):

- Type `open maker ops` → should get "MakerOps is listening — what do you
  need?" Tail `docker logs alexa-bridge -f` while doing this to confirm
  signature verification actually ran and passed.
- Ask something ambiguous → confirm exactly one clarifying question comes
  back, not a guess.
- Ask a direct question → confirm a spoken answer.
- Say "status" → confirm it reports on the last thing asked.
- Trigger a write action that hits mcp-tools' approval gate, then say
  "confirm" → confirm it resolves via `/approvals` directly (check
  mcp-tools logs — the liaison/LLM should not appear in that call path).
- Say "goodbye" → confirm the session ends cleanly.

Then repeat on a real Echo device on the same Amazon account — this
validates the full round trip including microphone/speaker UX and the
natural pause in the async "still working, check status later" flow.

## Known limitations (see also `alexa-bridge/README.md` and
`smolagents/agents/alexa_liaison.py`'s module docstring)

- Status tracks the single most recent turn per Alexa user — dispatching a
  second request before checking on the first makes "status" ambiguous.
- A liaison session (conversation history) is keyed by Alexa's stable
  `userId`, not the ephemeral per-invocation session — it survives
  Alexa's own ~8s-silence session timeout but goes stale and resets after
  `SMOLAGENTS_LIAISON_SESSION_STALE_HOURS` (default 6h) of inactivity.
