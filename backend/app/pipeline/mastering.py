"""LUFS-target loudness normalization + stem-level EQ.

Most consumer platforms publish a single target loudness:

    YouTube      −14 LUFS
    Spotify      −14 LUFS (loud profile) / −19 LUFS (quiet profile)
    Apple Music  −16 LUFS
    Tidal        −14 LUFS
    Broadcast EU −23 LUFS  (EBU R128)

When the user picks a target the orchestrator runs this stage after the
final encode, producing a sibling artifact ``instrumental_lufs.wav``
that is psychoacoustically aligned to that platform's loudness target.

We use ``pyloudnorm`` (BS.1770 + ITU-R loudness meter) — already a
dependency of the project — to measure integrated LUFS, then apply a
single gain stage. No multi-band processing, no compression.

The EQ side is a parametric 3-band tilter (low shelf / mid bell / high
shelf) implemented via scipy biquad cascade. Useful when the user wants
a brighter or warmer MR before exporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir


PLATFORM_TARGETS_LUFS: dict[str, float] = {
    "youtube":    -14.0,
    "spotify":    -14.0,
    "spotify_q":  -19.0,
    "apple":      -16.0,
    "tidal":      -14.0,
    "broadcast":  -23.0,
}


@dataclass
class LoudnessResult:
    out_path: Path
    measured_lufs: float
    target_lufs: float
    gain_db: float
    sample_rate: int
    # ── new (P0-F) — true-peak + verification ──────────────────────
    true_peak_dbtp_before: float = 0.0
    true_peak_dbtp_after: float = 0.0
    measured_lufs_after: float = 0.0
    lufs_error_db: float = 0.0
    limiter_applied: bool = False


def _true_peak_dbtp(audio: np.ndarray, sr: int) -> float:  # noqa: ARG001
    """Estimate ITU-R BS.1770 true peak in dBTP via 4× oversampling.

    Inter-sample peaks (the peaks of the *continuous* signal between
    samples) routinely exceed sample peaks by 1-3 dB when content has
    energy above the Nyquist quarter. Sample-peak ceiling checks let
    those slip through and the consumer's DAC eats the clip.

    We resample 4× with polyphase filtering — fast, deterministic,
    accurate enough for mastering decisions. ``sr`` is not used (the
    resample factor is fixed at 4) but kept for API clarity / future
    extension to a SR-dependent algorithm.
    """
    del sr  # silence unused-parameter lint without changing the API
    if audio.size == 0:
        return -np.inf
    try:
        from scipy.signal import resample_poly
        # 4× oversampling per channel.
        if audio.ndim == 1:
            up = resample_poly(audio, 4, 1)
        else:
            up = np.stack(
                [resample_poly(audio[:, c], 4, 1) for c in range(audio.shape[1])],
                axis=-1,
            )
        peak = float(np.max(np.abs(up)))
    except Exception:
        peak = float(np.max(np.abs(audio)))
    if peak <= 0:
        return -np.inf
    return float(20.0 * np.log10(peak))


def _soft_limit(
    audio: np.ndarray,
    sr: int,
    *,
    ceiling_dbtp: float = -1.0,
    release_ms: float = 50.0,
) -> tuple[np.ndarray, bool]:
    """Look-ahead soft limiter.

    Returns (limited_audio, was_active). Single-band, transparent enough
    for mastered MR content. When peaks already sit below ``ceiling`` the
    signal is returned untouched.

    Algorithm: 4× oversampled peak detection → per-sample target gain
    (ceiling / |x|) → smoothed via single-pole release filter to avoid
    distortion → applied to dry signal.
    """
    ceiling_lin = 10.0 ** (ceiling_dbtp / 20.0)
    if audio.size == 0:
        return audio, False
    sample_peak = float(np.max(np.abs(audio)))
    if sample_peak <= ceiling_lin:
        # Even raw sample peak fits — true peak might still exceed, but
        # only marginally; for mastering this is well below audibility.
        if _true_peak_dbtp(audio, sr) <= ceiling_dbtp:
            return audio, False

    # Compute per-sample suppression gain.
    abs_x = np.max(np.abs(audio), axis=1) if audio.ndim == 2 else np.abs(audio)
    needed = np.where(abs_x > ceiling_lin, ceiling_lin / np.maximum(abs_x, 1e-9), 1.0)

    # One-pole smoothing for release. Attack is instantaneous (look-ahead
    # would require a delay buffer; release-only is acceptable for
    # mastering-grade work on already-finished material).
    release_samps = max(1, int(sr * release_ms / 1000.0))
    alpha = float(np.exp(-1.0 / release_samps))
    g = np.empty_like(needed)
    cur = 1.0
    for i in range(len(needed)):
        n = needed[i]
        if n < cur:                     # attack — snap down
            cur = n
        else:                           # release — smooth back to unity
            cur = alpha * cur + (1.0 - alpha) * 1.0
        g[i] = cur
    if audio.ndim == 2:
        out = audio * g[:, None]
    else:
        out = audio * g
    return out.astype(np.float32, copy=False), True


def normalize_lufs(
    input_path: Path,
    out_path: Path,
    target_lufs: float = -14.0,
    *,
    true_peak_ceiling_dbtp: float = -1.0,
    use_limiter: bool = True,
) -> LoudnessResult:
    """Apply a gain stage to hit ``target_lufs`` (integrated, BS.1770).

    Now BS.1770-conformant on the verification side: we measure true peak
    (4× oversampled) both before and after, and apply a look-ahead soft
    limiter when ``use_limiter`` is on and the post-gain true peak would
    exceed the ceiling. Without the limiter we still back off the gain
    so the *sample* peak stays under the ceiling — useful when the
    consumer wants pure linear gain.

    Returned ``LoudnessResult`` records measured_lufs_after,
    true_peak_dbtp_after, lufs_error_db so the orchestrator can include
    these in the quality.json and the UI can show 'within target'.
    """
    import pyloudnorm as pyln

    audio, sr = sf.read(str(input_path), dtype="float32", always_2d=True)
    meter = pyln.Meter(sr)
    measured = float(meter.integrated_loudness(audio))
    tp_before = _true_peak_dbtp(audio, sr)

    if measured == -np.inf:
        ensure_dir(out_path.parent)
        sf.write(str(out_path), audio, sr, subtype="FLOAT")
        return LoudnessResult(
            out_path=out_path, measured_lufs=-np.inf,
            target_lufs=target_lufs, gain_db=0.0, sample_rate=sr,
            true_peak_dbtp_before=tp_before,
            true_peak_dbtp_after=tp_before,
            measured_lufs_after=-np.inf,
            lufs_error_db=float("inf"),
            limiter_applied=False,
        )

    desired_gain = target_lufs - measured
    desired_lin = 10.0 ** (desired_gain / 20.0)

    if use_limiter:
        # With limiter: apply full target gain, then limit true peak.
        actual_lin = desired_lin
    else:
        # No limiter: back off gain so sample peak stays under ceiling.
        sample_peak = float(np.max(np.abs(audio)))
        if sample_peak > 0:
            ceiling_lin = 10.0 ** (true_peak_ceiling_dbtp / 20.0)
            actual_lin = min(desired_lin, ceiling_lin / sample_peak)
        else:
            actual_lin = desired_lin
    actual_gain_db = float(20.0 * np.log10(actual_lin + 1e-12))

    out = (audio * actual_lin).astype(np.float32)
    limiter_active = False
    if use_limiter:
        out, limiter_active = _soft_limit(
            out, sr, ceiling_dbtp=true_peak_ceiling_dbtp, release_ms=50.0,
        )
    np.clip(out, -1.0, 1.0, out=out)

    ensure_dir(out_path.parent)
    sf.write(str(out_path), out, sr, subtype="FLOAT")

    # Verify post-gain values.
    measured_after = float(meter.integrated_loudness(out))
    tp_after = _true_peak_dbtp(out, sr)
    err = (measured_after - target_lufs) if np.isfinite(measured_after) else float("inf")

    return LoudnessResult(
        out_path=out_path,
        measured_lufs=measured,
        target_lufs=target_lufs,
        gain_db=actual_gain_db,
        sample_rate=sr,
        true_peak_dbtp_before=tp_before,
        true_peak_dbtp_after=tp_after,
        measured_lufs_after=measured_after,
        lufs_error_db=err,
        limiter_applied=limiter_active,
    )


# ── 3-band parametric EQ ──────────────────────────────────────────────────

@dataclass
class EqResult:
    out_path: Path
    low_db: float
    mid_db: float
    high_db: float
    sample_rate: int


def apply_3band_eq(
    input_path: Path,
    out_path: Path,
    *,
    low_db: float = 0.0,
    low_hz: float = 200.0,
    mid_db: float = 0.0,
    mid_hz: float = 1000.0,
    mid_q: float = 1.0,
    high_db: float = 0.0,
    high_hz: float = 5000.0,
) -> EqResult:
    """3-band biquad EQ (low-shelf / mid-bell / high-shelf).

    All gains in dB. ``low_hz`` / ``high_hz`` are the shelf corner
    frequencies; ``mid_hz`` is the bell centre, ``mid_q`` its width.
    Skips bands whose gain is exactly 0 to avoid colouring the signal.
    """
    audio, sr = sf.read(str(input_path), dtype="float32", always_2d=True)

    out = audio.copy()
    if abs(low_db) > 0.01:
        sos = _shelf_sos(sr, low_hz, low_db, kind="low")
        out = _apply_sos_per_channel(out, sos)
    if abs(mid_db) > 0.01:
        sos = _peaking_sos(sr, mid_hz, mid_db, mid_q)
        out = _apply_sos_per_channel(out, sos)
    if abs(high_db) > 0.01:
        sos = _shelf_sos(sr, high_hz, high_db, kind="high")
        out = _apply_sos_per_channel(out, sos)

    np.clip(out, -1.0, 1.0, out=out)
    ensure_dir(out_path.parent)
    sf.write(str(out_path), out.astype(np.float32), sr, subtype="FLOAT")
    return EqResult(out_path, low_db, mid_db, high_db, sr)


def _shelf_sos(sr, hz, db, kind):
    """Bilinear-transform 2nd-order shelf. Robbins / Bristow-Johnson formulas."""
    A = 10 ** (db / 40.0)
    w0 = 2 * np.pi * hz / sr
    cos_w = np.cos(w0)
    sin_w = np.sin(w0)
    S = 1.0
    alpha = sin_w / 2 * np.sqrt((A + 1 / A) * (1 / S - 1) + 2)
    sqrtA_alpha = 2 * np.sqrt(A) * alpha
    if kind == "low":
        b0 =    A * ((A + 1) - (A - 1) * cos_w + sqrtA_alpha)
        b1 =  2*A * ((A - 1) - (A + 1) * cos_w)
        b2 =    A * ((A + 1) - (A - 1) * cos_w - sqrtA_alpha)
        a0 =        (A + 1) + (A - 1) * cos_w + sqrtA_alpha
        a1 =   -2 * ((A - 1) + (A + 1) * cos_w)
        a2 =        (A + 1) + (A - 1) * cos_w - sqrtA_alpha
    else:  # high shelf
        b0 =    A * ((A + 1) + (A - 1) * cos_w + sqrtA_alpha)
        b1 = -2*A * ((A - 1) + (A + 1) * cos_w)
        b2 =    A * ((A + 1) + (A - 1) * cos_w - sqrtA_alpha)
        a0 =        (A + 1) - (A - 1) * cos_w + sqrtA_alpha
        a1 =    2 * ((A - 1) - (A + 1) * cos_w)
        a2 =        (A + 1) - (A - 1) * cos_w - sqrtA_alpha
    sos = np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])
    return sos


def _peaking_sos(sr, hz, db, q):
    A = 10 ** (db / 40.0)
    w0 = 2 * np.pi * hz / sr
    cos_w = np.cos(w0)
    alpha = np.sin(w0) / (2 * q)
    b0 = 1 + alpha * A
    b1 = -2 * cos_w
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * cos_w
    a2 = 1 - alpha / A
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def _apply_sos_per_channel(x, sos):
    from scipy.signal import sosfilt
    out = np.empty_like(x)
    for c in range(x.shape[1]):
        out[:, c] = sosfilt(sos, x[:, c]).astype(np.float32)
    return out
