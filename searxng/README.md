# SearXNG — Private Metasearch Engine

Self-hosted [SearXNG](https://github.com/searxng/searxng) instance providing
free, keyless web search by aggregating results from public engines (Google,
Bing, DuckDuckGo, and others). It is the web-search backend for the AI stack:

- **openwebui** uses it natively via `SEARXNG_QUERY_URL` (chat web search).
- **mcp-tools** exposes it to any MCP client as the `web_search` tool.

No GPU required. Safe to leave running.

## Start

```bash
./start.sh
```

- UI: <http://localhost:8098> (or <http://search.localhost> via name-proxy)
- JSON API: `http://localhost:8098/search?q=<query>&format=json`

`start.sh` creates `.env` from `.env.example` on first run and generates
`SEARXNG_SECRET`.

## Configuration

- `.env` — port, base URL, secret, data path (see `.env.example`).
- `settings.yml` — SearXNG settings overrides, bind-mounted read-only.
  Notable choices:
  - `search.formats` includes `json` — required for the API; without it,
    `format=json` requests return 403.
  - `server.limiter: false` — this is a private instance; the bot-detection
    limiter would require a Valkey sidecar and rate-limit the LLM tool callers.

To tune which engines are queried or their weights, add an `engines:` section
to `settings.yml` and restart
(see the [SearXNG engine docs](https://docs.searxng.org/admin/settings/settings_engine.html)).

## Verify

```bash
curl -s 'http://localhost:8098/search?q=test&format=json' | jq '.results[0] | {title, url}'
```

## Stop / Teardown

```bash
./stop.sh      # container stops, cache preserved
./teardown.sh  # removes containers, volumes, images (confirmation prompt)
```

## Notes

- Outbound DNS uses explicit resolvers (`8.8.8.8`, `1.1.1.1`) in the compose
  file — the WSL2 host resolver is unreachable from Docker bridge networks.
- Do not expose this instance to the public internet with the limiter
  disabled.
