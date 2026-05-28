"""CI-friendly smoke test for the synthetic 4-stem corpus.

We don't run the real separator here (CI has no GPU + 6 GB of weights),
but we *do* validate the core invariants the separator-free parts of the
pipeline rely on:

  1. The synth corpus is byte-deterministic (same seed → same WAVs).
  2. mixture = vocals + drums + bass + other  (within float rounding).
  3. ``ensemble.ensemble_stems`` correctly fuses three identical copies
     of one stem back to that stem (regression for the new weighted
     ensemble + phase-coherent path).
  4. ``ensemble.apply_diff_mask_iterative`` actually reduces the
     mixture's energy in the vocals' band when the vocals stem is
     provided as the leakage source.
  5. ``compute_quality`` returns a finite null-rms / corr / xcorr triple
     on the synthetic mix.

These run in well under 5 seconds on a CI Ubuntu runner.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture(scope="module")
def synth_corpus():
    """Build a 2-song corpus into a tempdir; clean up at module teardown."""
    from scripts.build_synth_4stem_corpus import build_corpus
    tmp = Path(tempfile.mkdtemp(prefix="rechord_synth_"))
    try:
        paths = build_corpus(tmp, n_songs=2)
        yield paths
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_corpus_is_deterministic(tmp_path):
    """Building twice with the same seed must produce identical WAVs."""
    from scripts.build_synth_4stem_corpus import build_corpus
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    build_corpus(d1, n_songs=1)
    build_corpus(d2, n_songs=1)
    for name in ("mixture.wav", "vocals.wav", "drums.wav", "bass.wav", "other.wav"):
        a = (d1 / "synth-song-01" / name).read_bytes()
        b = (d2 / "synth-song-01" / name).read_bytes()
        assert a == b, f"{name} differs between runs"


def test_mixture_equals_sum_of_stems(synth_corpus):
    for song_dir in synth_corpus:
        mix, sr = sf.read(str(song_dir / "mixture.wav"), dtype="float32",
                          always_2d=True)
        v, _ = sf.read(str(song_dir / "vocals.wav"), dtype="float32",
                       always_2d=True)
        d, _ = sf.read(str(song_dir / "drums.wav"), dtype="float32",
                       always_2d=True)
        b, _ = sf.read(str(song_dir / "bass.wav"), dtype="float32",
                       always_2d=True)
        o, _ = sf.read(str(song_dir / "other.wav"), dtype="float32",
                       always_2d=True)
        n = min(mix.shape[0], v.shape[0], d.shape[0], b.shape[0], o.shape[0])
        residual = mix[:n] - (v[:n] + d[:n] + b[:n] + o[:n])
        # Allow ~ −60 dBFS rounding error (16-bit WAV through 32-bit float).
        rms = float(np.sqrt(np.mean(residual ** 2)))
        assert rms < 1e-3, f"{song_dir.name}: |mix - sum| RMS {rms:.5f}"


def test_ensemble_returns_input_when_all_copies_identical(synth_corpus, tmp_path):
    """The weighted_mag ensemble of three identical sources must equal
    the source within numerical noise. Regression guard for the new
    phase-coherent path."""
    from backend.app.pipeline.ensemble import ensemble_stems
    song = synth_corpus[0]
    src = song / "vocals.wav"
    sources = [src, src, src]
    out = tmp_path / "ensembled.wav"
    res = ensemble_stems(
        sources, out, method="weighted_mag", target_sr=22050,
        weights=[1.0, 1.0, 1.0], phase_coherent=True,
    )
    assert res.out_path.exists()
    orig, sr_o = sf.read(str(src), dtype="float32", always_2d=True)
    fused, sr_f = sf.read(str(res.out_path), dtype="float32", always_2d=True)
    assert sr_o == 22050 and sr_f == 22050
    n = min(orig.shape[0], fused.shape[0])
    diff = fused[:n] - orig[:n]
    rms = float(np.sqrt(np.mean(diff ** 2)))
    # STFT round-trip + clip safety introduces ~ -45 dBFS noise.
    assert rms < 5e-3, f"ensemble drift: rms={rms}"


def test_iterative_diff_mask_reduces_vocal_band_energy(synth_corpus, tmp_path):
    from backend.app.pipeline.ensemble import apply_diff_mask_iterative
    song = synth_corpus[0]
    # Use the mixture as "instrumental + vocal residue" and the vocals
    # stem as the leakage source — diff-mask should drop the vocal band.
    inst = song / "mixture.wav"
    voc = song / "vocals.wav"
    out = tmp_path / "diffmasked.wav"
    apply_diff_mask_iterative(inst, voc, out, target_sr=22050,
                              passes=2, strength=0.55)
    assert out.exists()

    def _band_rms(p: Path, lo: float, hi: float) -> float:
        a, sr = sf.read(str(p), dtype="float32", always_2d=True)
        mono = a.mean(axis=1)
        spec = np.fft.rfft(mono)
        freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
        mask = (freqs >= lo) & (freqs <= hi)
        return float(np.sqrt(np.mean(np.abs(spec[mask]) ** 2)))

    # 220-330 Hz is the synth vocal pitch range.
    before = _band_rms(inst, 200.0, 350.0)
    after = _band_rms(out, 200.0, 350.0)
    assert after < before, f"diff-mask did not reduce vocal band: " \
                           f"before={before:.4f} after={after:.4f}"


def test_compute_quality_runs_clean(synth_corpus):
    from backend.app.pipeline.quality import compute_quality
    song = synth_corpus[0]
    rep = compute_quality(
        song / "mixture.wav",
        song / "other.wav",      # pretend "other" is the instrumental
        song / "vocals.wav",
        target_sr=22050, sample_seconds=5.0,
    )
    assert np.isfinite(rep.null_rms_dbfs)
    assert -1.0 <= rep.reconstruction_corr <= 1.0
    assert -1.0 <= rep.voc_inst_xcorr <= 1.0
    assert rep.grade() in {"E", "D", "C", "B", "B+", "A", "A+"}
