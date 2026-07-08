# trellis — Image-to-3D generation

[microsoft/TRELLIS](https://github.com/microsoft/TRELLIS) (`TRELLIS-image-large`,
1.2B params, MIT) wrapped in a small FastAPI job server (`serve.py`): a single
image in, a textured GLB 3D model out. Exposed to agents through the
`trellis` domain on mcp-tools (studio agent).

> Why not TRELLIS.2? The 4B follow-up needs ≥24 GB VRAM (issues report OOM
> even on 80 GB cards); this card has 16 GB. TRELLIS 1.x officially fits.

## Ports

| Port | What |
| --- | --- |
| 8094 | Web GUI at `/` + job server API (also `http://trellis.localhost` via name-proxy) |

## Web GUI

`http://trellis.localhost` (or `localhost:8094`) serves a single-page GUI
(`index.html`, bind-mounted like `serve.py`): drop an image, set
seed/texture/simplify, and watch the job; the result renders in an
interactive 3D viewer with a download button. The viewer uses Google's
`<model-viewer>` component from a CDN, so the *browser* needs internet —
generation itself is fully local.

## API usage

```bash
./start.sh          # build (first time 20-40 min) + start
curl -s localhost:8094/healthz | jq          # wait for weights_ready:true

# submit a job (single centered object on a plain background works best)
curl -s -F image=@object.png -F seed=1 localhost:8094/generate
# → {"job_id":"abc123def456","seed":1}

curl -s localhost:8094/jobs/abc123def456 | jq        # queued|running|completed|failed
curl -o model.glb localhost:8094/jobs/abc123def456/model.glb

./stop.sh           # free the GPU when done
```

`POST /generate` form fields: `image` (file, required), `seed` (int, -1 =
random), `texture_size` (512|1024|2048, default 1024), `simplify` (0–0.98
mesh decimation, default 0.95), `ss_steps`/`ss_cfg` and `slat_steps`/`slat_cfg`
(sampler steps/guidance, defaults 12/7.5 and 12/3.0).

GLB files open in Blender, Windows 3D Viewer, or <https://gltf-viewer.donmccurdy.com/>.

## VRAM (16 GB card, shared with Ollama + ComfyUI)

- A generation needs most of the card (measured 2026-07-06: **15.2 GiB peak**
  of 16.4 with default settings); the service is **start-on-demand** — start
  it for 3D work, stop it after.
- Inside the container the pipeline lazy-loads on the first job and unloads
  after `TRELLIS_IDLE_UNLOAD_S` (default 600 s) idle, so a running-but-idle
  container holds no VRAM.
- **The idle container still holds ~5.4 GB of host RAM** (torch runtime +
  cached weights) even after the VRAM unload. On the 24 GB WSL2 cap that is
  the difference between the qwen3.6:35b variants loading or being
  OOM-killed (`signal: killed` during tensor load — observed 2026-07-06).
  `./stop.sh` when 3D work is done, not just idle.
- WSL2 CUDA spills into shared system RAM when an LLM is resident — slow but
  survives. For full speed, generate while Ollama models are idle.
- If a job OOMs: lower `texture_size` to 512 and `slat_steps`/`ss_steps` to 8;
  if that's not enough, the low-VRAM community fork
  [trellis-stable-projectorz](https://github.com/IgorAherne/trellis-stable-projectorz)
  (claims 8 GB) can replace the upstream clone in the Dockerfile — serve.py
  and everything downstream stay unchanged.

## First run

1. `start.sh` builds the image (compiles two CUDA extensions, pinned commits)
   and starts the container.
2. The container downloads ~4.5 GB of model weights in the background into
   `data/hf/` (`/healthz` → `weights_ready`). DINOv2 (torch.hub → `data/torch/`)
   and the rembg background-removal model (`data/u2net/`) download on the
   first job.
3. The first generation also loads the pipeline and JIT-compiles nvdiffrast
   kernels (measured: ~160 s); warm generations take ~20 s at default
   settings.

## Files

- `serve.py` — job server; bind-mounted, edit + `docker restart trellis`.
- `data/` (gitignored) — `hf/`, `torch/`, `u2net/` model caches; `jobs/<id>/`
  with `input.png`, `params.json`, `status.json`, `model.glb`.

## Attribution

[TRELLIS](https://github.com/microsoft/TRELLIS) — Microsoft Research, MIT
license. Structured 3D latents for scalable and versatile 3D generation.
