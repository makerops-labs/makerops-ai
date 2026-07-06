"""Speech (audio creation) tools. Renders text to speech through the local
Kokoro TTS service (OpenAI-compatible) and serves the files back via the
/files static mount. STT is deliberately not exposed — no agent task needs
it yet."""

import re
import time

import httpx
from fastmcp import FastMCP

from . import config, policy
from .client import DEFAULT_TIMEOUT

mcp = FastMCP(
    "speech",
    instructions="Audio creation (Kokoro TTS): render text/scripts to speech audio files.")
required_env = None  # local CPU service, no token

# CPU synthesis of long scripts is slow — allow minutes, fail connects fast.
_TTS_TIMEOUT = httpx.Timeout(180.0, connect=5.0)
_MAX_TEXT_CHARS = 5000
_FORMATS = ("mp3", "wav", "opus", "flac")

_AUDIO_DIR = config.DATA_DIR / "generated" / "audio"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "speech"


@mcp.tool
def speech_list_voices() -> str:
    """List the voice ids available for speech_generate_audio. Voice ids are
    prefixed by language/gender (e.g. af_ = American female, am_ = American
    male, bf_/bm_ = British)."""
    try:
        resp = httpx.get(f"{config.SPEECH_TTS_URL}/v1/audio/voices",
                         timeout=DEFAULT_TIMEOUT)
    except httpx.ConnectError:
        return "ERROR: connection to the speech service refused — is ai/private speech started?"
    except httpx.HTTPError as exc:
        return f"ERROR: speech service request failed: {exc}"
    if resp.status_code >= 400:
        return f"ERROR: speech service returned {resp.status_code}: {resp.text[:300]}"
    try:
        voices = [v["id"] for v in resp.json().get("voices", [])]
    except (ValueError, KeyError, TypeError):
        return f"ERROR: unexpected voices response: {resp.text[:300]}"
    return f"{len(voices)} voices (default {config.SPEECH_TTS_VOICE}): " + ", ".join(voices)


def _do_generate_audio(params: dict) -> str:
    voice = params.get("voice") or config.SPEECH_TTS_VOICE
    fmt = params.get("response_format") or "mp3"
    try:
        resp = httpx.post(
            f"{config.SPEECH_TTS_URL}/v1/audio/speech",
            json={"model": "kokoro", "input": params["text"], "voice": voice,
                  "speed": params.get("speed", 1.0), "response_format": fmt},
            timeout=_TTS_TIMEOUT)
    except httpx.ConnectError:
        return "ERROR: connection to the speech service refused — is ai/private speech started?"
    except httpx.TimeoutException:
        return ("ERROR: speech synthesis timed out — the script may be too long; "
                f"split it into chunks under {_MAX_TEXT_CHARS} characters.")
    except httpx.HTTPError as exc:
        return f"ERROR: speech service request failed: {exc}"
    if resp.status_code >= 400:
        return f"ERROR: speech service returned {resp.status_code}: {resp.text[:300]}"

    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(params['text'])}.{fmt}"
    (_AUDIO_DIR / name).write_bytes(resp.content)
    return (f"Audio generated (voice {voice}, {len(resp.content)} bytes): "
            f"{config.MCPTOOLS_PUBLIC_URL}/files/audio/{name}")


policy.register_executor("speech", "speech_generate_audio", _do_generate_audio)


@mcp.tool
def speech_generate_audio(text: str, voice: str = "", speed: float = 1.0,
                          response_format: str = "mp3") -> str:
    """WRITE ACTION — renders text to a speech audio file with the local
    Kokoro TTS and returns a downloadable URL. text: the script to speak,
    up to ~5000 characters (split longer scripts into multiple calls).
    voice: a voice id from speech_list_voices (default from config).
    speed: 0.5–2.0. response_format: mp3, wav, opus, or flac.
    Synthesis is CPU-only and can take a minute for long scripts.
    The user is notified with a summary."""
    if not text.strip():
        return "ERROR: text is empty."
    if len(text) > _MAX_TEXT_CHARS:
        return (f"ERROR: text is {len(text)} characters; the limit is "
                f"{_MAX_TEXT_CHARS}. Split the script and call once per chunk.")
    if response_format not in _FORMATS:
        return f"ERROR: response_format must be one of {_FORMATS}."
    if not 0.5 <= speed <= 2.0:
        return "ERROR: speed must be between 0.5 and 2.0."
    return policy.apply_policy(
        domain="speech", tool="speech_generate_audio", action_kind="create",
        summary=f"Generate speech audio: {text[:100]}",
        params={"text": text, "voice": voice, "speed": speed,
                "response_format": response_format},
        changes=[f"New audio file ({response_format}, voice "
                 f"{voice or config.SPEECH_TTS_VOICE}): {text[:100]}"])
