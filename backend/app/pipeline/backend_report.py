"""Surface the actual backend used by each pipeline stage.

Why this exists: every stage of our pipeline has a primary (SOTA) backend
and one or more fallbacks. When the SOTA backend is missing the user
silently gets a degraded result and there's no way to tell from the
output whether the fancy 170-class chord vocabulary, drum-specialist
transcription, or madmom CNN key detector actually ran.

For commercial release we need the result to be *self-describing*: which
backend produced each artifact, what level of accuracy it implies, and
whether a better backend is available locally if the user installs one
more package.

Usage in workers/orchestrator.py:

    from backend.app.pipeline.backend_report import (
        record_backend, build_dependency_warnings,
    )
    record_backend(job, "chord_detect", "crema", level="sota",
                   note="170-class with 7th/sus/slash support")
    ...
    job.meta["backend_warnings"] = build_dependency_warnings(job)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import util as _import_util


@dataclass
class BackendChoice:
    stage: str                   # e.g. "chord_detect", "transcribe_piano"
    backend: str                 # what actually ran, e.g. "crema", "basic_pitch"
    level: str = "primary"       # "sota" | "primary" | "fallback" | "heuristic"
    note: str = ""               # human-readable accuracy expectation


@dataclass
class DependencyHint:
    stage: str
    missing: str                 # the package name
    install_cmd: str             # "uv pip install crema"
    impact: str                  # what the user is missing


# Single source of truth for the SOTA-vs-fallback matrix. Used by the
# warning builder to tell the user *which* installs would actually help.
_SOTA_DEPS: dict[str, list[DependencyHint]] = {
    "chord_detect": [
        DependencyHint(
            stage="chord_detect", missing="crema",
            install_cmd="uv pip install crema",
            impact="7th/sus/dim/slash chord recognition (170 classes vs 24 triads)",
        ),
    ],
    "key_detect": [
        DependencyHint(
            stage="key_detect", missing="madmom",
            install_cmd="uv pip install madmom",
            impact="CNN key detector ~85-92% vs librosa Krumhansl ~70-80%",
        ),
    ],
    "beat_grid": [
        DependencyHint(
            stage="beat_grid", missing="madmom",
            install_cmd="uv pip install madmom",
            impact="DBN downbeat tracking on compound meters",
        ),
    ],
    "transcribe_piano": [
        DependencyHint(
            stage="transcribe_piano", missing="piano_transcription_inference",
            install_cmd="uv pip install piano_transcription_inference",
            impact="polyphonic piano F1 80-85% vs basic-pitch 65-75%",
        ),
    ],
    "transcribe_drums": [
        DependencyHint(
            stage="transcribe_drums", missing="omnizart",
            install_cmd="uv pip install omnizart (needs Python ≤ 3.10)",
            impact="drum F1 88% vs heuristic ~70-75%",
        ),
    ],
    "transcribe_bass": [
        DependencyHint(
            stage="transcribe_bass", missing="crepe",
            install_cmd="uv pip install crepe --no-build-isolation",
            impact="bass note F1 90-92% vs basic-pitch 75-80%",
        ),
    ],
    "chord_llm": [
        DependencyHint(
            stage="chord_llm", missing="ollama",
            install_cmd="bin/ollama/ollama.exe serve && ollama pull llama3.2:1b",
            impact="LLM theory re-rank on low-confidence chord predictions",
        ),
    ],
    "lyrics": [
        DependencyHint(
            stage="lyrics", missing="faster_whisper",
            install_cmd="uv pip install faster-whisper",
            impact="lyric transcription with word-level timestamps",
        ),
    ],
    "aux_classifier": [
        DependencyHint(
            stage="aux_classifier", missing="laion_clap",
            install_cmd='uv pip install -e ".[aux_classifier]"',
            impact="auto-detection of organ/pad/strings/synth AUX patches",
        ),
    ],
}


def _is_installed(module_name: str) -> bool:
    try:
        return _import_util.find_spec(module_name) is not None
    except Exception:
        return False


def record_backend(job, stage: str, backend: str, *, level: str = "primary",
                   note: str = "") -> None:
    """Append a BackendChoice to ``job.meta['backends_used']``.

    Safe to call before or after the actual stage runs; we just want one
    record per (stage, backend) per job.
    """
    if job is None:
        return
    meta = getattr(job, "meta", None)
    if meta is None:
        return
    used = meta.setdefault("backends_used", [])
    entry = {"stage": stage, "backend": backend, "level": level, "note": note}
    # De-duplicate by stage — last-write-wins (a later refinement might
    # supersede the initial template-match call, for example).
    used[:] = [u for u in used if u.get("stage") != stage]
    used.append(entry)


def record_fallback(job, stage: str, missing: str, reason: str = "") -> None:
    """Note that a stage *would have* used ``missing`` but couldn't.

    Goes into ``job.meta['backend_fallbacks']`` so the UI can render a
    'install for better accuracy' hint without us having to grep logs.
    """
    if job is None:
        return
    meta = getattr(job, "meta", None)
    if meta is None:
        return
    falls = meta.setdefault("backend_fallbacks", [])
    falls.append({"stage": stage, "missing": missing, "reason": reason})


def build_dependency_warnings(job) -> list[dict]:
    """Walk the SOTA dependency matrix and return install hints for whatever
    is still missing on the current machine.

    Returns an empty list when everything is installed; this is the value
    the orchestrator stashes in ``job.meta['backend_warnings']`` so the UI
    can render an unobtrusive 'tip' card.
    """
    out: list[dict] = []
    for stage, deps in _SOTA_DEPS.items():
        for d in deps:
            mod_name = d.missing.replace("-", "_")
            if mod_name == "ollama":
                # Ollama is a binary, not a Python module — we can't probe it
                # cheaply from here; the orchestrator records its own
                # fallback if /chord_llm fails to reach the daemon.
                continue
            if not _is_installed(mod_name):
                out.append({
                    "stage": stage,
                    "missing": d.missing,
                    "install": d.install_cmd,
                    "accuracy_impact": d.impact,
                })
    return out


def freeze_backend_summary(job) -> dict:
    """Take everything we recorded and stash a compact summary on the job.

    Call once at the end of orchestrator.run_job — the frontend reads this
    via /jobs/:id to know what to brag about or apologize for.
    """
    if job is None:
        return {}
    meta = getattr(job, "meta", None) or {}
    summary = {
        "backends_used": list(meta.get("backends_used", [])),
        "fallbacks": list(meta.get("backend_fallbacks", [])),
        "install_hints": build_dependency_warnings(job),
    }
    meta["backend_summary"] = summary
    return summary
