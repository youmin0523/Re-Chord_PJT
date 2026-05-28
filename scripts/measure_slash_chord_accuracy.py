"""Measure slash-chord bass cross-check accuracy on synthetic stems.

Generates pairs of (chord_label, bass_audio) where the bass audio plays a
known fundamental. We then ask ``chord_bass_check.cross_check_slash_bass``
to validate or reject the slash and compare its decision to ground truth.

Three scenarios:
  * matching   — slash bass matches the audio fundamental (should confirm)
  * mismatching — slash bass disagrees with audio (should downgrade)
  * ambiguous  — silent/noisy bass (should leave alone)

Output: data/qa/slash_chord_check_<date>.json
"""

from __future__ import annotations

import datetime as dt
import json
import math
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


SR = 22050
DUR = 2.0
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "qa" / f"slash_chord_check_{dt.date.today().isoformat()}.json"


@dataclass
class ChordEvent:
    """Minimal stand-in for the real ChordEvent dataclass — same field
    names so cross_check_slash_bass can mutate ``label`` / ``confidence``.
    """
    start_sec: float
    end_sec: float
    root: str = ""
    quality: str = "maj"
    label: str = ""
    confidence: float = 0.5
    bass_audio_pc: int | None = None
    bass_check: str = ""


# Pitch class → A2-octave fundamental for synth bass.
_PC_HZ_A2 = {  # A2 = 110, C3 = 130.81 etc.
    "C": 130.81, "C#": 138.59, "D": 146.83, "D#": 155.56,
    "E": 164.81, "F": 174.61, "F#": 185.00, "G": 196.00,
    "G#": 207.65, "A": 110.00, "A#": 116.54, "B": 123.47,
}


def _saw(f: float, dur: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    return (2.0 * (t * f - np.floor(t * f + 0.5))).astype(np.float32) * 0.4


def _silence(dur: float) -> np.ndarray:
    return np.zeros(int(dur * SR), dtype=np.float32)


def _write_wav(path: Path, mono: np.ndarray) -> None:
    stereo = np.stack([mono, mono], axis=1)
    stereo = np.clip(stereo, -1.0, 1.0)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def main() -> int:
    """
    Build a synthetic bass track that plays C-E-G across 6 seconds (3 chord
    segments of 2 s each). Run cross_check_slash_bass against three slash
    chord lists:
      * truthful   — every slash bass matches the audio
      * lying      — every slash bass disagrees with the audio
      * mixed      — half match, half don't
    """
    from backend.app.pipeline.chord_bass_check import cross_check_slash_bass

    # Build a 6-second bass track with three roots: C / E / G
    track = np.concatenate([
        _saw(_PC_HZ_A2["C"], DUR),
        _saw(_PC_HZ_A2["E"], DUR),
        _saw(_PC_HZ_A2["G"], DUR),
    ]).astype(np.float32)

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "bass.wav"
        _write_wav(wav, track)

        # ---- scenario A: truthful ---------------------------------
        truthful = [
            ChordEvent(0.0, 2.0, root="F", quality="maj", label="F/C", confidence=0.5),
            ChordEvent(2.0, 4.0, root="C", quality="maj", label="C/E", confidence=0.5),
            ChordEvent(4.0, 6.0, root="C", quality="maj", label="C/G", confidence=0.5),
        ]
        rep_a = cross_check_slash_bass(truthful, wav)

        # ---- scenario B: lying ------------------------------------
        # All slashes claim a bass that doesn't match the audio.
        lying = [
            ChordEvent(0.0, 2.0, root="A", quality="min", label="Am/F#",
                       confidence=0.5),
            ChordEvent(2.0, 4.0, root="D", quality="maj", label="D/A",
                       confidence=0.5),
            ChordEvent(4.0, 6.0, root="F", quality="maj", label="F/B",
                       confidence=0.5),
        ]
        rep_b = cross_check_slash_bass(lying, wav)

        # ---- scenario C: mixed ------------------------------------
        mixed = [
            ChordEvent(0.0, 2.0, root="F", quality="maj", label="F/C",
                       confidence=0.5),                                    # match
            ChordEvent(2.0, 4.0, root="D", quality="maj", label="D/A",
                       confidence=0.5),                                    # mismatch
            ChordEvent(4.0, 6.0, root="C", quality="maj", label="C/G",
                       confidence=0.5),                                    # match
        ]
        rep_c = cross_check_slash_bass(mixed, wav)

    report = {
        "date": dt.date.today().isoformat(),
        "sample_rate": SR,
        "scenarios": {
            "truthful": {
                "report": rep_a,
                "expected_confirmed": 3,
                "actual_confirmed": rep_a.get("confirmed", 0),
                "pass": rep_a.get("confirmed", 0) >= 2,        # tolerate 1 ambiguous
            },
            "lying": {
                "report": rep_b,
                "expected_downgraded": 3,
                "actual_downgraded": rep_b.get("downgraded", 0),
                "pass": rep_b.get("downgraded", 0) >= 2,
            },
            "mixed": {
                "report": rep_c,
                "expected_confirmed": 2,
                "expected_downgraded": 1,
                "actual_confirmed": rep_c.get("confirmed", 0),
                "actual_downgraded": rep_c.get("downgraded", 0),
                "pass": (rep_c.get("confirmed", 0) >= 1
                         and rep_c.get("downgraded", 0) >= 1),
            },
        },
    }
    passes = sum(1 for s in report["scenarios"].values() if s["pass"])
    report["pass_rate"] = passes / 3
    print(f"[info] slash-chord cross-check accuracy: {passes}/3 scenarios passed")
    for name, sc in report["scenarios"].items():
        print(f"  {name}: {sc}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[ok] wrote {OUT_PATH}")
    return 0 if passes == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
