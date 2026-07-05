"""ComfyUI (image generation) tools. Submits an API-format workflow to /prompt
and polls /history until the image is rendered."""

import json
import random
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastmcp import FastMCP

from . import config, policy
from .client import DEFAULT_TIMEOUT

mcp = FastMCP(
    "comfyui",
    instructions="Image generation (ComfyUI/FLUX): create images from text prompts.")
required_env = None  # no token; the ComfyUI API is unauthenticated on the LAN

_WORKFLOW_PATH = Path(__file__).resolve().parent.parent / "workflows" / "txt2img.json"
_POLL_INTERVAL_S = 5
_POLL_TIMEOUT_S = 300


def _first_checkpoint() -> str | None:
    """Ask ComfyUI which model checkpoints exist; used when COMFYUI_CHECKPOINT
    is unset."""
    try:
        resp = httpx.get(f"{config.COMFYUI_URL}/object_info/CheckpointLoaderSimple",
                         timeout=DEFAULT_TIMEOUT)
        options = (resp.json()["CheckpointLoaderSimple"]["input"]["required"]
                   ["ckpt_name"][0])
        return options[0] if options else None
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None


def _do_generate_image(params: dict) -> str:
    workflow = json.loads(_WORKFLOW_PATH.read_text())

    checkpoint = config.COMFYUI_CHECKPOINT or _first_checkpoint()
    if not checkpoint:
        return ("ERROR: no model checkpoint found — is makerops-core/ai/comfyui running with at "
                "least one checkpoint installed? (or set COMFYUI_CHECKPOINT)")

    seed = params.get("seed")
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    for node in workflow.values():
        ct, inputs = node.get("class_type"), node.get("inputs", {})
        if ct == "CheckpointLoaderSimple":
            inputs["ckpt_name"] = checkpoint
        elif ct == "CLIPTextEncode":
            if inputs.get("text") == "__PROMPT__":
                inputs["text"] = params["prompt"]
            elif inputs.get("text") == "__NEGATIVE__":
                inputs["text"] = params.get("negative_prompt", "")
        elif ct == "EmptyLatentImage":
            inputs["width"] = params.get("width", 1024)
            inputs["height"] = params.get("height", 1024)
        elif ct == "KSampler":
            inputs["seed"] = seed

    client_id = str(uuid.uuid4())
    try:
        resp = httpx.post(f"{config.COMFYUI_URL}/prompt",
                          json={"prompt": workflow, "client_id": client_id},
                          timeout=DEFAULT_TIMEOUT)
    except httpx.ConnectError:
        return "ERROR: connection to ComfyUI refused — is makerops-core/ai/comfyui started?"
    except httpx.HTTPError as exc:
        return f"ERROR: ComfyUI request failed: {exc}"
    if resp.status_code >= 400:
        return f"ERROR: ComfyUI rejected the workflow ({resp.status_code}): {resp.text[:400]}"
    prompt_id = resp.json().get("prompt_id")

    deadline = time.time() + _POLL_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        try:
            hist = httpx.get(f"{config.COMFYUI_URL}/history/{prompt_id}",
                             timeout=DEFAULT_TIMEOUT).json()
        except (httpx.HTTPError, ValueError):
            continue
        entry = hist.get(prompt_id)
        if not entry:
            continue
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            return f"ERROR: ComfyUI generation failed: {json.dumps(status)[:400]}"
        images = [img for out in entry.get("outputs", {}).values()
                  for img in out.get("images", [])]
        if images:
            urls = [f"{config.COMFYUI_PUBLIC_URL}/view?" + urlencode(
                {"filename": img["filename"], "type": img.get("type", "output"),
                 "subfolder": img.get("subfolder", "")}) for img in images]
            return ("Image generated (seed {seed}, model {model}):\n{urls}".format(
                seed=seed, model=checkpoint, urls="\n".join(urls)))
    return (f"ERROR: generation timed out after {_POLL_TIMEOUT_S}s "
            f"(prompt id {prompt_id} — it may still finish; check ComfyUI).")


policy.register_executor("comfyui", "comfyui_generate_image", _do_generate_image)


@mcp.tool
def comfyui_generate_image(prompt: str, negative_prompt: str = "",
                           width: int = 1024, height: int = 1024,
                           seed: int | None = None) -> str:
    """WRITE ACTION — generates an image with the local ComfyUI instance and
    returns a viewable URL. Takes up to a few minutes on first model load.
    The user is notified with a summary."""
    return policy.apply_policy(
        domain="comfyui", tool="comfyui_generate_image", action_kind="create",
        summary=f"Generate image: {prompt[:100]}",
        params={"prompt": prompt, "negative_prompt": negative_prompt,
                "width": width, "height": height, "seed": seed},
        changes=[f"New image ({width}x{height}): {prompt[:100]}"])
