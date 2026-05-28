"""Ground-truth verification of the mastering LUFS + true-peak stage.

This is a fully deterministic measurement (no GPU, no models): we
synthesize signals at known loudness, run normalize_lufs targeting each
platform preset, then re-measure the OUTPUT's integrated LUFS with
pyloudnorm and assert it lands on target. We also verify the true-peak
ceiling is respected.

Gated against tests/fixtures/accuracy_thresholds.json:loudness.
"""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
THR = json.loads(
    (ROOT / "tests" / "fixtures" / "accuracy_thresholds.json").read_text(encoding="utf-8")
)["loudness"]
SR = 48000


def _have_pyln():
    try:
        import pyloudnorm  # noqa: F401
        return True
    except Exception:
        return False


def _write_wav(path: Path, audio: np.ndarray, sr: int = SR):
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    import soundfile as sf
    sf.write(str(path), audio.astype(np.float32), sr, subtype="FLOAT")


def _pink_ish(dur=8.0, level=0.3, seed=0):
    """A broadband-ish test signal (sum of tones + noise) at a given peak."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    sig = (0.5 * np.sin(2 * math.pi * 220 * t)
           + 0.3 * np.sin(2 * math.pi * 440 * t)
           + 0.2 * np.sin(2 * math.pi * 880 * t)).astype(np.float32)
    sig += 0.1 * rng.standard_normal(n).astype(np.float32)
    sig = sig / (np.max(np.abs(sig)) + 1e-9) * level
    return sig.astype(np.float32)


@pytest.mark.parametrize("target", [-14.0, -16.0, -23.0])
def test_lufs_normalization_hits_target(tmp_path, target):
    if not _have_pyln():
        pytest.skip("pyloudnorm not installed")
    import pyloudnorm as pyln
    from backend.app.pipeline.mastering import normalize_lufs

    src = tmp_path / "src.wav"
    out = tmp_path / "out.wav"
    _write_wav(src, _pink_ish(level=0.25))
    res = normalize_lufs(src, out, target_lufs=target, use_limiter=True)

    # Re-measure the OUTPUT independently.
    import soundfile as sf
    audio, sr = sf.read(str(out), dtype="float32", always_2d=True)
    meter = pyln.Meter(sr)
    measured = float(meter.integrated_loudness(audio))

    err = abs(measured - target)
    max_err = THR["lufs_error_db"]["min"]    # 'min' is the hard tolerance
    print(f"  target={target}  measured={measured:.2f}  err={err:.2f}dB "
          f"(limiter={res.limiter_applied})")
    assert err <= max_err, \
        f"LUFS off by {err:.2f}dB (target {target}, got {measured:.2f}); tol {max_err}"


@pytest.mark.parametrize("target", [-14.0, -9.0])
def test_true_peak_ceiling_respected(tmp_path, target):
    """After normalization (esp. a loud target on a hot source) the true
    peak must stay under the ceiling — no inter-sample clipping."""
    if not _have_pyln():
        pytest.skip("pyloudnorm not installed")
    from backend.app.pipeline.mastering import normalize_lufs, _true_peak_dbtp

    src = tmp_path / "src.wav"
    out = tmp_path / "out.wav"
    # Hot source so a loud LUFS target forces the limiter to engage.
    _write_wav(src, _pink_ish(level=0.6))
    res = normalize_lufs(src, out, target_lufs=target,
                         true_peak_ceiling_dbtp=-1.0, use_limiter=True)

    import soundfile as sf
    audio, _ = sf.read(str(out), dtype="float32", always_2d=True)
    tp = _true_peak_dbtp(audio, SR)
    ceiling = THR["true_peak_max_dbtp"]["min"]   # -0.5 dBTP hard ceiling
    print(f"  target={target}  true_peak_after={tp:.2f}dBTP "
          f"(reported={res.true_peak_dbtp_after:.2f}, limiter={res.limiter_applied})")
    assert tp <= ceiling, f"true peak {tp:.2f}dBTP exceeds ceiling {ceiling}"


def test_silence_passthrough_no_crash(tmp_path):
    if not _have_pyln():
        pytest.skip("pyloudnorm not installed")
    from backend.app.pipeline.mastering import normalize_lufs
    src = tmp_path / "sil.wav"
    out = tmp_path / "out.wav"
    _write_wav(src, np.zeros(int(2 * SR), dtype=np.float32))
    res = normalize_lufs(src, out, target_lufs=-14.0)
    assert out.exists()
    assert res.gain_db == 0.0
