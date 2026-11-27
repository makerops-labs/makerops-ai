"""Per-task tool filtering for agents with large tool sets.

Local models pick the wrong tool more often as the number of tools they see
grows (2026 studies; and this stack's own history: the 68-tool OpenWebUI
connection, the ops agent's ~41 tools). A ToolFilteringAgent embeds each task,
ranks its tools by similarity, and shows the model only a subset for that run.

Modes (SMOLAGENTS_OPS_TOOL_FILTER):
  off    - every tool, every run (default; current behaviour)
  domain - the top-k tools pull in their WHOLE domain. Keeps every tool of a
           relevant domain visible (including risky ones, so "should decline"
           behaviour is still exercised), and drops unrelated domains.
  topk   - only the top-k tools. Smallest prompt, but can hide a tool the task
           should have declined to use, which changes what a decline means.

Always visible: tools from the "always" set (shared helpers like
current_datetime, tools_help, the approvals domain) and final_answer.
Any embedding failure falls back to every tool: filtering may only ever help,
never strand a task without its tools.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable

import httpx
from smolagents import ToolCallingAgent

from . import config

QUERY_PREFIX = ("Instruct: Given a business-operations request, retrieve the tools "
                "needed to carry it out\nQuery: ")

EmbedFn = Callable[[list[str]], list[list[float]]]


def _ollama_native_base() -> str:
    base = config.OLLAMA_API_BASE.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def ollama_embed(texts: list[str]) -> list[list[float]]:
    """Embeddings through Ollama's native /api/embed (same host the agents'
    models use, so it works on the host and in the container).

    The embedder is pinned to CPU (num_gpu 0) so it never takes VRAM from
    the lead model (~1 s to load, ~30 ms per query). It still needs ~1.2 GB
    of host RAM: with the partly offloaded 35b lead under the 24 GB WSL cap,
    the 2026-11-25 eval saw the 35b runner OOM-killed and reloaded 4-5 times
    per filtered run (0-1 without the filter). Fine with leads that fit in
    VRAM (9b); for the 35b, free host RAM before turning the filter on."""
    resp = httpx.post(f"{_ollama_native_base()}/api/embed",
                      json={"model": config.EMBED_MODEL_ID, "input": texts,
                            "keep_alive": "30m", "options": {"num_gpu": 0}},
                      headers={"Authorization": f"Bearer {config.OLLAMA_API_KEY}"},
                      timeout=120)
    resp.raise_for_status()
    return resp.json()["embeddings"]


def _cos(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb) if na and nb else 0.0


class ToolSelector:
    """Ranks a fixed tool set against task text. Tool embeddings are computed
    once, lazily, on first use; one query embedding per selection."""

    def __init__(self, domain_tools: dict[str, list], always: Iterable = (),
                 mode: str = "domain", k: int = 8, embed: EmbedFn = ollama_embed):
        if mode not in ("domain", "topk"):
            raise ValueError(f"unknown tool-filter mode {mode!r}")
        self.mode, self.k, self.embed = mode, k, embed
        self.always = {t.name: t for t in always}
        self.domain_of: dict[str, str] = {}
        self.candidates: dict[str, object] = {}
        for domain, tools in domain_tools.items():
            for t in tools:
                if t.name in self.always or t.name in self.candidates:
                    continue  # shared tools (tools_help…) appear in every domain
                self.candidates[t.name] = t
                self.domain_of[t.name] = domain
        self._vectors: dict[str, list[float]] | None = None

    def _tool_vectors(self) -> dict[str, list[float]]:
        if self._vectors is None:
            names = list(self.candidates)
            docs = [f"{n}: {self.candidates[n].description}" for n in names]
            self._vectors = dict(zip(names, self.embed(docs), strict=True))
        return self._vectors

    def select(self, task: str) -> list:
        """Tools to expose for this task (always-set included). Falls back to
        every tool if embedding fails for any reason."""
        everything = [*self.candidates.values(), *self.always.values()]
        try:
            vectors = self._tool_vectors()
            (query,) = self.embed([QUERY_PREFIX + task])
        except Exception as exc:  # noqa: BLE001 — never strand a task
            print(f"[tool_filter] embedding failed ({type(exc).__name__}); exposing all tools.")
            return everything
        ranked = sorted(self.candidates, key=lambda n: -_cos(query, vectors[n]))
        top = ranked[: self.k]
        if self.mode == "topk":
            chosen = top
        else:
            domains = {self.domain_of[n] for n in top}
            chosen = [n for n in ranked if self.domain_of[n] in domains]
        return [*(self.candidates[n] for n in chosen), *self.always.values()]


class ToolFilteringAgent(ToolCallingAgent):
    """ToolCallingAgent that narrows its visible tools at the start of each
    fresh run. smolagents rebuilds the system prompt and the tool schema list
    from self.tools on every run/step, so swapping the dict is enough.
    Continued conversations (reset=False) keep the previous run's tools."""

    def __init__(self, *args, selector: ToolSelector | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.selector = selector
        self._all_tools = dict(self.tools)
        self._filter_query: str | None = None
        self.last_selected_tools: list[str] = list(self.tools)

    def __call__(self, task: str, **kwargs):
        # As a managed agent the task arrives wrapped in a prompt template;
        # rank tools against the manager's actual request, not the wrapper.
        self._filter_query = task
        try:
            return super().__call__(task, **kwargs)
        finally:
            self._filter_query = None

    def run(self, task: str, *args, reset: bool = True, **kwargs):
        if self.selector is not None and reset:
            chosen = self.selector.select(self._filter_query or task)
            tools = {t.name: t for t in chosen}
            tools["final_answer"] = self._all_tools["final_answer"]
            self.tools = tools
            self.last_selected_tools = sorted(tools)
            print(f"[tool_filter] {self.name}: {len(tools)}/{len(self._all_tools)} tools "
                  f"({self.selector.mode}, k={self.selector.k})", flush=True)
        return super().run(task, *args, reset=reset, **kwargs)
