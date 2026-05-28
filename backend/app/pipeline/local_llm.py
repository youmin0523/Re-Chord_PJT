"""Tiny Ollama-backed local LLM helper.

We call Ollama's HTTP API at ``http://localhost:11434`` when available.
Used for two narrow tasks:

  * Chord re-ranking (``chord_llm.py``): "given key + 8 chords, is the
    7th chord plausible given common jazz idioms? If not, suggest the
    most likely substitute from {…top-K…}."
  * Section label refinement (``sections_advanced.py``): "given chord
    progression + lyric snippet, is this verse/chorus/bridge?"

We use small instruct models (Llama 3.2 1B / Qwen 2.5 1.5B) so latency
is < 1 s on CPU. If Ollama isn't running or the model isn't pulled,
every helper returns ``None`` and the caller falls back to pure-rule
logic.

Configure with env var ``OLLAMA_MODEL`` (default ``llama3.2:1b``) and
``OLLAMA_HOST`` (default ``http://localhost:11434``).
"""

from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_MODEL = "llama3.2:1b"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 10.0


def is_available() -> bool:
    """Quick probe: is Ollama responding on the configured host?"""
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    try:
        import urllib.request
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


# Process-local LRU cache for re-rank prompts. Re-running the same job
# re-generates the same prompts (e.g. key + 8 chord neighbourhood);
# caching turns a ~1s Ollama round-trip into a hashmap lookup. Bounded
# size so long-running servers don't grow unbounded.
import functools as _functools


@_functools.lru_cache(maxsize=1024)
def _cached_generate_json(prompt: str, schema_hint: str,
                          temperature: float) -> str | None:
    """LRU-cached worker. Returns the raw JSON string (callers parse).
    We cache strings (not dicts) so the lru_cache return value is hashable."""
    result = _generate_json_uncached(prompt, schema_hint=schema_hint,
                                     temperature=temperature)
    return json.dumps(result) if result is not None else None


def generate_json(prompt: str, *, schema_hint: str = "",
                  temperature: float = 0.1) -> dict[str, Any] | None:
    """Cached wrapper. Same (prompt, schema, temperature) → cached verdict.

    Set env ``RECHORD_LLM_NO_CACHE=1`` to bypass — useful when measuring
    cold-start latency or debugging non-determinism."""
    if os.environ.get("RECHORD_LLM_NO_CACHE"):
        return _generate_json_uncached(prompt, schema_hint=schema_hint,
                                       temperature=temperature)
    cached = _cached_generate_json(prompt, schema_hint, temperature)
    if cached is None:
        return None
    try:
        return json.loads(cached)
    except Exception:
        return None


def _generate_json_uncached(prompt: str, *, schema_hint: str = "",
                            temperature: float = 0.1) -> dict[str, Any] | None:
    """Underlying Ollama call. Same docstring as the cached wrapper above."""
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    full_prompt = prompt.strip()
    if schema_hint:
        full_prompt += "\n\n" + schema_hint.strip()
    body = json.dumps({
        "model": model,
        "prompt": full_prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": float(temperature)},
    }).encode("utf-8")
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    text = payload.get("response", "")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some models leak extra prose around the JSON. Try to recover.
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except Exception:
            return None
