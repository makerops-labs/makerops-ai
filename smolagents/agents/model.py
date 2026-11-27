"""Model factory: all agents get their LLM through here."""

from typing import Literal

from openai import OpenAI
from smolagents import OpenAIServerModel
from smolagents.models import REMOVE_PARAMETER

from . import config

Role = Literal["coding", "general"]


def route(model_id: str) -> tuple[str, str]:
    """(api_base, model name to send) for a model id.

    Ids listed in SMOLAGENTS_LLAMACPP_MODELS go to the llama.cpp router under
    their ':'-free preset name; everything else goes to Ollama unchanged.
    """
    if model_id in config.LLAMACPP_MODELS:
        return config.LLAMACPP_API_BASE, model_id.replace(":", "-")
    return config.OLLAMA_API_BASE, model_id


def raw_client(model_id: str) -> tuple[OpenAI, str]:
    """OpenAI client + model name for plain (tool-less) completions, routed
    like get_model()."""
    base, name = route(model_id)
    return OpenAI(base_url=base, api_key=config.OLLAMA_API_KEY), name


def get_model(role: Role = "general", model_id: str | None = None) -> OpenAIServerModel:
    """Return the model for the given role (Ollama or llama.cpp, see route()).

    role="coding" uses SMOLAGENTS_CODING_MODEL_ID (code generation),
    role="general" uses SMOLAGENTS_GENERAL_MODEL_ID (planning, chat,
    research). An explicit model_id overrides the role.
    """
    if model_id is None:
        model_id = config.CODING_MODEL_ID if role == "coding" else config.GENERAL_MODEL_ID
    api_base, name = route(model_id)
    return OpenAIServerModel(
        model_id=name,
        api_base=api_base,
        api_key=config.OLLAMA_API_KEY,
        # Explicit ceiling per call: without it a wedged Ollama request can
        # hold a background job "running" for hours (see config.py).
        client_kwargs={"timeout": config.MODEL_TIMEOUT_S,
                       "max_retries": config.MODEL_MAX_RETRIES},
        # smolagents sends tool_choice="required" by default. Ollama ignores it;
        # llama.cpp enforces it with a grammar that won't let the model end a
        # plain-text answer, so it restates the answer until the context fills
        # (2026-11-27: 2-5 runaways per ops-eval run, 0 with the field omitted).
        # Omitting it matches what Ollama has always done.
        tool_choice=REMOVE_PARAMETER,
    )
