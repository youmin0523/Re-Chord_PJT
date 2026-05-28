"""Measure auto-tune correction accuracy on synthetic detuned vocals.

Ground truth: we synthesize sustained tones intentionally detuned by a
known amount (±20-60 cents) from C-major scale degrees, run autotune
(CREPE+WORLD, scale-aware), then measure how close the output lands to
the intended scale tone. A correct auto-tune pulls the pitch toward the
grid; we report residual cents error after correction vs before.

Output: data/qa/autotune_accuracy_<date>.json
"""

from __future__ import annotations

import datetime as dt
import json
import math
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SR = 44100


def _midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12.0)


def _detuned_tone(midi: int, cents_off: float, dur: float = 1.2) -> np.ndarray:
    """Sustained harmonic tone detuned by cents_off from the exact pitch."""
    f = _midi_hz(midi) * 2 ** (cents_off / 1200.0)
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = (np.sin(2 * math.pi * f * t)
           + 0.4 * np.sin(2 * math.pi * 2 * f * t)
           + 0.2 * np.sin(2 * math.pi * 3 * f * t)).astype(np.float32)
    env = np.ones(n, dtype=np.float32)
    a = int(0.02 * SR)
    env[:a] = np.linspace(0, 1, a); env[-a:] = np.linspace(1, 0, a)
    return sig * env * 0.3


def _write(path: Path, mono: np.ndarray):
    import soundfile as sf
    sf.write(str(path), np.stack([mono, mono], axis=1), SR, subtype="FLOAT")


def _dominant_hz(mono: np.ndarray) -> float:
    n = len(mono)
    seg = mono[n // 4: n // 4 + min(n // 2, 1 << 15)]
    if len(seg) < 1024:
        seg = mono
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / SR)
    k = int(np.argmax(spec))
    if 1 <= k < len(spec) - 1:
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        d = (a - 2 * b + c)
        delta = 0.5 * (a - c) / d if d != 0 else 0.0
    else:
        delta = 0.0
    return float((k + delta) * (freqs[1] - freqs[0]))


def main() -> int:
    from backend.app.pipeline.autotune import autotune_vocal, is_available
    if not is_available():
        print("[skip] crepe/pyworld not available")
        return 0

    # C-major scale degrees, each detuned by a known offset.
    cases = [
        (60, +40), (62, -35), (64, +50), (65, -25),
        (67, +30), (69, -45), (71, +20), (72, -55),
    ]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for midi, off in cases:
            src = Path(tmp) / f"in_{midi}_{off}.wav"
            out = Path(tmp) / f"out_{midi}_{off}.wav"
            _write(src, _detuned_tone(midi, off))
            try:
                autotune_vocal(src, out, key_root="C", scale="major",
                               preset="natural")
            except Exception as e:
                rows.append({"midi": midi, "detune_cents": off,
                             "err": repr(e)[:120]})
                continue
            import soundfile as sf
            audio, _ = sf.read(str(out), dtype="float32", always_2d=True)
            measured = _dominant_hz(audio.mean(axis=1))
            # Correct ground truth for a scale-snapping autotune: the
            # NEAREST C-major scale tone to the (detuned) input pitch.
            # A correct autotune pulls toward that, not necessarily back
            # to the note we started detuning from.
            c_major = {0, 2, 4, 5, 7, 9, 11}
            in_midi_f = midi + off / 100.0
            # nearest scale tone in semitones (search ±2 semitones).
            best_t, best_d = midi, 99.0
            for cand in range(midi - 2, midi + 3):
                if cand % 12 in c_major and abs(cand - in_midi_f) < best_d:
                    best_d = abs(cand - in_midi_f); best_t = cand
            target = _midi_hz(best_t)
            resid = 1200.0 * math.log2(measured / target) if measured > 0 else 9999
            # input distance to that same nearest scale tone, for "improved".
            in_resid = (in_midi_f - best_t) * 100.0
            rows.append({
                "midi": midi, "detune_cents": off,
                "nearest_scale_midi": best_t,
                "residual_cents_after": round(resid, 1),
                "input_cents_to_target": round(in_resid, 1),
                "improved": abs(resid) < abs(in_resid),
            })

    valid = [r for r in rows if "residual_cents_after" in r]
    resids = [abs(r["residual_cents_after"]) for r in valid]
    n_improved = sum(1 for r in valid if r["improved"])
    report = {
        "date": dt.date.today().isoformat(),
        "preset": "natural",
        "cases": rows,
        "mean_residual_cents": round(float(np.mean(resids)), 1) if resids else None,
        "improved_rate": round(n_improved / len(valid), 3) if valid else None,
        "note": "Lower residual = better pull-to-grid. Natural preset is "
                "partial-correction (won't fully snap), so some residual "
                "is by design.",
    }
    out = ROOT / "data" / "qa" / f"autotune_accuracy_{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== auto-tune correction (natural preset) ===")
    for r in rows:
        if "residual_cents_after" in r:
            print(f"  midi {r['midi']} detuned {r['detune_cents']:+d}c "
                  f"→ residual {r['residual_cents_after']:+.1f}c "
                  f"{'(improved)' if r['improved'] else '(worse!)'}")
    print(f"mean|residual|={report['mean_residual_cents']}c, "
          f"improved_rate={report['improved_rate']}")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
