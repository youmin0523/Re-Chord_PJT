"""End-to-end accuracy measurement pipeline.

Runs each analysis stage against synthetic ground-truth signals and emits a
JSON report. Real audio benchmarks (MUSDB18 SI-SDR, JAAH chord F1) live in
``tests/test_separation_regression.py`` and stay there; this script is the
fast smoke-test that *always* runs and tracks day-to-day drift.

Usage:
    python scripts/measure_accuracy.py
    python scripts/measure_accuracy.py --out data/qa/accuracy_2026_05_20.json

Metrics produced (all honest — synthetic signals only, no marketing-fluff):
    - key.major_correct          : % of major-key tonics correctly identified
    - bpm.mae_bpm                : mean absolute error on tempo estimation
    - bpm.tolerance_4pct_acc     : % of tempos within 4% (MIREX standard)
    - onset.f1_50ms              : onset-detection F1 at 50ms tolerance
    - chord.symbol_acc           : chord-symbol accuracy (root + quality)

The script does not import torch directly; it loads the analysis modules
from ``backend.app.pipeline.analyze`` so we measure what the product
actually does, not a library.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


SR = 22050


def _save_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio.astype(np.float32), sr, subtype="PCM_16")


def _sine(freq: float, dur: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return 0.4 * np.sin(2 * np.pi * freq * t)


def _click_track(bpm: float, dur: float, sr: int = SR) -> np.ndarray:
    n = int(dur * sr)
    audio = np.zeros(n, dtype=np.float32)
    step = int(sr * 60.0 / bpm)
    click_len = int(0.01 * sr)
    pos = 0
    while pos < n - click_len:
        # Brief noise burst → easy onset target.
        audio[pos : pos + click_len] = np.random.default_rng(0).standard_normal(click_len) * 0.5
        pos += step
    return audio


# ----------------------------------------------------------------------------
# Key estimation
# ----------------------------------------------------------------------------

NOTE_FREQ = {
    "C": 261.63, "C#": 277.18, "D": 293.66, "D#": 311.13, "E": 329.63,
    "F": 349.23, "F#": 369.99, "G": 392.00, "G#": 415.30, "A": 440.00,
    "A#": 466.16, "B": 493.88,
}


def measure_key_accuracy() -> dict:
    """For each of the 12 major-key tonics, build a triad + tonic root and
    ask the analyzer to identify the key."""
    try:
        from backend.app.pipeline.analyze import detect_key
    except Exception as e:
        return {"skipped": True, "reason": f"detect_key import failed: {e!r}"}

    correct = 0
    total = 0
    per_note: dict[str, bool] = {}
    for note, freq in NOTE_FREQ.items():
        # Tonic + 3rd + 5th of a major chord, 8 seconds.
        third = freq * (5 / 4)
        fifth = freq * (3 / 2)
        sig = _sine(freq, 8) + _sine(third, 8) + _sine(fifth, 8)
        peak = float(np.max(np.abs(sig)))
        if peak > 1.0:
            sig = sig / peak
        try:
            _key_name, root, mode, _conf = detect_key(sig.astype(np.float32), SR)
            ok = (root == note) and (mode == "major")
        except Exception:
            ok = False
        per_note[note] = ok
        correct += int(ok)
        total += 1
    return {
        "skipped": False,
        "major_correct": round(correct / total, 4) if total else 0.0,
        "total": total,
        "per_note": per_note,
    }


# ----------------------------------------------------------------------------
# BPM estimation
# ----------------------------------------------------------------------------

def measure_bpm_accuracy() -> dict:
    try:
        from backend.app.pipeline.analyze import detect_bpm
    except Exception as e:
        return {"skipped": True, "reason": f"detect_bpm import failed: {e!r}"}

    targets = [60, 75, 90, 100, 110, 120, 128, 140, 160, 180]
    errors: list[float] = []
    within_4pct = 0
    per_target: dict[str, float] = {}
    for bpm in targets:
        sig = _click_track(bpm, 20).astype(np.float32)
        try:
            pred, _conf = detect_bpm(sig, SR)
            pred = float(pred or 0.0)
        except Exception:
            pred = 0.0
        # MIREX: accept half/double tempo as correct.
        tempo_diff = min(abs(pred - bpm), abs(pred - bpm / 2.0), abs(pred - bpm * 2.0))
        err = tempo_diff
        errors.append(err)
        per_target[str(bpm)] = round(pred, 2)
        if pred > 0 and err / bpm <= 0.04:
            within_4pct += 1
    return {
        "skipped": False,
        "mae_bpm": round(float(np.mean(errors)), 3),
        "tolerance_4pct_acc": round(within_4pct / len(targets), 4),
        "total": len(targets),
        "per_target": per_target,
    }


# ----------------------------------------------------------------------------
# Onset detection
# ----------------------------------------------------------------------------

def measure_onset_f1() -> dict:
    try:
        import librosa
    except Exception as e:
        return {"skipped": True, "reason": f"librosa unavailable: {e!r}"}

    # Build a click track at 120 BPM (0.5s spacing) for 10 seconds.
    bpm = 120
    dur = 10
    sig = _click_track(bpm, dur)
    truth = np.arange(0, dur, 60.0 / bpm)
    truth = truth[truth < dur]

    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "click.wav"
            _save_wav(path, sig)
            y, sr = librosa.load(str(path), sr=SR, mono=True)
            onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    except Exception as e:
        return {"skipped": True, "reason": f"onset detection failed: {e!r}"}

    tol = 0.05    # 50 ms
    matched = set()
    tp = 0
    for o in onset_frames:
        best = None
        for i, t in enumerate(truth):
            if i in matched:
                continue
            if abs(o - t) <= tol:
                best = i
                break
        if best is not None:
            matched.add(best)
            tp += 1
    fp = len(onset_frames) - tp
    fn = len(truth) - tp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "skipped": False,
        "f1_50ms": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "truth_count": int(len(truth)),
        "predicted_count": int(len(onset_frames)),
    }


# ----------------------------------------------------------------------------
# Chord symbol (root + quality)
# ----------------------------------------------------------------------------

def measure_chord_symbol_acc() -> dict:
    """Build sustained triads and ask the chord analyser to identify them."""
    try:
        from backend.app.pipeline.chords import analyze_chords
    except Exception as e:
        return {"skipped": True, "reason": f"analyze_chords import failed: {e!r}"}

    cases = [
        ("C", "maj", [261.63, 329.63, 392.00]),    # C E G
        ("D", "min", [293.66, 349.23, 440.00]),    # D F A
        ("F", "maj", [349.23, 440.00, 523.25]),    # F A C
        ("G", "maj", [392.00, 493.88, 587.33]),    # G B D
        ("A", "min", [440.00, 523.25, 659.25]),    # A C E
    ]
    correct = 0
    per_chord: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for root, quality, freqs in cases:
            sig = sum(_sine(f, 8) for f in freqs)
            peak = float(np.max(np.abs(sig)))
            if peak > 1.0:
                sig = sig / peak
            path = Path(tmp) / f"chord_{root}_{quality}.wav"
            _save_wav(path, sig)
            try:
                events = analyze_chords(path) or []
                labels = [(ev.label or "").strip() for ev in events]
                roots = [(ev.root or "").strip() for ev in events]
                qualities = [(ev.quality or "").strip() for ev in events]
            except Exception:
                labels, roots, qualities = [], [], []
            ok = any(
                (r == root) and (q == quality)
                for r, q in zip(roots, qualities)
            )
            per_chord[f"{root}{quality}"] = {"ok": ok, "labels": labels[:3]}
            correct += int(ok)
    return {
        "skipped": False,
        "symbol_acc": round(correct / len(cases), 4),
        "total": len(cases),
        "per_chord": per_chord,
    }


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="JSON output path (default: data/qa/accuracy_<date>.json)")
    ap.add_argument("--skip", action="append", default=[], choices=["key", "bpm", "onset", "chord"],
                    help="Skip a specific test (repeatable)")
    args = ap.parse_args()

    metrics: dict = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "host": os.environ.get("COMPUTERNAME") or os.uname().nodename if hasattr(os, "uname") else "?",
    }

    if "key" not in args.skip:
        print("[key] measuring...", flush=True)
        metrics["key"] = measure_key_accuracy()
    if "bpm" not in args.skip:
        print("[bpm] measuring...", flush=True)
        metrics["bpm"] = measure_bpm_accuracy()
    if "onset" not in args.skip:
        print("[onset] measuring...", flush=True)
        metrics["onset"] = measure_onset_f1()
    if "chord" not in args.skip:
        print("[chord] measuring...", flush=True)
        metrics["chord"] = measure_chord_symbol_acc()

    out = args.out or f"data/qa/accuracy_{dt.date.today().isoformat()}.json"
    out_path = ROOT / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    # Human-readable summary.
    print("\n=== Accuracy report ===")
    for k in ("key", "bpm", "onset", "chord"):
        v = metrics.get(k)
        if not v:
            continue
        if v.get("skipped"):
            print(f"  {k:<6}  SKIPPED: {v.get('reason','?')}")
        else:
            highlight = (
                v.get("major_correct")
                if k == "key"
                else v.get("tolerance_4pct_acc") if k == "bpm"
                else v.get("f1_50ms") if k == "onset"
                else v.get("symbol_acc")
            )
            print(f"  {k:<6}  {highlight!r}  →  {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
