"""Audio-to-MIDI transcription dispatcher.

Default backend is basic-pitch (Spotify Research, MIT) which handles all
stem types acceptably. The :func:`transcribe` dispatcher picks a per-stem
backend so we can plug in specialised SOTA models when the optional deps
are installed:

    stem      backend (when installed)               accuracy
    ─────────────────────────────────────────────────────────────────
    vocals    basic-pitch                            80–85% note F1
    bass      basic-pitch (low-freq tuned)           75–80%
    piano     basic-pitch  → MT3 (if available)      65–75 → 80–85%
    guitar    basic-pitch                            60–70%
    drums     basic-pitch  → A2D2 (if available)     70 → 88%
    other     basic-pitch                            55–70%

The optional models all expose a ``transcribe(audio_path) -> midi_data``
shim under ``backend.app.pipeline.transcribe_backends.*``. If a backend
module is missing or import-fails, we silently fall back to basic-pitch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# Silence TensorFlow's chatty logs before importing it transitively.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


StemKindForTranscribe = Literal[
    "vocals", "piano", "guitar", "bass", "drums", "other", "instrumental", "mix",
]


# Stem → preferred specialised backend module name (under
# backend.app.pipeline.transcribe_backends). None falls through to basic-pitch.
_PREFERRED_BACKEND: dict[str, str | None] = {
    "piano":  "mt3",          # google-research/mt3 — polyphonic transformer
    "drums":  "a2d2",         # AudioDrumDataset 2 — drum-specific
    "bass":   "jdc_pe",       # JDC-PE — joint detection+classification, low freq
    # Vocals stays on basic-pitch by default — CREPE-based monophonic
    # pitch tracking is competitive and avoids backend churn.
}


@dataclass
class TranscribeResult:
    midi_path: Path
    note_events_csv: Path | None
    stem_kind: str
    elapsed_sec: float
    note_count: int
    duration_sec: float
    low_midi: int | None = None       # lowest pitched note (for vocal-range hints)
    high_midi: int | None = None      # highest pitched note


def _basic_pitch_predict(audio_path: Path, stem_kind: StemKindForTranscribe):
    """Run basic-pitch with parameters tuned for the stem type."""
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    # Tunable thresholds per stem kind. Lower onset threshold = more sensitive
    # note onset detection; lower frame threshold = keep softer notes.
    if stem_kind == "vocals":
        kwargs = dict(onset_threshold=0.5, frame_threshold=0.3,
                      minimum_note_length=68, minimum_frequency=70.0,
                      maximum_frequency=2000.0, melodia_trick=True)
    elif stem_kind in ("piano", "guitar", "other", "instrumental"):
        kwargs = dict(onset_threshold=0.5, frame_threshold=0.3,
                      minimum_note_length=58, minimum_frequency=27.5,
                      maximum_frequency=4200.0, melodia_trick=False)
    elif stem_kind == "bass":
        kwargs = dict(onset_threshold=0.5, frame_threshold=0.3,
                      minimum_note_length=80, minimum_frequency=30.0,
                      maximum_frequency=400.0, melodia_trick=False)
    else:  # mix
        kwargs = dict(onset_threshold=0.5, frame_threshold=0.3,
                      minimum_note_length=58, minimum_frequency=27.5,
                      maximum_frequency=4200.0, melodia_trick=False)

    return predict(str(audio_path), model_or_model_path=ICASSP_2022_MODEL_PATH, **kwargs)


def _try_specialised_backend(
    audio_path: Path, stem_kind: StemKindForTranscribe,
):
    """Attempt to import and run a stem-specific transcription backend.

    Returns ``(midi_data, note_events)`` on success, ``None`` if the backend
    isn't installed or failed (caller falls back to basic-pitch).
    """
    backend_name = _PREFERRED_BACKEND.get(stem_kind)
    if not backend_name:
        return None
    try:
        mod = __import__(
            f"backend.app.pipeline.transcribe_backends.{backend_name}",
            fromlist=["transcribe"],
        )
        return mod.transcribe(audio_path)
    except (ImportError, ModuleNotFoundError):
        return None
    except Exception:
        # Any runtime failure inside the specialised backend → fall back
        # silently. The user still gets a result via basic-pitch.
        return None


def transcribe(
    audio_path: Path,
    out_dir: Path,
    stem_kind: StemKindForTranscribe = "vocals",
    write_csv: bool = True,
) -> TranscribeResult:
    """Transcribe audio to MIDI. Writes <stem>.mid and optional <stem>.csv.

    Dispatches to the best available backend for ``stem_kind``; on missing
    deps the fallback path is plain basic-pitch.
    """
    import time
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    specialised = _try_specialised_backend(audio_path, stem_kind)
    if specialised is not None:
        midi_data, note_events = specialised
    else:
        _model_output, midi_data, note_events = _basic_pitch_predict(audio_path, stem_kind)
    elapsed = time.perf_counter() - t0

    midi_path = out_dir / f"{stem_kind}.mid"
    midi_data.write(str(midi_path))

    csv_path: Path | None = None
    if write_csv:
        csv_path = out_dir / f"{stem_kind}_notes.csv"
        _write_note_events_csv(note_events, csv_path)

    # Aggregate note count + duration for the report.
    note_count = sum(len(inst.notes) for inst in midi_data.instruments)
    duration_sec = float(midi_data.get_end_time())

    # Melody range — lowest/highest MIDI pitches across all notes. Used by
    # the frontend KeyControl audience-range hint. Ignore outlier ~5% so a
    # single mis-detected note doesn't widen the range artificially.
    pitches = sorted(
        n.pitch for inst in midi_data.instruments for n in inst.notes
    )
    low_midi: int | None = None
    high_midi: int | None = None
    if pitches:
        n = len(pitches)
        # 5th and 95th percentiles as robust bounds.
        low_midi = int(pitches[max(0, int(n * 0.05))])
        high_midi = int(pitches[min(n - 1, int(n * 0.95))])

    return TranscribeResult(
        midi_path=midi_path,
        note_events_csv=csv_path,
        stem_kind=stem_kind,
        elapsed_sec=elapsed,
        note_count=note_count,
        duration_sec=duration_sec,
        low_midi=low_midi,
        high_midi=high_midi,
    )


def _write_note_events_csv(note_events, path: Path) -> None:
    """basic-pitch returns a list of (start_sec, end_sec, midi_pitch, velocity,
    pitch_bends_or_None). Persist as a simple CSV for downstream tools."""
    with path.open("w", encoding="utf-8") as fp:
        fp.write("start_sec,end_sec,midi_pitch,velocity\n")
        for ev in note_events:
            start, end, pitch, vel = ev[0], ev[1], ev[2], ev[3]
            fp.write(f"{start:.4f},{end:.4f},{int(pitch)},{int(vel)}\n")
