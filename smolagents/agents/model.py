"""Model factory: all agents get their LLM through here."""

from typing import Literal

from smolagents import OpenAIServerModel

from . import config

Role = Literal["coding", "general"]


def get_model(role: Role = "general", model_id: str | None = None) -> OpenAIServerModel:
    """Return an Ollama-backed model for the given role.

    role="coding" uses SMOLAGENTS_CODING_MODEL_ID (code generation),
    role="general" uses SMOLAGENTS_GENERAL_MODEL_ID (planning, chat,
    research). An explicit model_id overrides the role.
    """
    if model_id is None:
        model_id = config.CODING_MODEL_ID if role == "coding" else config.GENERAL_MODEL_ID
    return OpenAIServerModel(
        model_id=model_id,
        api_base=config.OLLAMA_API_BASE,
        api_key=config.OLLAMA_API_KEY,
        # Explicit ceiling per call: without it a wedged Ollama request can
        # hold a background job "running" for hours (see config.py).
        client_kwargs={"timeout": config.MODEL_TIMEOUT_S,
                       "max_retries": config.MODEL_MAX_RETRIES},
    )
