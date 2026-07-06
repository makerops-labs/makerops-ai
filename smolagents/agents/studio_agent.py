"""Studio agent: media asset creation — images (ComfyUI/FLUX), diagrams
(draw.io), and spoken audio (Kokoro TTS via the mcp-tools speech domain).
Video generation is not part of the stack yet and is declared out of scope."""

from smolagents import ToolCallingAgent

from . import config
from .context import with_baseline
from .model import get_model
from .tools import get_domains_tools

STUDIO_DOMAINS = ("comfyui", "drawio", "speech")


def build_studio_agent() -> ToolCallingAgent:
    tools = get_domains_tools(*STUDIO_DOMAINS)
    return ToolCallingAgent(
        tools=tools,
        model=get_model("general"),
        name="studio",
        description=(
            "Creates media assets: images from text prompts (ComfyUI/FLUX), "
            "diagrams (draw.io), and spoken audio from scripts (Kokoro "
            "TTS). Give it a complete creative brief: subject, style, "
            "dimensions or voice, and how the asset will be used. Video "
            "generation is NOT available — do not send video tasks."
        ),
        instructions=with_baseline(
            "Turn the brief into concrete tool parameters: for images, "
            "write a detailed prompt (subject, style, composition, "
            "lighting) and a negative prompt for common flaws; for audio, "
            "pass the script verbatim and pick a fitting voice "
            "(speech_list_voices). Image and audio generation take up to a "
            "few minutes — that is normal, wait for the tool result. Always "
            "return the asset URLs the tools give you. Video generation is "
            "out of scope for this stack: report it as unavailable rather "
            "than attempting a workaround. When a tool answers PENDING "
            "APPROVAL, report the pending id and stop — never retry."
        ),
        max_steps=config.MAX_STEPS,
    )
