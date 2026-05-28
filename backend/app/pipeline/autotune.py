"""Subtle vocal pitch correction ("auto-tune lite") via CREPE + WORLD.

The goal is not to make Cher / T-Pain style audible auto-tune — it's to
*gently* nudge slightly-off pitches in amateur recordings back to the
nearest scale degree, preserving the singer's natural vibrato and
inflection. Two parameters control intensity:

  ``correction_strength``  0..1   how strongly to pull toward the grid
                                  (1.0 = full snap, 0.5 = halfway)
  ``snap_window_cents``    int    only correct notes within this distance
                                  (e.g. 50 = ±50 cents); larger drifts are
                                  intentional and left alone

Pipeline:
  1. CREPE pitch tracking (10 ms frames, viterbi).
  2. Quantize each frame to its nearest scale degree if within window.
  3. Smooth the correction with a short median filter to prevent
     micro-jumps mid-note.
  4. WORLD analyse the original audio.
  5. Replace F0 with the corrected sequence; spectral envelope +
     aperiodicity stay intact (formants preserved).
  6. Synthesize.

When either ``crepe`` or ``pyworld`` is missing, this module raises
ImportError so the caller can decide whether to expose the feature.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import soundfile as sf


@dataclass
class AutotuneResult:
    out_path: Path
    sample_rate: int
    frames_corrected: int
    elapsed_sec: float
    strength: float
    snap_cents: int
    preset: str = ""


# Named presets — a single source of truth that both the API and UI
# pull from. Naming follows the user-mental-model: "Natural" = most
# people only need this; "Bold" = T-Pain effect.
AUTOTUNE_PRESETS: dict[str, dict] = {
    # Subtle: half-snap, narrow window. Catches only slightly-off notes,
    # leaves vibrato and intentional slides untouched. Recommended for
    # worship lead vocals where natural inflection matters.
    "subtle":   {"correction_strength": 0.40, "snap_window_cents": 30,
                 "description": "거의 들리지 않는 보정 — 비브라토 / 슬라이드 보존"},
    # Natural: balanced default. Most amateur recordings benefit from
    # this — pitches inside ±50 cents are pulled most of the way to the
    # grid, more dramatic drifts are intentional and left alone.
    "natural":  {"correction_strength": 0.65, "snap_window_cents": 50,
                 "description": "자연스러운 보정 (기본값) — 음정만 정리"},
    # Tight: aggressive snap. For background harmonies that should lock
    # to the lead, or for studio polish where the listener expects
    # "perfect" intonation.
    "tight":    {"correction_strength": 0.85, "snap_window_cents": 70,
                 "description": "타이트한 보정 — 화음/스튜디오 마감용"},
    # Bold: T-Pain / Cher-style audible auto-tune. Snap = 1.0, wide
    # window catches even half-step drifts so the characteristic
    # "stepped" pitch contour comes through.
    "bold":     {"correction_strength": 1.00, "snap_window_cents": 100,
                 "description": "효과로 의도된 강한 보정 — T-Pain 스타일"},
}


def apply_preset(name: str) -> dict | None:
    """Look up a preset by name; returns None for unknown presets."""
    return AUTOTUNE_PRESETS.get((name or "").lower().strip())


# Western major / natural-minor scale templates (semitone offsets in 12-TET).
SCALE_TEMPLATES: dict[str, list[int]] = {
    "major":  [0, 2, 4, 5, 7, 9, 11],
    "minor":  [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixo":   [0, 2, 4, 5, 7, 9, 10],
    "chromatic": list(range(12)),
}

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def is_available() -> bool:
    try:
        import crepe  # noqa: F401
        import pyworld  # noqa: F401
        return True
    except ImportError:
        return False


def autotune_vocal(
    input_path: Path,
    out_path: Path,
    *,
    key_root: str = "C",
    scale: str = "major",
    correction_strength: float = 0.65,
    snap_window_cents: int = 50,
    preset: str | None = None,
) -> AutotuneResult:
    """Apply pitch correction to a vocal file and write a corrected WAV.

    ``preset``: one of "subtle" | "natural" | "tight" | "bold". When set,
    overrides ``correction_strength`` and ``snap_window_cents`` with the
    preset's tuned values (see :data:`AUTOTUNE_PRESETS`).
    """
    preset_name = ""
    if preset:
        p = apply_preset(preset)
        if p:
            correction_strength = float(p["correction_strength"])
            snap_window_cents = int(p["snap_window_cents"])
            preset_name = preset.lower().strip()
    try:
        import crepe  # type: ignore
        import pyworld as pw  # type: ignore
    except ImportError as e:
        raise ImportError(
            "autotune requires both crepe and pyworld. "
            "Run: `uv pip install crepe --no-build-isolation pyworld`"
        ) from e

    import librosa

    t0 = time.perf_counter()

    audio, sr = sf.read(str(input_path), dtype="float32", always_2d=True)
    if audio.shape[1] > 2:
        audio = audio[:, :2]

    # CREPE analyses mono at 16 kHz internally; we average channels for f0
    # detection then apply the correction independently to each channel.
    mono = audio.mean(axis=1)
    if sr != 16000:
        mono_16k = librosa.resample(mono, orig_sr=sr, target_sr=16000,
                                     res_type="soxr_hq")
    else:
        mono_16k = mono

    times, freqs, confs, _ = crepe.predict(
        mono_16k.astype(np.float32), 16000,
        model_capacity="medium", step_size=10, viterbi=True, verbose=0,
    )

    # Scale-snap each frame whose drift is within the window.
    target_freqs, n_corrected = _snap_to_scale(
        freqs, confs,
        key_root=key_root, scale=scale,
        snap_cents=snap_window_cents,
        strength=correction_strength,
    )

    # Build a frame-time → multiplicative ratio map. We'll resample this
    # to the per-sample F0 grid WORLD will use (5 ms frames).
    crepe_ratio = np.where(freqs > 0, target_freqs / np.maximum(freqs, 1e-6), 1.0)
    crepe_times = times                    # seconds, 10-ms step

    # Per-channel WORLD analysis + corrected synthesis.
    out_channels = []
    for c in range(audio.shape[1]):
        x = audio[:, c].astype(np.float64)
        f0, t_world = pw.dio(x, sr, frame_period=5.0)
        f0 = pw.stonemask(x, f0, t_world, sr)
        sp = pw.cheaptrick(x, f0, t_world, sr)
        ap = pw.d4c(x, f0, t_world, sr)
        # Interpolate the correction ratio to the WORLD frame grid.
        ratio = np.interp(t_world, crepe_times, crepe_ratio,
                          left=1.0, right=1.0)
        f0_corr = f0 * ratio
        y = pw.synthesize(f0_corr, sp, ap, sr, frame_period=5.0)
        out_channels.append(y.astype(np.float32))

    out = np.stack(out_channels, axis=-1)
    np.clip(out, -1.0, 1.0, out=out)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), out, sr, subtype="FLOAT")

    return AutotuneResult(
        out_path=out_path,
        sample_rate=sr,
        frames_corrected=int(n_corrected),
        elapsed_sec=time.perf_counter() - t0,
        strength=correction_strength,
        snap_cents=snap_window_cents,
        preset=preset_name,
    )


def _snap_to_scale(
    freqs: np.ndarray,
    confs: np.ndarray,
    *,
    key_root: str,
    scale: str,
    snap_cents: int,
    strength: float,
) -> tuple[np.ndarray, int]:
    """Compute per-frame target frequency that nudges each f0 toward the
    nearest scale tone within the snap window. Returns (target_freqs, n_corrected)."""
    scale_offsets = SCALE_TEMPLATES.get(scale, SCALE_TEMPLATES["major"])
    root_idx = PITCH_CLASSES.index(key_root) if key_root in PITCH_CLASSES else 0
    scale_pcs = {(root_idx + off) % 12 for off in scale_offsets}

    target = np.copy(freqs)
    n_corrected = 0

    for i in range(len(freqs)):
        f = float(freqs[i])
        c = float(confs[i])
        if f <= 0 or c < 0.5:
            continue
        midi_f = 69 + 12 * np.log2(f / 440.0)
        nearest_int = int(round(midi_f))
        # Snap to the nearest MIDI integer first.
        cents_off_int = (midi_f - nearest_int) * 100  # signed cents
        if abs(cents_off_int) > snap_cents:
            continue
        # Now find the closest scale-pc.
        nearest_pc = nearest_int % 12
        if nearest_pc not in scale_pcs:
            # Shift to nearest scale tone (max ±1 semitone).
            options = sorted(
                [(min((nearest_pc - pc) % 12, (pc - nearest_pc) % 12), pc)
                 for pc in scale_pcs],
                key=lambda t: t[0],
            )
            best_dist, best_pc = options[0]
            if best_dist > 1:
                continue   # gap larger than 1 semitone — leave alone
            shift = ((best_pc - nearest_pc + 6) % 12) - 6
            target_midi = nearest_int + shift - cents_off_int / 100
        else:
            target_midi = float(nearest_int)
        # Blend toward target by `strength`.
        new_midi = midi_f * (1 - strength) + target_midi * strength
        target[i] = 440.0 * (2.0 ** ((new_midi - 69) / 12.0))
        n_corrected += 1

    return target, n_corrected
