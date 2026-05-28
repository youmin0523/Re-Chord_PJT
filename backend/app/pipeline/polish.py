"""Post-processing polish for the final instrumental stem.

After separation + ensemble + karaoke cleanup, the instrumental often shows
two annoying artifacts:

  1) "Compression / ducking": short-term loudness dips where vocals used
     to be, because the mask removed not just the vocal but a sliver of
     surrounding ambience too.
  2) "Dry holes": the room/reverb tail that lived with the vocal is gone,
     so the part of the song without vocals feels noticeably drier.

This stage applies two surgical fixes:

  A. Light mixback (default inst_share=0.20): adds 20% of the residual
     ``original - (inst + voc)`` back onto the instrumental. That residual
     is mostly the missing ambience/tail, so it restores naturalness
     without flooding the stem with leaked vocal energy.

  B. dynaudnorm (ffmpeg): a perceptual short-term loudness normalizer
     that gently lifts quiet sections (where vocals were ducked out) so
     the overall envelope reads as one consistent track again.

Both steps preserve dynamic range — this is *not* a maximizer.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir


@dataclass
class PolishResult:
    out_path: Path
    inst_share: float
    used_mixback: bool
    used_dynaudnorm: bool
    sample_rate: int


def _read_stereo(path: Path, target_sr: int) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    if sr != target_sr:
        import librosa
        data = np.stack(
            [librosa.resample(data[:, c], orig_sr=sr, target_sr=target_sr,
                              res_type="soxr_hq")
             for c in range(data.shape[1])],
            axis=-1,
        ).astype(np.float32)
    return data


def _light_mixback(
    original_master: Path,
    instrumental: Path,
    vocals: Path,
    out_path: Path,
    inst_share: float = 0.20,
    target_sr: int = 48000,
    *,
    band_limited: bool = False,
    band_lo_hz: float = 200.0,
    band_hi_hz: float = 4000.0,
) -> Path:
    """Mixback residual ambience back into the instrumental.

    Default (broadband): adds ``inst_share`` of (original - inst - voc) back.

    ``band_limited=True`` (BEHM — Band-Envelope Hybrid Mixback): only mixes
    back the residual energy inside ``[band_lo_hz, band_hi_hz]`` (typically
    200 Hz–4 kHz, the vocal-formant band where ducking artifacts cluster).
    The bass and air are kept dry, so vocal leakage stays out of those
    frequency regions even at higher mixback ratios.
    """
    orig = _read_stereo(original_master, target_sr)
    inst = _read_stereo(instrumental, target_sr)
    voc = _read_stereo(vocals, target_sr)
    n = min(orig.shape[0], inst.shape[0], voc.shape[0])
    orig = orig[:n]; inst = inst[:n]; voc = voc[:n]
    residual = orig - (inst + voc)

    if band_limited:
        residual = _bandpass(residual, target_sr, band_lo_hz, band_hi_hz)

    out = inst + inst_share * residual
    np.clip(out, -1.0, 1.0, out=out)
    ensure_dir(out_path.parent)
    sf.write(str(out_path), out.astype(np.float32), target_sr, subtype="FLOAT")
    return out_path


def _bandpass(x: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    """Zero-phase 4th-order Butterworth bandpass on each channel."""
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2.0
    lo_n = max(1e-4, min(0.999, lo / nyq))
    hi_n = max(lo_n + 1e-4, min(0.999, hi / nyq))
    sos = butter(4, [lo_n, hi_n], btype="bandpass", output="sos")
    out = np.empty_like(x)
    for c in range(x.shape[1]):
        out[:, c] = sosfiltfilt(sos, x[:, c]).astype(np.float32)
    return out


def restore_reverb_tail(
    original_master: Path,
    instrumental: Path,
    vocals: Path,
    out_path: Path,
    target_sr: int = 48000,
    *,
    tail_share: float = 0.25,
    attack_ms: float = 50.0,
    release_ms: float = 600.0,
    hp_hz: float = 500.0,
) -> Path:
    """Restore the reverb tail that disappeared with the vocal stem.

    Premise:
      residual = original − (inst + voc)
    The residual is dominated by the long-decaying ambience the separator
    misclassified as vocal. We:

    1. High-pass the residual above ``hp_hz`` so we don't add boomy bass back.
    2. Apply an envelope follower with slow attack + slow release — the
       envelope tracks long-decaying reverb tail energy and rejects sharp
       phoneme transients.
    3. Add ``tail_share`` × (residual × envelope) onto the instrumental.

    The envelope multiplication is the key trick: phoneme content (fast
    on/off) gets suppressed because the slow attack can't catch up to it;
    reverb tail (slowly decaying) gets through cleanly. Effectively we're
    re-injecting the *temporal shape* of the missing ambience without
    re-injecting the words.
    """
    orig = _read_stereo(original_master, target_sr)
    inst = _read_stereo(instrumental, target_sr)
    voc = _read_stereo(vocals, target_sr)

    n = min(orig.shape[0], inst.shape[0], voc.shape[0])
    orig = orig[:n]; inst = inst[:n]; voc = voc[:n]
    residual = orig - (inst + voc)

    # 1) Drop the boomy band — reverb tails we care about start ~500 Hz.
    residual = _bandpass(residual, target_sr, hp_hz, target_sr / 2 - 500)

    # 2) Envelope follower (one-pole attack / release on the absolute value).
    rect = np.abs(residual)
    attack = np.exp(-1.0 / max(1, int(target_sr * attack_ms / 1000)))
    release = np.exp(-1.0 / max(1, int(target_sr * release_ms / 1000)))
    env = np.zeros_like(rect)
    prev_l = 0.0
    prev_r = 0.0
    for i in range(rect.shape[0]):
        l = rect[i, 0]
        r = rect[i, 1]
        coef_l = attack if l > prev_l else release
        coef_r = attack if r > prev_r else release
        prev_l = coef_l * prev_l + (1 - coef_l) * l
        prev_r = coef_r * prev_r + (1 - coef_r) * r
        env[i, 0] = prev_l
        env[i, 1] = prev_r

    # Normalise envelope so the multiplier is in [0..1].
    env_max = float(env.max() + 1e-8)
    env_n = env / env_max

    # 3) Mix the envelope-shaped residual back onto the instrumental.
    out = inst + tail_share * (residual * env_n)
    np.clip(out, -1.0, 1.0, out=out)
    ensure_dir(out_path.parent)
    sf.write(str(out_path), out.astype(np.float32), target_sr, subtype="FLOAT")
    return out_path


def _dynaudnorm(
    input_path: Path,
    out_path: Path,
    target_sr: int = 48000,
    # Gentle settings: short ramp, modest target, modest peak.
    frame_len_ms: int = 500,
    gauss_size: int = 31,
    peak: float = 0.97,
    target_rms: float = 0.10,
) -> Path | None:
    """Apply ffmpeg's dynaudnorm with conservative settings.

    f=frame length in samples — must be 10..8000. We approximate from sr.
    g=Gaussian filter size (odd). p=peak. r=RMS target ∈ (0, 1]. m=max gain
    (limits how much quiet parts get boosted). s=compress factor — keep
    low so we don't smash dynamics.
    """
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    frame_len_samples = max(10, min(8000, int(target_sr * frame_len_ms / 1000)))
    rms_clamped = max(0.0, min(1.0, target_rms))
    af = (
        "aresample=resampler=soxr:precision=28:osr="
        f"{target_sr},dynaudnorm=f={frame_len_samples}:g={gauss_size}:"
        f"p={peak}:r={rms_clamped}:m=8.0:s=2.0:n=1"
    )
    ensure_dir(out_path.parent)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    cmd = [
        exe, "-y",
        "-i", str(input_path),
        "-vn", "-map_metadata", "-1",
        "-af", af,
        "-c:a", "pcm_f32le",
        "-f", "wav",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        return None
    tmp.replace(out_path)
    return out_path


def polish_instrumental(
    original_master: Path,
    instrumental: Path,
    vocals: Path,
    out_dir: Path,
    inst_share: float = 0.20,
    do_mixback: bool = True,
    do_dynaudnorm: bool = True,
    target_sr: int = 48000,
    *,
    band_limited_mixback: bool = False,
    band_lo_hz: float = 200.0,
    band_hi_hz: float = 4000.0,
    do_reverb_tail: bool = False,
    reverb_tail_share: float = 0.25,
) -> PolishResult:
    """Apply the (reverb-tail restore + mixback + dynaudnorm) polish pipeline.

    Set ``do_reverb_tail=True`` to invoke ``restore_reverb_tail`` BEFORE the
    light mixback step — restores the long-decaying ambience that was lost
    with the vocal stem, without re-injecting vocal phonemes. The two
    stages compose: tail restoration adds ambience, mixback adds the rest
    of the missing residual, dynaudnorm flattens the envelope.

    Set ``band_limited_mixback=True`` to use BEHM (Band-Envelope Hybrid
    Mixback) — restricts residual mixback to the vocal-formant band so
    vocal leakage stays out of bass/air even at higher ``inst_share``.
    """
    ensure_dir(out_dir)
    current = instrumental
    used_mb = False
    used_dn = False

    if do_reverb_tail:
        try:
            rt_path = out_dir / "polished_reverb.wav"
            restore_reverb_tail(
                original_master, current, vocals, rt_path,
                target_sr=target_sr,
                tail_share=reverb_tail_share,
            )
            current = rt_path
        except Exception:
            # Reverb-tail is a polish-of-polish; never break the chain.
            pass

    if do_mixback:
        mb_path = out_dir / "polished_mb.wav"
        _light_mixback(
            original_master, current, vocals, mb_path,
            inst_share=inst_share, target_sr=target_sr,
            band_limited=band_limited_mixback,
            band_lo_hz=band_lo_hz, band_hi_hz=band_hi_hz,
        )
        current = mb_path
        used_mb = True

    if do_dynaudnorm:
        dn_path = out_dir / "polished.wav"
        res = _dynaudnorm(current, dn_path, target_sr=target_sr)
        if res is not None:
            current = dn_path
            used_dn = True

    return PolishResult(
        out_path=current,
        inst_share=inst_share if used_mb else 0.0,
        used_mixback=used_mb,
        used_dynaudnorm=used_dn,
        sample_rate=target_sr,
    )
