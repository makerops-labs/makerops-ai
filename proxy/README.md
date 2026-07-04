# proxy — name-proxy drop-in for the private AI routes

makerops-core's [name-proxy](https://github.com/makerops-labs/makerops-core)
maps `*.localhost` subdomains to host ports. The public repo only carries
routes for its own services; this directory provides the routes for the
private AI stack as a **drop-in template** that never appears in the public
repo (makerops-core gitignores `local-*.conf.template`).

## Install (enable the routes)

```bash
cp local-ai.conf.template \
   ../../makerops-core/infrastructure/name-proxy/nginx/templates/
cd ../../makerops-core/infrastructure/name-proxy
docker compose -p name-proxy up -d --force-recreate
```

nginx's docker entrypoint renders every `*.template` in the templates
directory at container start — no compose or env changes needed.

Routes added: `openwebui.localhost`, `agents.localhost`,
`search.localhost`, `mcp.localhost`, `stt.localhost`, `tts.localhost`.

## Uninstall (disable the routes)

```bash
rm ../../makerops-core/infrastructure/name-proxy/nginx/templates/local-ai.conf.template
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
