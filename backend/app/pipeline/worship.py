"""WORSHIP-mode helpers — pedal-tone synthesis + intro/outro extension.

Worship-team workflows need a few specific transformations the generic
MR pipeline doesn't cover out-of-box:

  1. **Pedal-tone synthesis** — generate a sustained tonic pad in a
     given key, useful as an interlude between songs, or as a "modulation
     pad" when keys jump.
  2. **Intro/outro extension** — extend an existing intro or outro by N
     bars by looping a chord-aware segment. Handy for prayer / ambient
     transitions.
  3. **Auto-segue** — render a smooth crossfade + pedal-tone bridge
     between two song MRs in different keys.

All synthesis is done with pyworld-quality additive sines + filtered
noise, so the output sits well behind a vocal without competing for the
phoneme band. We deliberately keep the tone simple (sine + filtered
noise) rather than sampled pads — the latter would be ~20 MB of
samples we'd have to ship.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir


PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class PedalToneResult:
    out_path: Path
    duration_sec: float
    sample_rate: int
    key_root: str
    mode: str


def _pc_freq(name: str, octave: int = 3) -> float:
    """Return Hz for a pitch-class name + octave (A4=440)."""
    idx = PITCH_CLASSES.index(name) if name in PITCH_CLASSES else 0
    midi = 12 * (octave + 1) + idx           # C-1=0 convention
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def synthesize_pedal_tone(
    out_path: Path,
    key_root: str,
    mode: str = "major",
    *,
    duration_sec: float = 16.0,
    sample_rate: int = 48000,
    target_lufs: float = -20.0,
) -> PedalToneResult:
    """Render a sustained, warm pedal-tone pad in the given key.

    The pad layers: root (3rd octave), root (4th octave), 5th (3rd octave),
    and a band-limited noise wash for air. We add slow random LFO to the
    partials so the result breathes; an exponential fade-in / fade-out
    prevents clicks.
    """
    n_samples = int(duration_sec * sample_rate)
    t = np.arange(n_samples) / sample_rate
    root_freq_low  = _pc_freq(key_root, octave=2)
    root_freq_mid  = _pc_freq(key_root, octave=3)
    fifth_freq     = root_freq_mid * (3.0 / 2.0)
    # Third — major or minor depending on mode.
    third_ratio = 5.0 / 4.0 if not mode.startswith("min") else 6.0 / 5.0
    third_freq  = root_freq_mid * third_ratio

    # Slow breath LFO (0.18 Hz vibrato on amplitude).
    rng = np.random.default_rng(seed=1337)
    lfo_amp = 0.08 + 0.05 * np.sin(2 * np.pi * 0.18 * t + rng.random() * 2 * np.pi)
    lfo_freq = 1.0 + 0.001 * np.sin(2 * np.pi * 0.07 * t)

    def osc(f, weight):
        # Sine + 2nd harmonic at -18 dB gives a warmer-than-pure tone.
        f_t = f * lfo_freq
        phase = 2 * np.pi * np.cumsum(f_t) / sample_rate
        return weight * (np.sin(phase) + 0.13 * np.sin(2 * phase))

    pad = (osc(root_freq_low, 0.36)
           + osc(root_freq_mid, 0.22)
           + osc(third_freq, 0.16)
           + osc(fifth_freq, 0.20))
    pad *= (1.0 + lfo_amp - lfo_amp.mean())

    # Add a soft air layer — bandpass-filtered noise.
    from scipy.signal import butter, sosfiltfilt
    noise = rng.standard_normal(n_samples).astype(np.float32)
    sos = butter(4, [4000 / (sample_rate / 2), 9000 / (sample_rate / 2)],
                 btype="bandpass", output="sos")
    air = sosfiltfilt(sos, noise) * 0.02
    pad = pad.astype(np.float32) + air.astype(np.float32)

    # Exponential fade in/out (250 ms each).
    fade_n = int(0.25 * sample_rate)
    ramp = np.linspace(0, 1, fade_n) ** 2
    pad[:fade_n] *= ramp
    pad[-fade_n:] *= ramp[::-1]

    # Quick normalise to roughly the target LUFS (rough estimate via RMS).
    rms = float(np.sqrt(np.mean(pad ** 2)) + 1e-12)
    target_rms = 10.0 ** ((target_lufs + 3) / 20.0)
    gain = target_rms / rms
    pad = (pad * gain).astype(np.float32)
    np.clip(pad, -0.99, 0.99, out=pad)

    # Write as stereo by duplicating.
    stereo = np.stack([pad, pad], axis=-1)

    ensure_dir(out_path.parent)
    sf.write(str(out_path), stereo, sample_rate, subtype="FLOAT")

    return PedalToneResult(
        out_path=out_path,
        duration_sec=duration_sec,
        sample_rate=sample_rate,
        key_root=key_root,
        mode=mode,
    )


@dataclass
class SegueResult:
    out_path: Path
    duration_sec: float
    crossfade_sec: float


def build_segue(
    song_a_path: Path,
    song_b_path: Path,
    out_path: Path,
    *,
    bridge_key: str | None = None,
    bridge_seconds: float = 8.0,
    crossfade_seconds: float = 2.0,
    sample_rate: int = 48000,
) -> SegueResult:
    """Render a smooth A → bridge → B transition for back-to-back songs.

    If ``bridge_key`` is None, we don't insert a pad — just cross-fade the
    last ``crossfade_seconds`` of A into the first ``crossfade_seconds``
    of B. With a bridge_key, we render a pedal-tone in that key and place
    it between the crossfades for a smoother key modulation.
    """
    a, sr_a = sf.read(str(song_a_path), dtype="float32", always_2d=True)
    b, sr_b = sf.read(str(song_b_path), dtype="float32", always_2d=True)
    if sr_a != sample_rate or sr_b != sample_rate:
        import librosa
        if sr_a != sample_rate:
            a = np.stack(
                [librosa.resample(a[:, c], orig_sr=sr_a, target_sr=sample_rate,
                                  res_type="soxr_hq") for c in range(a.shape[1])],
                axis=-1,
            ).astype(np.float32)
        if sr_b != sample_rate:
            b = np.stack(
                [librosa.resample(b[:, c], orig_sr=sr_b, target_sr=sample_rate,
                                  res_type="soxr_hq") for c in range(b.shape[1])],
                axis=-1,
            ).astype(np.float32)

    # Equal-power cross-fade window.
    xn = int(crossfade_seconds * sample_rate)
    ramp = np.sin(np.linspace(0, np.pi / 2, xn)) ** 2

    # Tail of A faded out, head of B faded in.
    a_tail = a[-xn:].copy()
    b_head = b[:xn].copy()
    a_tail *= ramp[::-1, None]
    b_head *= ramp[:, None]

    # Optional bridge pedal.
    if bridge_key:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            bridge_path = Path(tmp.name)
        synthesize_pedal_tone(
            bridge_path, bridge_key, mode="major",
            duration_sec=bridge_seconds + 2 * crossfade_seconds,
            sample_rate=sample_rate,
        )
        bridge_audio, _ = sf.read(str(bridge_path), dtype="float32", always_2d=True)
        bridge_path.unlink(missing_ok=True)
        # Trim to (xn + bridge + xn).
        target_n = xn + int(bridge_seconds * sample_rate) + xn
        if bridge_audio.shape[0] > target_n:
            bridge_audio = bridge_audio[:target_n]
        # Cross-fade pedal in over the tail of A, hold, cross-fade out into B head.
        result = np.concatenate([
            a[:-xn],
            a_tail + bridge_audio[:xn] * ramp[:, None],
            bridge_audio[xn:xn + int(bridge_seconds * sample_rate)],
            b_head + bridge_audio[-xn:] * ramp[::-1, None],
            b[xn:],
        ], axis=0).astype(np.float32)
    else:
        result = np.concatenate([
            a[:-xn],
            a_tail + b_head,
            b[xn:],
        ], axis=0).astype(np.float32)

    np.clip(result, -1.0, 1.0, out=result)

    ensure_dir(out_path.parent)
    sf.write(str(out_path), result, sample_rate, subtype="FLOAT")

    return SegueResult(
        out_path=out_path,
        duration_sec=result.shape[0] / sample_rate,
        crossfade_sec=crossfade_seconds,
    )
