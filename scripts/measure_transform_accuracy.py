"""Measure pitch-transform accuracy: does ±N semitone shift land on the
right pitch?

Ground truth is exact: a 440 Hz tone shifted +N semitones must come out
at 440 * 2^(N/12) Hz. We synthesize a tone, run transform_audio for a
range of shifts, measure the output's dominant frequency (FFT peak +
parabolic interpolation), and report the error in cents.

Tests the Rubber Band / ffmpeg pitch path (and WORLD for large vocal
shifts). < 25 cents error is inaudible; < 50 is acceptable.

Output: data/qa/transform_accuracy_<date>.json
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
BASE_HZ = 440.0


def _tone(freq: float, dur: float = 3.0, sr: int = SR) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return (0.6 * np.sin(2 * math.pi * freq * t)).astype(np.float32)


def _write(path: Path, mono: np.ndarray):
    import soundfile as sf
    sf.write(str(path), np.stack([mono, mono], axis=1), SR, subtype="FLOAT")


def _dominant_hz(mono: np.ndarray, sr: int = SR) -> float:
    """FFT peak with parabolic interpolation for sub-bin accuracy."""
    # Use a long window from the steady middle of the signal.
    n = len(mono)
    seg = mono[n // 4: n // 4 + min(n // 2, 1 << 16)]
    win = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(len(win), 1.0 / sr)
    k = int(np.argmax(spec))
    if 1 <= k < len(spec) - 1:
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        denom = (a - 2 * b + c)
        delta = 0.5 * (a - c) / denom if denom != 0 else 0.0
    else:
        delta = 0.0
    bin_hz = freqs[1] - freqs[0]
    return float((k + delta) * bin_hz)


def _cents(measured: float, expected: float) -> float:
    if measured <= 0 or expected <= 0:
        return 9999.0
    return 1200.0 * math.log2(measured / expected)


def main() -> int:
    from backend.app.pipeline.transform import transform_audio
    shifts = [-7, -5, -3, -2, 2, 3, 5, 7]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "tone.wav"
        _write(src, _tone(BASE_HZ))
        for st in shifts:
            out = Path(tmp) / f"shift_{st}.wav"
            try:
                transform_audio(src, out, semitones=float(st), tempo_ratio=1.0,
                                stem_kind="instrumental")
            except Exception as e:
                rows.append({"semitones": st, "error_cents": None,
                             "err": repr(e)[:120]})
                continue
            import soundfile as sf
            audio, _ = sf.read(str(out), dtype="float32", always_2d=True)
            measured = _dominant_hz(audio.mean(axis=1))
            expected = BASE_HZ * 2 ** (st / 12.0)
            cents = _cents(measured, expected)
            rows.append({"semitones": st,
                         "expected_hz": round(expected, 2),
                         "measured_hz": round(measured, 2),
                         "error_cents": round(cents, 1)})

    valid = [r["error_cents"] for r in rows if r.get("error_cents") is not None]
    abs_errs = [abs(c) for c in valid]
    report = {
        "date": dt.date.today().isoformat(),
        "base_hz": BASE_HZ,
        "per_shift": rows,
        "mean_abs_cents": round(float(np.mean(abs_errs)), 2) if abs_errs else None,
        "max_abs_cents": round(float(np.max(abs_errs)), 2) if abs_errs else None,
        "note": "<25 cents inaudible, <50 acceptable.",
    }
    out = ROOT / "data" / "qa" / f"transform_accuracy_{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== pitch-transform accuracy ===")
    for r in rows:
        if r.get("error_cents") is not None:
            print(f"  {r['semitones']:+d} st: expected {r['expected_hz']}Hz "
                  f"measured {r['measured_hz']}Hz  err={r['error_cents']:+.1f} cents")
        else:
            print(f"  {r['semitones']:+d} st: FAILED {r.get('err')}")
    print(f"mean|err|={report['mean_abs_cents']} cents, "
          f"max|err|={report['max_abs_cents']} cents")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
