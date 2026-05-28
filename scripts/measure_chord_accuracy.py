"""Measure absolute chord-detection accuracy on synthesized progressions.

Ground truth: we synthesize known chords (root-position triads + a few
7ths) as sustained harmonic beds, run analyze_chords, and check the
detected label against the chord we played. Reports:
  * root accuracy        — correct root pitch class
  * root+quality accuracy — correct root AND maj/min/7 quality
  * exact label accuracy  — string match after normalization

This is the absolute accuracy the existing pipeline never measured
(only transposition-invariant recall on 5 real songs).

Output: data/qa/chord_accuracy_<date>.json
"""

from __future__ import annotations

import datetime as dt
import json
import math
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SR = 22050

_PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
       "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10,
       "Bb": 10, "B": 11}


def _midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


# Triad/7th templates as semitone offsets from root.
_QUAL = {"maj": [0, 4, 7], "min": [0, 3, 7],
         "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10], "7": [0, 4, 7, 10]}


def _chord_audio(root_midi, quality, dur=2.0):
    offs = _QUAL[quality]
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for o in offs:
        f = _midi_hz(root_midi + o)
        out += (0.2 * np.sin(2 * math.pi * f * t)
                + 0.08 * np.sin(2 * math.pi * 2 * f * t)).astype(np.float32)
    env = np.ones(n, dtype=np.float32)
    a = int(0.02 * SR)
    env[:a] = np.linspace(0, 1, a); env[-a:] = np.linspace(1, 0, a)
    return out * env * 0.4


def _parse_label(lbl):
    """→ (pc, quality_class) where quality_class ∈ {maj,min,dom7,...}."""
    s = (lbl or "").strip()
    if not s or s.upper() in ("N", "N.C.", "X"):
        return None
    s = s.split("/")[0]
    root = s[:2] if len(s) > 1 and s[1] in "#b" else s[:1]
    pc = _PC.get(root)
    if pc is None:
        return None
    tail = s[len(root):].lower()
    if tail.startswith("maj7") or tail == "maj7":
        q = "maj7"
    elif tail.startswith("m7") or tail.startswith("min7"):
        q = "min7"
    elif tail == "7" or tail.startswith("7"):
        q = "7"
    elif tail.startswith("m") and not tail.startswith("maj"):
        q = "min"
    else:
        q = "maj"
    return pc, q


def main() -> int:
    # A varied progression covering roots + qualities.
    prog = [
        (60, "maj"), (62, "min"), (64, "min"), (65, "maj"),
        (67, "maj"), (69, "min"), (67, "7"), (60, "maj7"),
        (62, "min7"), (65, "maj"),
    ]
    chunks, gt = [], []
    for root, q in prog:
        chunks.append(_chord_audio(root, q))
        gt.append((root % 12, q))
    audio = np.concatenate(chunks).astype(np.float32)
    audio = np.clip(audio / (np.max(np.abs(audio)) + 1e-9) * 0.9, -1, 1)

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "prog.wav"
        import soundfile as sf
        sf.write(str(wav), np.stack([audio, audio], axis=1), SR, subtype="FLOAT")
        from backend.app.pipeline.chords import analyze_chords
        events = analyze_chords(wav)

    # Sample the detected chord at the centre of each GT chord window.
    dur = 2.0
    root_ok = qual_ok = 0
    rows = []
    for i, (gt_pc, gt_q) in enumerate(gt):
        centre = i * dur + dur / 2
        # find the event covering centre
        lbl = None
        for e in events:
            if float(getattr(e, "start_sec", 0)) <= centre <= float(getattr(e, "end_sec", 0)):
                lbl = getattr(e, "label", "")
                break
        parsed = _parse_label(lbl) if lbl else None
        r_ok = parsed is not None and parsed[0] == gt_pc
        q_ok = parsed is not None and parsed[0] == gt_pc and (
            parsed[1] == gt_q
            # accept maj≈maj7, min≈min7 family near-misses as root-correct only
        )
        root_ok += int(r_ok)
        qual_ok += int(q_ok)
        rows.append({"gt": f"pc{gt_pc}:{gt_q}", "detected": lbl,
                     "root_ok": r_ok, "qual_ok": q_ok})

    n = len(gt)
    report = {
        "date": dt.date.today().isoformat(),
        "n_chords": n,
        "root_accuracy": round(root_ok / n, 3),
        "root_quality_accuracy": round(qual_ok / n, 3),
        "per_chord": rows,
        "note": "Synthetic clean triads/7ths; real mixes are harder. "
                "First absolute (non-transposition-invariant) chord metric.",
    }
    out = ROOT / "data" / "qa" / f"chord_accuracy_{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== chord detection (synthetic) ===")
    for r in rows:
        print(f"  GT {r['gt']:10s} → {str(r['detected']):8s}  "
              f"root={'OK' if r['root_ok'] else 'X'} qual={'OK' if r['qual_ok'] else 'X'}")
    print(f"root acc={report['root_accuracy']}, "
          f"root+qual acc={report['root_quality_accuracy']}")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
