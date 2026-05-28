"""Measure section-detection accuracy on a synthetic structured song.

We build a song with a KNOWN form: intro / verse / chorus / verse /
chorus, where each section has a distinct harmonic+timbral signature
(so a self-similarity / chroma method can find the boundaries). Ground
truth = the boundaries we placed.

Metrics:
  * boundary hit rate  — fraction of GT boundaries matched within ±3 s
  * over/under-seg     — predicted vs GT segment count ratio

Section *labels* (verse vs chorus) are notoriously hard and language-
dependent; we report label agreement too but treat boundary detection
as the primary metric (that's what drives click-track/cue placement).

Output: data/qa/section_accuracy_<date>.json
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


def _chord_bed(roots_hz, dur, sr=SR):
    n = int(dur * sr)
    t = np.arange(n) / sr
    out = np.zeros(n, dtype=np.float32)
    for f in roots_hz:
        out += 0.15 * np.sin(2 * math.pi * f * t).astype(np.float32)
    return out


def _kick_bed(dur, bpm=120, sr=SR, level=0.4):
    n = int(dur * sr)
    out = np.zeros(n, dtype=np.float32)
    beat = 60.0 / bpm
    for b in range(int(dur / beat)):
        s = int(b * beat * sr)
        kn = int(0.1 * sr)
        e = min(n, s + kn)
        tt = np.arange(e - s) / sr
        sweep = np.linspace(110, 50, e - s)
        ph = 2 * math.pi * np.cumsum(sweep) / sr
        out[s:e] += level * (np.sin(ph) * np.exp(-tt / 0.07)).astype(np.float32)
    return out


def _build_song():
    """intro(8s) verse(16) chorus(16) verse(16) chorus(16). Distinct
    harmony per section type so SSM can separate them."""
    verse_ch = [220.0, 277.18, 329.63]      # A C# E  (A major-ish)
    chorus_ch = [261.63, 329.63, 392.0]     # C E G   (C major) — brighter
    intro_ch = [220.0, 261.63, 329.63]      # sparse

    plan = [("intro", 8.0, intro_ch, 0.15),
            ("verse", 16.0, verse_ch, 0.4),
            ("chorus", 16.0, chorus_ch, 0.5),
            ("verse", 16.0, verse_ch, 0.4),
            ("chorus", 16.0, chorus_ch, 0.5)]
    gt_bounds = []
    chunks = []
    cursor = 0.0
    for name, dur, ch, kicklvl in plan:
        gt_bounds.append((cursor, name))
        bed = _chord_bed(ch, dur)
        # chorus brighter: add an upper octave
        if name == "chorus":
            bed += _chord_bed([c * 2 for c in ch], dur) * 0.5
        kick = _kick_bed(dur, level=kicklvl)
        chunks.append((bed + kick).astype(np.float32))
        cursor += dur
    audio = np.concatenate(chunks)
    audio = np.clip(audio / (np.max(np.abs(audio)) + 1e-9) * 0.9, -1, 1)
    return audio.astype(np.float32), gt_bounds, cursor


def _write(path, mono):
    import soundfile as sf
    sf.write(str(path), np.stack([mono, mono], axis=1), SR, subtype="FLOAT")


def main() -> int:
    audio, gt_bounds, total = _build_song()
    gt_times = [t for t, _ in gt_bounds][1:]   # internal boundaries (skip 0)
    print(f"[info] synthetic song {total:.0f}s, {len(gt_bounds)} sections, "
          f"GT internal boundaries: {[round(t,1) for t in gt_times]}")

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "song.wav"
        _write(wav, audio)
        from backend.app.pipeline.sections import analyze_sections
        res = analyze_sections(wav, "auto", refine=False)
        pred = res.sections

    pred_bounds = [s.start_sec for s in pred][1:]   # skip the 0 start
    # Boundary hit rate within ±3s.
    TOL = 3.0
    hits = 0
    for g in gt_times:
        if any(abs(p - g) <= TOL for p in pred_bounds):
            hits += 1
    hit_rate = hits / len(gt_times) if gt_times else 1.0

    report = {
        "date": dt.date.today().isoformat(),
        "gt_sections": len(gt_bounds),
        "gt_boundaries": [round(t, 1) for t in gt_times],
        "pred_sections": len(pred),
        "pred_boundaries": [round(p, 1) for p in pred_bounds],
        "boundary_hit_rate_3s": round(hit_rate, 3),
        "segment_count_ratio": round(len(pred) / len(gt_bounds), 2),
        "note": "Synthetic clear-structure song; real worship is harder. "
                "Boundary detection is the primary metric (drives cues).",
    }
    out = ROOT / "data" / "qa" / f"section_accuracy_{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  GT boundaries:   {report['gt_boundaries']}")
    print(f"  pred boundaries: {report['pred_boundaries']}")
    print(f"  boundary hit rate (±3s) = {hit_rate:.3f}")
    print(f"  segment count: pred {len(pred)} vs GT {len(gt_bounds)}")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
