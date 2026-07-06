"""TRELLIS (image-to-3D) tools. Submits an image to the local TRELLIS job
server, polls until the GLB is baked, then copies it under the /files static
mount so the URL stays valid after the GPU service is stopped."""

import re
import time

import httpx
from fastmcp import FastMCP

from . import config, policy
from .client import DEFAULT_TIMEOUT

mcp = FastMCP(
    "trellis",
    instructions="3D model generation (TRELLIS): turn a single image into a textured GLB 3D model.")
required_env = None  # local GPU service, no token

_POLL_INTERVAL_S = 5
# Generation is 1-3 min; the first job adds pipeline load + kernel JIT.
_POLL_TIMEOUT_S = 900
_TEXTURE_SIZES = (512, 1024, 2048)

_MODELS_DIR = config.DATA_DIR / "generated" / "models"

_START_HINT = ("is makerops-ai/trellis started? (trellis/start.sh — it is "
               "stopped by default to free the GPU; do not retry, tell the user)")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "model"


def _fetch_image(image_url: str) -> bytes | str:
    """Return the image bytes, or an ERROR string. Public URLs of sibling
    services don't resolve inside this container — rewrite them to their
    backend equivalents first."""
    url = image_url
    if url.startswith(config.COMFYUI_PUBLIC_URL):
        url = config.COMFYUI_URL + url[len(config.COMFYUI_PUBLIC_URL):]
    elif url.startswith(f"{config.MCPTOOLS_PUBLIC_URL}/files/"):
        rel = url[len(f"{config.MCPTOOLS_PUBLIC_URL}/files/"):]
        path = (config.DATA_DIR / "generated" / rel).resolve()
        if not path.is_relative_to(config.DATA_DIR / "generated") or not path.is_file():
            return f"ERROR: no such generated file: {rel}"
        return path.read_bytes()
    try:
        resp = httpx.get(url, timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        return f"ERROR: could not fetch image_url: {exc}"
    if resp.status_code >= 400:
        return f"ERROR: image_url returned {resp.status_code}"
    ctype = resp.headers.get("content-type", "").split(";")[0]
    if not ctype.startswith("image/"):
        return f"ERROR: image_url is {ctype or 'unknown type'}, not an image"
    if len(resp.content) > config.FETCH_MAX_DOWNLOAD_BYTES:
        return f"ERROR: image exceeds {config.FETCH_MAX_DOWNLOAD_BYTES} bytes"
    return resp.content


def _do_image_to_3d(params: dict) -> str:
    image = _fetch_image(params["image_url"])
    if isinstance(image, str):
        return image

    try:
        resp = httpx.post(
            f"{config.TRELLIS_URL}/generate",
            files={"image": ("input.png", image)},
            data={"seed": params.get("seed") if params.get("seed") is not None else -1,
                  "texture_size": params.get("texture_size", 1024),
                  "simplify": params.get("simplify", 0.95)},
            timeout=DEFAULT_TIMEOUT)
    except httpx.ConnectError:
        return f"ERROR: connection to the TRELLIS service refused — {_START_HINT}"
    except httpx.HTTPError as exc:
        return f"ERROR: TRELLIS request failed: {exc}"
    if resp.status_code >= 400:
        return f"ERROR: TRELLIS rejected the job ({resp.status_code}): {resp.text[:300]}"
    job = resp.json()
    job_id, seed = job["job_id"], job["seed"]

    deadline = time.time() + _POLL_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        try:
            status = httpx.get(f"{config.TRELLIS_URL}/jobs/{job_id}",
                               timeout=DEFAULT_TIMEOUT).json()
        except (httpx.HTTPError, ValueError):
            continue
        if status.get("status") == "failed":
            return f"ERROR: TRELLIS generation failed: {status.get('error', '?')[:300]}"
        if status.get("status") == "completed":
            break
    else:
        return (f"ERROR: generation timed out after {_POLL_TIMEOUT_S}s "
                f"(job {job_id} — it may still finish; check the trellis service).")

    try:
        glb = httpx.get(f"{config.TRELLIS_URL}/jobs/{job_id}/model.glb",
                        timeout=httpx.Timeout(120.0, connect=5.0))
        glb.raise_for_status()
    except httpx.HTTPError as exc:
        return f"ERROR: could not download the finished GLB: {exc}"

    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(params['image_url'].rsplit('/', 1)[-1])}.glb"
    (_MODELS_DIR / name).write_bytes(glb.content)
    return (f"3D model generated (seed {seed}, {len(glb.content)} bytes, GLB): "
            f"{config.MCPTOOLS_PUBLIC_URL}/files/models/{name} — opens in any "
            f"glTF viewer (e.g. Blender, Windows 3D Viewer).")


policy.register_executor("trellis", "trellis_image_to_3d", _do_image_to_3d)


@mcp.tool
def trellis_image_to_3d(image_url: str, seed: int | None = None,
                        texture_size: int = 1024, simplify: float = 0.95) -> str:
    """WRITE ACTION — converts an image into a textured 3D model (GLB) with
    the local TRELLIS service and returns a downloadable URL. image_url: an
    image URL, e.g. one returned by comfyui_generate_image; a single centered
    object on a plain background converts best. texture_size: 512, 1024 or
    2048. simplify: mesh decimation 0-0.98 (higher = lighter mesh).
    Generation takes 2-5 minutes (up to ~10 on the first call while the model
    loads) — do not retry while a call is in flight. The trellis service is
    started on demand; if the connection is refused, report that to the user
    instead of retrying. The user is notified with a summary."""
    if texture_size not in _TEXTURE_SIZES:
        return f"ERROR: texture_size must be one of {_TEXTURE_SIZES}."
    if not 0 <= simplify <= 0.98:
        return "ERROR: simplify must be between 0 and 0.98."
    if not image_url.startswith(("http://", "https://")):
        return "ERROR: image_url must be an http(s) URL."
    return policy.apply_policy(
        domain="trellis", tool="trellis_image_to_3d", action_kind="create",
        summary=f"Generate 3D model from image: {image_url[:100]}",
        params={"image_url": image_url, "seed": seed,
                "texture_size": texture_size, "simplify": simplify},
        changes=[f"New 3D model (GLB, texture {texture_size}px) from {image_url[:100]}"])
