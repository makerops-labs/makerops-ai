"""Studio agent: media asset creation — images (ComfyUI/FLUX), diagrams
(draw.io), spoken audio (Kokoro TTS via the mcp-tools speech domain), and
3D models from images (TRELLIS). Video generation is not part of the stack
yet and is declared out of scope."""

from smolagents import ToolCallingAgent

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools

STUDIO_DOMAINS = ("comfyui", "drawio", "speech", "trellis")


def build_studio_agent() -> ToolCallingAgent:
    tools = get_domains_tools(*STUDIO_DOMAINS)
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general"),
        name="studio",
        description=(
            "Creates media assets: images from text prompts (ComfyUI/FLUX), "
            "diagrams (draw.io), spoken audio from scripts (Kokoro TTS), "
            "and textured 3D models (GLB) from a single image (TRELLIS). "
            "Give it a complete creative brief: subject, style, dimensions "
            "or voice, and how the asset will be used. Video generation is "
            "NOT available — do not send video tasks."
        ),
        instructions=with_baseline(
            "Turn the brief into concrete tool parameters: for images, "
            "write a detailed prompt (subject, style, composition, "
            "lighting) and a negative prompt for common flaws; for audio, "
            "pass the script verbatim and pick a fitting voice "
            "(speech_list_voices). For 3D models, generate or obtain the "
            "source image first — a single centered object on a plain "
            "background converts best — then pass its URL to "
            "trellis_image_to_3d. Image and audio generation take up to a "
            "few minutes and 3D generation up to ~10 — that is normal, wait "
            "for the tool result; never start a second generation while one "
            "is in flight. If trellis reports its connection refused, the "
            "on-demand GPU service is stopped: tell the user to run "
            "trellis/start.sh instead of retrying. Always return the asset "
            "URLs the tools give you. Video generation is out of scope for "
            "this stack: report it as unavailable rather than attempting a "
            "workaround. When a tool answers PENDING APPROVAL, report the "
            "pending id and stop — never retry."
        ),
        max_steps=config.MAX_STEPS,
    )
