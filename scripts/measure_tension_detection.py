"""Measure chroma-based tension detection (add9/6/sus/7) on synth chords.

Ground truth: we synthesize chords WITH known extensions (Cadd9, C6,
Csus4, Csus2, C7, Cmaj7) as harmonic beds, compute the chroma the
detector would see, and check detect_tensions() recovers the extension.

This covers exactly what CREMA cannot (add9/6/sus). Output:
data/qa/tension_detection_<date>.json
"""

from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np

ROOT_HZ = {"C": 261.63}
SR = 22050
_PC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _chord_chroma(semitones_from_C, dur=2.0):
    """Synthesize a chord (given pitch-class offsets) and return its
    chroma_cqt vector the way analyze_chords computes it."""
    import librosa
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n, dtype=np.float32)
    base = 261.63  # C4
    for st in semitones_from_C:
        f = base * 2 ** (st / 12.0)
        sig += (0.25 * np.sin(2 * math.pi * f * t)
                + 0.1 * np.sin(2 * math.pi * 2 * f * t)).astype(np.float32)
    y_h = librosa.effects.harmonic(sig, margin=4.0)
    chroma = librosa.feature.chroma_cqt(y=y_h, sr=SR, hop_length=512, n_chroma=12)
    return chroma.mean(axis=1)


def main() -> int:
    from backend.app.pipeline.chord_tension import detect_tensions

    # chord name → (semitone offsets, root_pc, is_minor, expected detection)
    cases = {
        "Cadd9": ([0, 4, 7, 14], 0, False, {"add": "add9"}),
        "C6":    ([0, 4, 7, 9], 0, False, {"add": "6"}),
        "Csus4": ([0, 5, 7], 0, False, {"sus": "sus4"}),
        "Csus2": ([0, 2, 7], 0, False, {"sus": "sus2"}),
        "C7":    ([0, 4, 7, 10], 0, False, {"seventh": "7"}),
        "Cmaj7": ([0, 4, 7, 11], 0, False, {"seventh": "maj7"}),
        # Upper-structure extensions (9/11/13) sitting on a 7th.
        "C9":    ([0, 4, 7, 10, 14], 0, False, {"seventh": "7", "ext": "9"}),
        "C11":   ([0, 4, 7, 10, 14, 17], 0, False, {"seventh": "7", "ext": "11"}),
        "C13":   ([0, 4, 7, 10, 14, 17, 21], 0, False, {"seventh": "7", "ext": "13"}),
        "Cmaj9": ([0, 4, 7, 11, 14], 0, False, {"seventh": "maj7", "ext": "9"}),
        # Minor 9th, root D (pc 2): D F A C E.
        "Dm9":   ([2, 5, 9, 12, 16], 2, True, {"seventh": "7", "ext": "9"}),
        # Altered dominants / lydian maj7 (modern worship harmony).
        "C7b9":     ([0, 4, 7, 10, 13], 0, False, {"alt": ["b9"]}),
        "C7#9":     ([0, 4, 7, 10, 15], 0, False, {"alt": ["#9"]}),
        "C7#11":    ([0, 4, 7, 10, 18], 0, False, {"alt": ["#11"]}),
        "C7#5":     ([0, 4, 8, 10], 0, False, {"alt": ["#5"]}),
        "Cmaj7#11": ([0, 4, 7, 11, 18], 0, False, {"alt": ["#11"]}),
        "C7alt":    ([0, 4, 10, 13, 15], 0, False, {"alt": ["b9", "#9"]}),
        "C":     ([0, 4, 7], 0, False, {}),   # plain triad — should NOT add tension
    }
    rows = []
    correct = 0
    for name, (offs, root_pc, is_minor, expected) in cases.items():
        chroma = _chord_chroma(offs)
        t = detect_tensions(root_pc, is_minor, chroma)
        # Check the expected key matches.
        ok = True
        for k, v in expected.items():
            if t.get(k) != v:
                ok = False
        # For plain triad, ensure NOTHING fired.
        if not expected:
            ok = (t.get("sus") is None and t.get("seventh") is None
                  and t.get("add") is None and t.get("ext") is None
                  and t.get("alt") is None)
        correct += int(ok)
        rows.append({"chord": name, "expected": expected,
                     "detected": {k: t[k] for k in
                                  ("sus", "seventh", "add", "ext", "alt")},
                     "ok": ok})

    acc = correct / len(cases)
    report = {
        "date": dt.date.today().isoformat(),
        "accuracy": round(acc, 3),
        "n_cases": len(cases),
        "cases": rows,
        "note": "Synthetic clean chords. Covers add9/6/sus/7 that CREMA "
                "cannot output. Real mixes are noisier — detector is "
                "conservative to avoid hallucinating tensions.",
    }
    from pathlib import Path
    out = Path(__file__).resolve().parent.parent / "data" / "qa" / f"tension_detection_{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== chroma tension detection (synth) ===")
    for r in rows:
        print(f"  {r['chord']:7s} expected {str(r['expected']):24s} "
              f"detected {str(r['detected'])}  {'OK' if r['ok'] else 'MISS'}")
    print(f"accuracy = {acc:.3f} ({correct}/{len(cases)})")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
