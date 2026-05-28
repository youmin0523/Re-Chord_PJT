"""Pin the stem cross-bleed detector.

  * Two uncorrelated stems → near-zero xcorr, "clean".
  * Two stems where one contains a copy of the other → high xcorr,
    flagged.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from backend.app.pipeline.quality import measure_stem_overlap


SR = 22050


def _write(path: Path, mono: np.ndarray) -> None:
    stereo = np.stack([mono, mono], axis=1)
    stereo = np.clip(stereo, -1.0, 1.0)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def _tone(freq: float, dur: float = 3.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    return (0.4 * np.sin(2 * math.pi * freq * t)).astype(np.float32)


def test_uncorrelated_stems_are_clean(tmp_path):
    a = tmp_path / "bass.wav"
    b = tmp_path / "guitar.wav"
    rng = np.random.default_rng(0)
    _write(a, (0.3 * rng.standard_normal(int(3 * SR))).astype(np.float32))
    _write(b, (0.3 * rng.standard_normal(int(3 * SR))).astype(np.float32))
    rep = measure_stem_overlap({"bass": a, "guitar": b}, target_sr=SR,
                               sample_seconds=3.0)
    assert rep["max_xcorr"] < 0.2
    assert rep["flagged"] == []


def test_bleeding_stems_are_flagged(tmp_path):
    """guitar = a fresh signal; 'other' = the same guitar signal + a bit
    of noise → strong correlation → flagged as bleed."""
    base = _tone(196.0)        # G3
    rng = np.random.default_rng(1)
    other = base + 0.05 * rng.standard_normal(len(base)).astype(np.float32)
    g = tmp_path / "guitar.wav"
    o = tmp_path / "other.wav"
    _write(g, base)
    _write(o, other)
    rep = measure_stem_overlap({"guitar": g, "other": o}, target_sr=SR,
                               sample_seconds=3.0)
    assert rep["max_xcorr"] > 0.5
    assert "guitar↔other" in rep["flagged"]
    assert rep["worst_pair"]["bleed"] in ("moderate", "heavy")


def test_handles_missing_files_gracefully(tmp_path):
    a = tmp_path / "bass.wav"
    _write(a, _tone(110.0))
    rep = measure_stem_overlap(
        {"bass": a, "ghost": tmp_path / "nonexistent.wav"},
        target_sr=SR, sample_seconds=3.0,
    )
    # Only one valid stem → no pairs, no crash.
    assert rep["pairs"] == []
    assert rep["max_xcorr"] == 0.0
