# Hermes Agent Setup (persistent memory, per-project profiles)

[Hermes Agent](https://hermes-agent.nousresearch.com) (Nous Research, MIT
license) is a terminal agent with a built-in learning loop: it extracts
memories from sessions, searches its own past conversations, and builds
skills over time. In this stack it is the **contextual-history layer** — it
runs on the host (not in Docker; its state lives in `~/.hermes/`) against
the local Ollama server, so nothing leaves the machine.

## Install

Follow the download instructions at
<https://hermes-agent.nousresearch.com>, then run the setup wizard:

```bash
hermes setup
```

Choose **Custom Endpoint** and enter:

| Prompt | Value |
| --- | --- |
| Base URL | `http://localhost:11434/v1` |
| API key | `no-key` (Ollama ignores it, but a value is required) |
| Model | `qwen3.5:9b-64k` |

Settings persist in `~/.hermes/config.yaml`.

### Model requirements

Hermes needs a tool-calling model with a **context window of at least 64K**.
Ollama's default context is far smaller, which is why the stack ships a
derived model (created in [ai-setup-checklist.md](ai-setup-checklist.md)):

```bash
printf 'FROM qwen3.5:9b\nPARAMETER num_ctx 64000\n' | \
  docker exec -i ollama sh -c 'cat > /tmp/Modelfile && ollama create qwen3.5:9b-64k -f /tmp/Modelfile'
```

`qwen3.5:9b-64k` is the general-domain lead (see the model hierarchy table
in [README.md](../README.md)) and supports native tool calling.

## Profile isolation policy — read before first use

Hermes memory is **global per profile**: every session in a profile feeds
the same memory store, session database, and skills directory. Left on one
profile, context from different projects bleeds together — assumptions from
one project surface as "memories" in another, and they conflict when the
projects use the same tools differently.

The fix is built in: each profile is an isolated directory under
`~/.hermes/profiles/<name>` with its own memory, sessions, and skills.
The convention for this stack:

- **One profile per project or focus** — e.g. `makerops`, plus one per
  client or side-project.
- **A `personal` profile** for cross-project, user-level context (who you
  are, standing preferences) — things that are true regardless of project.
- **Never share a profile across projects.** When in doubt, create a new
  profile; an empty memory is cheaper than a contaminated one.
- Check `hermes --help` on your installed version for the exact
  profile-selection flag/command; profile support ships with the agent but
  the CLI surface has changed between releases.

### Verify isolation

After creating two profiles, tell each one a distinguishing fact ("this
project uses Postgres" / "this project uses SQLite"), start fresh sessions
in both, and ask what database the project uses. Each profile should only
know its own fact.

## Baseline tool awareness (once per profile)

Give every profile standing knowledge of the stack's tools — no per-session
prompting:

1. Register the mcp-tools domains the profile needs via the Hermes MCP CLI
   (`http://localhost:8099/mcp/<domain>/`, one server per domain — same
   per-domain scoping rationale as
   [openwebui/contexts/](../openwebui/contexts/README.md)). Every domain
   endpoint automatically includes `tools_help(path)`, the browsable tool
   documentation tree (`''` = domain manifest, `'<domain>'`,
   `'<domain>/<tool>'` = full usage details).
2. In the profile's first session, paste the baseline block from
   [openwebui/contexts/_baseline.md](../openwebui/contexts/_baseline.md)
   and tell Hermes to remember it — per-profile persistent memory carries
   the awareness into every later session.

## Day-to-day

- Switch the backing model mid-session with `/model <name>` (any pulled
  Ollama model with tool support works).
- Keep Ollama running (`makerops-core/ai/ollama/start.sh`) before starting a session.
