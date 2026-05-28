"""Spectral envelope matching ("tone match") for stem mixdowns.

When users build a custom mixdown by excluding a stem (e.g. "no electric
guitar"), the result loses the spectral energy that stem was carrying.
The remaining mix sounds mid-scooped / muddy because every separator
inevitably routes some part of the room reverb / sub-bass / air into a
single stem, and removing that stem takes the energy with it.

``eq_match_to_reference`` corrects this by:

  1. Estimating a long-term magnitude spectrum for both the target
     mixdown and the original full mix (one value per FFT freq bin,
     averaged over the whole track).
  2. Computing a per-bin ratio ``ref / target`` — this is the EQ curve
     that would turn target's tone back into the original's.
  3. Smoothing the curve across neighbouring bins so we apply a tonal
     correction, not a per-note notch filter.
  4. Capping the boost (default ±6 dB) so we don't amplify the noise
     floor or runaway peaks where target has near-silence.
  5. Re-rendering the target via STFT/iSTFT with the curve applied as a
     time-invariant gain per bin.

This is **not** a magic "remove all bleed" filter — it can't put back
spectral content that the separator threw away. What it does is restore
the *overall* tonal balance so the excluded-stem mixdown doesn't sound
muddy or mid-scooped compared to the source.
"""

from __future__ import annotations

import numpy as np


def _to_mono(stereo: np.ndarray) -> np.ndarray:
    if stereo.ndim == 1:
        return stereo
    return stereo.mean(axis=1).astype(np.float32)


def _spectral_envelope(audio: np.ndarray, sr: int, n_fft: int) -> np.ndarray:
    """Long-term magnitude spectrum, averaged over all frames."""
    import librosa
    mono = _to_mono(audio)
    S = np.abs(librosa.stft(mono, n_fft=n_fft, hop_length=n_fft // 4))
    return S.mean(axis=1).astype(np.float32)


def eq_match_to_reference(
    target: np.ndarray,
    reference: np.ndarray,
    sr: int,
    *,
    n_fft: int = 4096,
    smoothing_bins: int = 9,
    boost_cap_db: float = 6.0,
) -> np.ndarray:
    """Apply a frequency-dependent gain curve to ``target`` so its long-term
    magnitude spectrum approaches ``reference``.

    Args:
        target:      mixdown audio, shape (samples, channels) — modified.
        reference:   source mix audio, shape (samples, channels) — read-only.
        sr:          sample rate (target and reference must already match).
        n_fft:       STFT window size; 4096 ≈ 11 Hz bin resolution @ 48 kHz.
        smoothing_bins:  Moving-average width across freq bins. Higher =
                     smoother (more tonal, less surgical).
        boost_cap_db:  Hard cap on per-bin boost / cut (±dB). Prevents
                     pumping up the noise floor where target is silent.

    Returns:
        Float32 ndarray of the same shape as ``target``.
    """
    if target.ndim == 1:
        target = target[:, None]
    if reference.ndim == 1:
        reference = reference[:, None]

    import librosa

    target_env = _spectral_envelope(target, sr, n_fft)
    ref_env = _spectral_envelope(reference, sr, n_fft)

    eps = 1e-7
    ratio = (ref_env + eps) / (target_env + eps)

    if smoothing_bins > 1:
        kernel = np.ones(smoothing_bins, dtype=np.float32) / float(smoothing_bins)
        ratio = np.convolve(ratio, kernel, mode="same")

    cap_lin = 10.0 ** (boost_cap_db / 20.0)
    ratio = np.clip(ratio, 1.0 / cap_lin, cap_lin).astype(np.float32)

    hop = n_fft // 4
    out = np.zeros_like(target, dtype=np.float32)
    for c in range(target.shape[1]):
        S = librosa.stft(target[:, c], n_fft=n_fft, hop_length=hop)
        S = S * ratio[:, None]
        rendered = librosa.istft(S, hop_length=hop, length=target.shape[0])
        out[:, c] = rendered.astype(np.float32)

    return out
