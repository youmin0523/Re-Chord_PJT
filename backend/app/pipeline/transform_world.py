"""WORLD-vocoder pitch shifting for vocal stems.

Rubber Band's R3 finer engine is industry-grade up to about ±5 semitones,
after which it audibly thins the vocal timbre. The WORLD vocoder
(Morise 2016, MIT licensed via the ``pyworld`` package) decomposes
speech / singing into three independent components:

    F0          — fundamental frequency over time
    spectral    — vocal-tract resonance envelope (formants)
    aperiodic   — breathy / unvoiced energy

Shifting only F0 while keeping the spectral envelope intact gives a
*formant-preserved* pitch shift. The result is noticeably more natural
than Rubber Band at ±7-12 semitones — the singer sounds like they're
hitting a different note rather than like a chipmunk / Darth Vader.

Tradeoffs:
    + Up to ~+12 / −12 semitone shifts sound musical
    + Mono-only intermediate (we apply per-channel for stereo)
    × ~1.5-3× slower than Rubber Band on the same audio
    × Slight buzz on very breathy / hissy phonemes

Activation: the dispatcher in ``transform.py`` routes vocal stems with
|semitones| > 5 to this backend automatically; everything else stays on
Rubber Band.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class WorldTransformResult:
    out_path: Path
    semitones: float
    tempo_ratio: float
    elapsed_sec: float


def is_available() -> bool:
    try:
        import pyworld  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def transform_vocal(
    input_path: Path,
    out_path: Path,
    semitones: float,
    tempo_ratio: float = 1.0,
    *,
    sample_rate_target: int = 48000,
) -> WorldTransformResult:
    """Shift pitch (and optionally tempo) of a vocal stem via WORLD.

    Tempo is achieved by resampling the synthesised waveform; for
    musically-useful tempo + pitch combinations the result is
    indistinguishable from Rubber Band but the pitch quality is better
    at large shifts.
    """
    try:
        import pyworld as pw  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "pyworld not installed. Run: uv pip install pyworld"
        ) from e

    t0 = time.perf_counter()

    audio, sr = sf.read(str(input_path), dtype="float32", always_2d=True)
    if audio.shape[1] > 2:
        audio = audio[:, :2]
    # WORLD processes mono signals at 16-bit-double precision. We keep the
    # full-rate input and process each channel independently to retain
    # stereo width.
    if sr != sample_rate_target:
        # Resample first so the output sr is consistent with the rest of
        # the pipeline; quality stays high via soxr.
        import librosa
        audio = np.stack(
            [librosa.resample(audio[:, c], orig_sr=sr, target_sr=sample_rate_target,
                              res_type="soxr_hq")
             for c in range(audio.shape[1])],
            axis=-1,
        ).astype(np.float32)
        sr = sample_rate_target

    f0_ratio = 2.0 ** (semitones / 12.0)

    out_channels = []
    for c in range(audio.shape[1]):
        x = audio[:, c].astype(np.float64)
        # WORLD analysis. Default frame_period=5ms gives high quality.
        f0, t = pw.dio(x, sr, frame_period=5.0)
        f0 = pw.stonemask(x, f0, t, sr)
        sp = pw.cheaptrick(x, f0, t, sr)
        ap = pw.d4c(x, f0, t, sr)
        # Shift F0; spectral envelope stays put → formants preserved.
        f0_shifted = f0 * f0_ratio
        y = pw.synthesize(f0_shifted, sp, ap, sr, frame_period=5.0)
        out_channels.append(y.astype(np.float32))

    out = np.stack(out_channels, axis=-1)

    # Tempo: resample-then-restore-pitch. WORLD already shifted the pitch,
    # so a plain librosa.effects.time_stretch on the synthesised signal
    # gives a clean tempo change. We use it only when needed.
    if abs(tempo_ratio - 1.0) > 1e-4:
        import librosa
        stretched = np.stack(
            [librosa.effects.time_stretch(out[:, c], rate=tempo_ratio)
             for c in range(out.shape[1])],
            axis=-1,
        ).astype(np.float32)
        out = stretched

    # Clip safety; we never normalise.
    np.clip(out, -1.0, 1.0, out=out)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), out, sr, subtype="FLOAT")

    return WorldTransformResult(
        out_path=out_path,
        semitones=float(semitones),
        tempo_ratio=float(tempo_ratio),
        elapsed_sec=time.perf_counter() - t0,
    )
