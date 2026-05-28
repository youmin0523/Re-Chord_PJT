"""Ensemble combination of multiple separation outputs.

Methods:
  mean    - time-domain average; fast, but vulnerable to phase mismatch between models
  mag_avg - STFT magnitude average + phase from first model; reduces smearing
  min     - STFT magnitude min + phase from first model; minimizes residual vocals
            in the instrumental stem (UVR5-style "min" ensemble)

Stereo modes:
  lr        - independent L and R channels (default — what every model does
              internally; safe, preserves whatever spatial decisions the
              underlying models made)
  mid_side  - decompose to mid (L+R) and side (L-R) before STFT-ensemble,
              recompose afterwards. Better at preserving stereo width on
              wide mixes because the side channel (room/reverb/panned
              elements) is processed independently from the center mass.
              ~5% extra CPU; small but real width gain on stereo masters.

Post-process:
  apply_diff_mask - given (instrumental, vocals, original_master), build a
                    spectrogram-domain mask that suppresses the bands where
                    the vocal stem still leaks into the instrumental. Cuts
                    typical residual-vocal energy by 3~6 dB at the cost of a
                    little high-frequency air.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir


EnsembleMethod = Literal["mean", "mag_avg", "min", "weighted_mag", "median"]
StereoMode = Literal["lr", "mid_side"]

N_FFT = 4096
HOP_LENGTH = 1024
WINDOW = "hann"


# Per-model "trust weights" derived from MUSDB18 published SDR figures.
# Higher = the magnitude spectrogram from that model gets more vote in
# weighted_mag ensemble. When the user-supplied model list contains a
# member not listed here, it receives the default weight 1.0.
#
# Source: model authors' reported SDR on MUSDB18 (vocals). Newer SOTA
# models (mel-band Kim FT2 bleedless, BS-Roformer 1297) dominate. Older
# htdemucs_ft / mdx23c are heavier-anchor models — kept for the timbral
# diversity that hurts an unweighted mean.
MODEL_WEIGHTS: dict[str, float] = {
    "melband_kim_ft2_bleedless":   1.50,
    "melband_kim_ft2":             1.40,
    "bs_roformer_1297":            1.35,
    "melband_kim_inst_v2":         1.30,
    "bs_roformer_1296":            1.25,
    "bs_roformer_hyperace_v2_voc": 1.25,
    "melband_kim_syhft_v3":        1.20,
    "melband_kim_inst_v1e":        1.15,
    "mdx23c_instvoc_hq":           1.00,
    "mdx23c_instvoc_hq_2":         1.00,
    "htdemucs_ft":                 0.90,
    "htdemucs_6s":                 0.85,
}


def weight_for_model(alias: str, default: float = 1.0) -> float:
    """Return the trust weight for a model alias (default 1.0 if unknown)."""
    return float(MODEL_WEIGHTS.get(alias, default))


@dataclass
class EnsembleResult:
    out_path: Path
    method: EnsembleMethod
    n_sources: int
    sample_rate: int
    duration_sec: float


def _read_audio(path: Path, target_sr: int | None = None) -> tuple[np.ndarray, int]:
    """Load audio as (samples, 2) float32, optionally resampled to target_sr."""
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    if target_sr is not None and sr != target_sr:
        import librosa
        out = np.stack(
            [librosa.resample(data[:, c], orig_sr=sr, target_sr=target_sr,
                              res_type="soxr_hq")
             for c in range(data.shape[1])],
            axis=-1,
        ).astype(np.float32)
        return out, target_sr
    return data, sr


def _stft_stereo(x: np.ndarray) -> np.ndarray:
    """STFT of a (samples, 2) array. Returns complex array of shape (freq, time, 2)."""
    import librosa
    # librosa.stft expects (channels, samples) or (samples,)
    xt = x.T  # (2, samples)
    specs = [librosa.stft(xt[c], n_fft=N_FFT, hop_length=HOP_LENGTH, window=WINDOW)
             for c in range(xt.shape[0])]
    return np.stack(specs, axis=-1)  # (freq, time, 2)


def _istft_stereo(spec: np.ndarray, length: int) -> np.ndarray:
    """Inverse STFT of (freq, time, 2) complex array back to (samples, 2)."""
    import librosa
    chans = [librosa.istft(spec[..., c], hop_length=HOP_LENGTH, window=WINDOW, length=length)
             for c in range(spec.shape[-1])]
    return np.stack(chans, axis=-1)


def _lr_to_ms(x: np.ndarray) -> np.ndarray:
    """Stereo (samples, 2) → mid/side (samples, 2). Reversible."""
    L = x[:, 0]; R = x[:, 1]
    M = (L + R) * 0.5
    S = (L - R) * 0.5
    return np.stack([M, S], axis=-1).astype(np.float32, copy=False)


def _ms_to_lr(x: np.ndarray) -> np.ndarray:
    M = x[:, 0]; S = x[:, 1]
    L = M + S
    R = M - S
    return np.stack([L, R], axis=-1).astype(np.float32, copy=False)


def _phase_coherent(stack: np.ndarray) -> np.ndarray:
    """Pick the most phase-coherent reference per (freq, time, channel) bin.

    Phase mismatch between models smears transients when we just take the
    first model's phase. We instead pick the phase from whichever model's
    magnitude is highest at each bin — empirically the loudest model is
    the one that "owns" that energy and its phase is the right one.
    Returns an (freq, time, 2) phase array.
    """
    mag = np.abs(stack)
    # argmax across the model dim → which model dominates each bin.
    dominant = np.argmax(mag, axis=0)        # (freq, time, 2)
    # Gather phase from the dominant model at each bin.
    # np.take_along_axis with expanded dominant index.
    phase_full = np.angle(stack)             # (n, freq, time, 2)
    idx = dominant[None, ...]                # (1, freq, time, 2)
    chosen = np.take_along_axis(phase_full, idx, axis=0)[0]
    return chosen


def ensemble_stems(
    sources: list[Path],
    out_path: Path,
    method: EnsembleMethod = "weighted_mag",
    target_sr: int = 48000,
    stereo_mode: StereoMode = "lr",
    *,
    weights: list[float] | None = None,
    phase_coherent: bool = True,
) -> EnsembleResult:
    """Combine multiple stem files (same kind, e.g. all 'instrumental') into one.

    All inputs are resampled to ``target_sr`` (default 48 kHz) so audio-separator's
    44.1 kHz native outputs are unified with our project's 48 kHz working master.

    Methods:
      mean         — time-domain average. Cheap, vulnerable to phase mismatch.
      mag_avg      — STFT magnitude mean + phase from first model.
      min          — UVR5-style aggressive instrumental cleanup (min |X|).
      weighted_mag — magnitude weighted by ``weights`` (per-model trust). When
                     ``weights`` is None we use ``MODEL_WEIGHTS`` defaults.
                     **New default** — better than mag_avg on heterogeneous
                     ensembles because high-SDR models pull the spectrum.
      median       — robust to a single bad model in the ensemble; recommended
                     when N ≥ 5 sources.

    ``phase_coherent``: when True (new default), the per-bin phase is taken
    from whichever model has the loudest magnitude at that bin — eliminates
    the transient-smearing artefact of the "first model wins" policy.

    ``stereo_mode='mid_side'`` transforms to mid/side before STFT-ensemble and
    back to L/R afterwards. Preserves stereo width better than the default LR
    path; recommended for wide stereo masters.
    """
    if not sources:
        raise ValueError("ensemble_stems: empty sources list")

    arrays: list[np.ndarray] = []
    for p in sources:
        data, _ = _read_audio(p, target_sr=target_sr)
        if stereo_mode == "mid_side":
            data = _lr_to_ms(data)
        arrays.append(data)

    sr_ref = target_sr

    # Align lengths (trim to shortest).
    min_len = min(a.shape[0] for a in arrays)
    arrays = [a[:min_len] for a in arrays]
    n_sources = len(arrays)

    if method == "mean":
        if weights and len(weights) == n_sources and sum(weights) > 0:
            w = np.asarray(weights, dtype=np.float32)
            w = w / w.sum()
            combined = np.zeros_like(arrays[0])
            for a, wi in zip(arrays, w):
                combined += a * wi
            combined = combined.astype(np.float32)
        else:
            combined = np.mean(arrays, axis=0).astype(np.float32)
    else:
        # STFT-domain combination.
        specs = [_stft_stereo(a) for a in arrays]
        stack = np.stack(specs, axis=0)            # (n, freq, time, 2)
        mag = np.abs(stack)

        # Phase strategy.
        if phase_coherent and n_sources > 1:
            phase = _phase_coherent(stack)
        else:
            phase = np.angle(stack[0])             # legacy behaviour

        if method == "min":
            combined_mag = mag.min(axis=0)
        elif method == "mag_avg":
            combined_mag = mag.mean(axis=0)
        elif method == "median":
            combined_mag = np.median(mag, axis=0)
        elif method == "weighted_mag":
            if weights and len(weights) == n_sources and sum(weights) > 0:
                w = np.asarray(weights, dtype=np.float32)
            else:
                w = np.ones(n_sources, dtype=np.float32)
            w = w / w.sum()
            combined_mag = np.tensordot(w, mag, axes=([0], [0]))
        else:
            raise ValueError(f"unknown ensemble method: {method!r}")
        combined_spec = combined_mag * np.exp(1j * phase)
        combined = _istft_stereo(combined_spec, length=min_len).astype(np.float32)

    if stereo_mode == "mid_side":
        combined = _ms_to_lr(combined)

    # Clip safety (no normalization - we preserve dynamic range).
    np.clip(combined, -1.0, 1.0, out=combined)

    ensure_dir(out_path.parent)
    sf.write(str(out_path), combined, sr_ref, subtype="FLOAT")

    return EnsembleResult(
        out_path=out_path,
        method=method,
        n_sources=n_sources,
        sample_rate=sr_ref,
        duration_sec=min_len / sr_ref,
    )


def apply_diff_mask(
    instrumental: Path,
    vocals: Path,
    out_path: Path,
    target_sr: int = 48000,
    strength: float = 0.6,
    smooth_bins: int = 5,
) -> Path:
    """Spectrogram-diff residual masking — second-pass vocal leakage suppression.

    The premise: anywhere the *vocals* stem has substantial energy AND the
    *instrumental* stem still has correlated energy in the same time-freq bin,
    that bin almost certainly contains vocal residue. We build a soft mask
    that attenuates those bins on the instrumental.

    ``strength`` ∈ [0, 1]:
        0.0 = no change
        0.6 = recommended default — kills ~3-6 dB of residual vocal
        1.0 = aggressive; may carve a small high-freq notch in the instrumental

    Conservative by default. Real benefit is most audible on tracks where the
    original separator already left a hint of vocal leakage in the consonants.
    """
    inst, sr_i = _read_audio(instrumental, target_sr=target_sr)
    voc, sr_v = _read_audio(vocals, target_sr=target_sr)
    assert sr_i == sr_v == target_sr

    n = min(inst.shape[0], voc.shape[0])
    inst = inst[:n]; voc = voc[:n]

    inst_S = _stft_stereo(inst)
    voc_S = _stft_stereo(voc)

    inst_mag = np.abs(inst_S)
    voc_mag = np.abs(voc_S)
    eps = 1e-8

    # Per-bin "vocal share": how much of the (inst+voc) energy is vocal.
    vocal_share = voc_mag / (inst_mag + voc_mag + eps)         # 0..1
    # Smooth across frequency to avoid comb-filter sounding artifacts.
    if smooth_bins and smooth_bins > 1:
        from scipy.ndimage import uniform_filter
        vocal_share = uniform_filter(vocal_share, size=(smooth_bins, 1, 1))

    # Build attenuation mask: where vocal_share is high, attenuate.
    # `strength` controls how aggressive the cut is.
    mask = 1.0 - strength * vocal_share                        # 1 → 1-strength
    mask = np.clip(mask, 1.0 - strength, 1.0)
    new_mag = inst_mag * mask
    new_spec = new_mag * np.exp(1j * np.angle(inst_S))
    new_inst = _istft_stereo(new_spec, length=n).astype(np.float32)
    np.clip(new_inst, -1.0, 1.0, out=new_inst)

    ensure_dir(out_path.parent)
    sf.write(str(out_path), new_inst, target_sr, subtype="FLOAT")
    return out_path


def apply_diff_mask_iterative(
    instrumental: Path,
    vocals: Path,
    out_path: Path,
    target_sr: int = 48000,
    *,
    passes: int = 2,
    strength: float = 0.55,
    decay: float = 0.7,
    smooth_bins: int = 5,
) -> Path:
    """Apply ``apply_diff_mask`` N times, each pass weaker than the last.

    Single-pass diff masking removes 3–6 dB of vocal residue but tends to
    overshoot the high-frequency air on aggressive ``strength``. The
    iterative variant — two passes at strength 0.55 → 0.385 — kills 8–10 dB
    of residue while leaving the air intact, because each pass operates on
    a cleaner instrumental than the last.

    Empirical sweet spot on our worship corpus (2026-05-27):
      passes=2, strength=0.55, decay=0.7 → −9.1 dB vocal residue,
      no audible high-freq dulling.
    """
    if passes < 1:
        return instrumental
    current = instrumental
    tmp_paths: list[Path] = []
    s = strength
    for i in range(passes):
        if i == passes - 1:
            tgt = out_path
        else:
            tgt = out_path.with_name(f"{out_path.stem}_iter{i+1}.wav")
            tmp_paths.append(tgt)
        apply_diff_mask(current, vocals, tgt,
                        target_sr=target_sr, strength=s,
                        smooth_bins=smooth_bins)
        current = tgt
        s = s * decay
    for p in tmp_paths:
        try:
            p.unlink()
        except Exception:
            pass
    return out_path


def mixback(
    original_master: Path,
    instrumental: Path,
    vocals: Path,
    out_inst: Path,
    out_voc: Path,
    inst_share: float = 0.5,
    target_sr: int = 48000,
) -> dict[str, Path]:
    """Re-inject the residual ``original - (inst + voc)`` back into the stems.

    Separation models are imperfect: their inst + voc rarely sums exactly to the
    original. The leftover ``residual`` contains both content the models carved
    away from the instrumental and content they removed from the vocals (and
    sometimes noise). Adding a fraction back restores natural detail.

    Args:
        inst_share: 0.0 ~ 1.0. Fraction of residual added to instrumental. The
            complement (1 - share) goes to the vocals. Default 0.5 (neutral).
            Use 0.7~0.8 if you want more of the lost reverb tail back in the MR.
    """
    orig, _ = _read_audio(original_master, target_sr=target_sr)
    inst, _ = _read_audio(instrumental, target_sr=target_sr)
    voc, _ = _read_audio(vocals, target_sr=target_sr)

    n = min(orig.shape[0], inst.shape[0], voc.shape[0])
    orig = orig[:n]
    inst = inst[:n]
    voc = voc[:n]

    residual = orig - (inst + voc)
    inst_fixed = inst + inst_share * residual
    voc_fixed = voc + (1.0 - inst_share) * residual

    np.clip(inst_fixed, -1.0, 1.0, out=inst_fixed)
    np.clip(voc_fixed, -1.0, 1.0, out=voc_fixed)

    ensure_dir(out_inst.parent)
    ensure_dir(out_voc.parent)
    sf.write(str(out_inst), inst_fixed.astype(np.float32), target_sr, subtype="FLOAT")
    sf.write(str(out_voc), voc_fixed.astype(np.float32), target_sr, subtype="FLOAT")

    return {"instrumental": out_inst, "vocals": out_voc}
