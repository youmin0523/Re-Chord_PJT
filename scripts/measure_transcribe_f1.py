"""Measure note-level transcription F1 on synthesized melodies.

Ground truth is the MIDI we synthesize FROM, so we know every note's
onset + pitch. We render a harmonically-rich monophonic line, run the
real transcribe() backend (basic-pitch), and compute note F1: a
predicted note matches a GT note when onset is within ±100 ms AND pitch
is exact (±0 semitone after octave-agnostic check off).

Pure-synth transcription is an upper-ish bound vs real instruments, but
it's the first objective number we have for our transcribe stage.

Output: data/qa/transcribe_f1_<date>.json
"""

from __future__ import annotations

import datetime as dt
import json
import math
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SR = 22050


def _render_note(midi_pitch: int, dur: float, sr: int = SR) -> np.ndarray:
    """Harmonically-rich tone (fundamental + 3 harmonics + decay) so
    basic-pitch has overtone structure to lock onto."""
    f = 440.0 * 2 ** ((midi_pitch - 69) / 12.0)
    n = int(dur * sr)
    t = np.arange(n) / sr
    sig = (np.sin(2 * math.pi * f * t)
           + 0.5 * np.sin(2 * math.pi * 2 * f * t)
           + 0.25 * np.sin(2 * math.pi * 3 * f * t)).astype(np.float32)
    env = np.minimum(1.0, np.exp(-t / (dur * 0.8))).astype(np.float32)
    # short attack
    a = int(0.01 * sr)
    if a > 0:
        env[:a] *= np.linspace(0, 1, a)
    return sig * env * 0.3


def _build_melody():
    """A C-major melody with stepwise + leap motion. Returns (audio,
    gt_notes) where gt_notes = [(onset_sec, midi_pitch), ...]."""
    # C4..C5 scale up then a few leaps.
    pitches = [60, 62, 64, 65, 67, 69, 71, 72, 67, 64, 60, 67, 72]
    note_dur = 0.5
    gap = 0.0
    gt = []
    chunks = []
    cursor = 0.0
    for p in pitches:
        gt.append((cursor, p))
        chunks.append(_render_note(p, note_dur))
        cursor += note_dur + gap
    audio = np.concatenate(chunks)
    return audio.astype(np.float32), gt


def _write_wav(path: Path, mono: np.ndarray):
    stereo = np.stack([mono, mono], axis=1)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype(np.int16).tobytes())


def _note_f1(gt, pred, onset_tol=0.10):
    """gt/pred: list of (onset, pitch). Match within onset_tol and exact pitch."""
    if not gt:
        return (1.0, 1.0, 1.0) if not pred else (0.0, 1.0, 0.0)
    if not pred:
        return (1.0, 0.0, 0.0)
    used = [False] * len(pred)
    tp = 0
    for (g_on, g_p) in gt:
        best = None
        for j, (p_on, p_p) in enumerate(pred):
            if used[j] or p_p != g_p:
                continue
            if abs(p_on - g_on) <= onset_tol:
                if best is None or abs(p_on - g_on) < abs(pred[best][0] - g_on):
                    best = j
        if best is not None:
            used[best] = True
            tp += 1
    fp = sum(1 for u in used if not u)
    fn = len(gt) - tp
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def main() -> int:
    audio, gt = _build_melody()
    print(f"[info] synthesized melody: {len(gt)} notes")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "melody.wav"
        _write_wav(wav, audio)
        from backend.app.pipeline.transcribe import transcribe
        res = transcribe(wav, Path(tmp), stem_kind="vocals", write_csv=True)
        # Parse predicted notes from the CSV (start_sec, pitch).
        pred = []
        if res.note_events_csv and Path(res.note_events_csv).exists():
            for ln in Path(res.note_events_csv).read_text().splitlines()[1:]:
                parts = ln.split(",")
                if len(parts) >= 3:
                    pred.append((float(parts[0]), int(parts[2])))

    # Exact-pitch F1.
    prec, rec, f1 = _note_f1(gt, pred)
    # Pitch-class F1 (octave-agnostic) — basic-pitch sometimes octave-slips.
    gt_pc = [(o, p % 12) for o, p in gt]
    pred_pc = [(o, p % 12) for o, p in pred]
    pc_prec, pc_rec, pc_f1 = _note_f1(gt_pc, pred_pc)

    report = {
        "date": dt.date.today().isoformat(),
        "backend": "basic-pitch (synthetic harmonic melody)",
        "gt_notes": len(gt),
        "pred_notes": len(pred),
        "exact_pitch": {"precision": round(prec, 3), "recall": round(rec, 3),
                        "f1": round(f1, 3)},
        "pitch_class": {"precision": round(pc_prec, 3), "recall": round(pc_rec, 3),
                        "f1": round(pc_f1, 3)},
        "note": "Synthetic upper bound; real instruments score lower.",
    }
    out = ROOT / "data" / "qa" / f"transcribe_f1_{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  exact-pitch F1 = {f1:.3f} (P={prec:.3f} R={rec:.3f})")
    print(f"  pitch-class F1 = {pc_f1:.3f} (P={pc_prec:.3f} R={pc_rec:.3f})")
    print(f"  gt={len(gt)} pred={len(pred)}")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
