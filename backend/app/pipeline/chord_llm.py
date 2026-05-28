"""Optional local-LLM chord re-ranker.

Calls Ollama (default ``llama3.2:1b``) to ask "given this key and this
chord progression, is each chord plausible? If not, suggest a
substitute". Silently no-ops when Ollama isn't available so the platform
keeps working without the dependency.

Output: a new ChordEvent list with low-confidence + LLM-substituted
chords replaced, with confidence equal to the original detector
confidence (we don't fabricate confidence from the LLM).
"""

from __future__ import annotations

from dataclasses import replace

from .chords import ChordEvent
from .local_llm import generate_json, is_available


PROMPT_TEMPLATE = """\
You are a music theory assistant. Given the key and a chord progression \
extracted from a recording, decide whether each chord is plausible. \
Return a JSON object with a single key "fixes" containing a list of \
{{index: int, suggested: string}} for chords that should be replaced. \
Index is 0-based. Suggested chord must be in the format like "C", "Am", \
"G7", "Dm7", "F/A". Only flag chords that don't make musical sense in \
the key; leave plausible chords alone (do not include them in fixes).

Key: {key_name}
Chords (in order):
{chord_list}

Return only the JSON object."""


SCHEMA_HINT = (
    'Schema: {"fixes":[{"index":0,"suggested":"Am"},'
    '{"index":3,"suggested":"G7"}]}. '
    "If no fixes are needed, return {\"fixes\": []}."
)


def is_enabled() -> bool:
    return is_available()


def rerank(
    events: list[ChordEvent],
    key_name: str,
    *,
    conf_floor: float = 0.65,
    max_chords: int = 32,
) -> list[ChordEvent]:
    """Run the LLM re-ranker. Returns the original list if Ollama is offline.

    Only the first ``max_chords`` low-confidence events are sent to the LLM
    (keeps prompt + latency bounded). Higher-confidence chords are kept
    as-is and surface in the prompt as context.
    """
    if not events or not key_name or not is_available():
        return events

    targets = [
        (i, ev) for i, ev in enumerate(events[:max_chords])
        if ev.confidence < conf_floor and ev.quality != "N"
    ]
    if not targets:
        return events

    chord_lines = "\n".join(
        f"{i}: {ev.label}  (conf {ev.confidence:.2f})"
        for i, ev in enumerate(events[:max_chords])
    )
    prompt = PROMPT_TEMPLATE.format(key_name=key_name, chord_list=chord_lines)
    result = generate_json(prompt, schema_hint=SCHEMA_HINT)
    if not result or not isinstance(result, dict):
        return events
    fixes = result.get("fixes") or []
    if not isinstance(fixes, list):
        return events

    out = list(events)
    for fix in fixes:
        if not isinstance(fix, dict):
            continue
        idx = fix.get("index")
        sug = fix.get("suggested")
        if not isinstance(idx, int) or not isinstance(sug, str):
            continue
        if idx < 0 or idx >= len(out):
            continue
        ev = out[idx]
        if ev.confidence >= conf_floor:
            continue
        parsed = _parse_label(sug.strip())
        if parsed is None:
            continue
        new_root, new_quality, new_label = parsed
        out[idx] = replace(
            ev, root=new_root, quality=new_quality, label=new_label,
        )
    return out


def _parse_label(label: str) -> tuple[str, str, str] | None:
    """Loose chord-label parser. Returns (root, normalized_quality, pretty)."""
    if not label:
        return None
    # Strip whitespace.
    label = label.strip()
    # Extract root (one of A-G plus optional # or b).
    if len(label) < 1:
        return None
    root = label[0].upper()
    if root not in "ABCDEFG":
        return None
    rest = label[1:]
    if rest.startswith(("#", "b")):
        root += rest[0]
        rest = rest[1:]
    # Normalise quality.
    rest_lower = rest.lower()
    if rest_lower.startswith("m") and not rest_lower.startswith("maj"):
        quality = "min"
    elif rest_lower.startswith("dim"):
        quality = "dim"
    elif rest_lower.startswith("aug"):
        quality = "aug"
    else:
        quality = "maj"
    return root, quality, label
