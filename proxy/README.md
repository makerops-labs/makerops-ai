# proxy — name-proxy drop-in for the private AI routes

makerops-core's [name-proxy](https://github.com/makerops-labs/makerops-core)
maps `*.localhost` subdomains to host ports. The public repo only carries
routes for its own services; this directory provides the routes for the
private AI stack as a **drop-in template** that never appears in the public
repo (makerops-core gitignores `local-*.conf.template`).

## Install (enable routes + landing-page cards)

```bash
cp local-ai.conf.template \
   ../../makerops-core/infrastructure/name-proxy/nginx/templates/
cp local-services.json \
   ../../makerops-core/infrastructure/name-proxy/html/
cp -r icons \
   ../../makerops-core/infrastructure/name-proxy/html/local-icons
cd ../../makerops-core/infrastructure/name-proxy
docker compose -p name-proxy up -d --force-recreate
```

nginx's docker entrypoint renders every `*.template` in the templates
directory at container start — no compose or env changes needed. The
landing page at `root.localhost` fetches `local-services.json` (an
optional, untracked manifest of `{ "Category": [entries] }`) and merges
each group into its category section — categories the public page doesn't
know render after the known ones. A 404 means the page simply shows the
public services only. Entry icons resolve relative to the page, so the
manifest points at `local-icons/…` (copied above; also untracked). The
`html/` directory is bind-mounted, so JSON/icon changes appear on
refresh — only the routes template needs the container recreate.

Routes added: `openwebui.localhost`, `agents.localhost`,
`search.localhost`, `mcp.localhost`, `stt.localhost`, `tts.localhost`,
`trellis.localhost`, `alexa.localhost` (alexa-bridge — local dev only,
separate from the public Cloudflare Tunnel route real Alexa traffic uses,
see `../alexa-bridge/README.md`; reuses `smolagents.png` as its icon since
there's no dedicated one).

## Install (Cloudflare Tunnel ingress for alexa-bridge)

A second, separate drop-in for `makerops-core/remote_access/cloudflared/`
(unrelated to name-proxy above — this configures the tunnel that exposes
alexa-bridge to the public internet, not a LAN-only `*.localhost` route):

```bash
cp cloudflared-config.yml.template \
   ../../makerops-core/remote_access/cloudflared/config/config.yml
```

Then fill in `<TUNNEL_ID>`, `<CREDENTIALS_FILE>`, and `<YOUR_DOMAIN>` in
the copied file — see `remote_access/cloudflared/README.md` for the
one-time tunnel setup that produces the first two. Recreate after any
change: `docker compose -p cloudflared up -d --force-recreate` from that
directory.

## Uninstall (disable routes + cards)

```bash
rm ../../makerops-core/infrastructure/name-proxy/nginx/templates/local-ai.conf.template
rm ../../makerops-core/infrastructure/name-proxy/html/local-services.json
rm -r ../../makerops-core/infrastructure/name-proxy/html/local-icons
cd ../../makerops-core/infrastructure/name-proxy
docker compose -p name-proxy up -d --force-recreate
```

## Notes

- Ports are hardcoded in the template and match each service's `.env`
  default. If you change a service's host port, edit your installed copy
  (and this source) to match.
- A route whose service is stopped returns **502** — that is the intended
  graceful failure; the proxy itself stays healthy.
- The public landing page (`root.localhost`) does not list the private
  services; their direct URLs are in the top-level [README](../README.md).
