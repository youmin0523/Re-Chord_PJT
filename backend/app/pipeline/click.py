"""Click track generation aligned to a BeatGrid.

Produces a stereo wav whose impacts land on each beat (and a brighter,
stronger impact on each downbeat). Used either:
  - as a standalone click track for practice,
  - or as the count-in tail inside a voice cue (last 3 beats of a 4-beat bar).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir
from .sections import BeatGrid


@dataclass
class ClickResult:
    out_path: Path
    sample_rate: int
    duration_sec: float
    beats: int
    downbeats: int


def _make_tick(sr: int, freq: float, dur_sec: float = 0.05, amp: float = 0.6) -> np.ndarray:
    """A short percussive 'tick': decaying sine with a sharp attack."""
    n = int(sr * dur_sec)
    t = np.arange(n) / sr
    env = np.exp(-t / max(dur_sec / 5.0, 1e-4))     # exponential decay
    attack = np.minimum(t / 0.001, 1.0)             # 1 ms attack
    sig = amp * env * attack * np.sin(2 * np.pi * freq * t)
    return sig.astype(np.float32)


def generate_click_track(
    beat_grid: BeatGrid,
    duration_sec: float,
    out_path: Path,
    sample_rate: int = 48000,
    beat_freq: float = 1500.0,
    downbeat_freq: float = 2200.0,
    beat_amp: float = 0.45,
    downbeat_amp: float = 0.75,
) -> ClickResult:
    """Render a click wav covering [0, duration_sec], one tick per beat."""
    n_total = int(duration_sec * sample_rate)
    track = np.zeros((n_total, 2), dtype=np.float32)

    beat_tick = _make_tick(sample_rate, beat_freq, dur_sec=0.04, amp=beat_amp)
    db_tick = _make_tick(sample_rate, downbeat_freq, dur_sec=0.05, amp=downbeat_amp)
    downbeats = set(round(t, 4) for t in beat_grid.downbeats_sec)

    db_count = 0
    bt_count = 0
    for t in beat_grid.beats_sec:
        if t < 0 or t >= duration_sec:
            continue
        idx = int(t * sample_rate)
        is_db = round(t, 4) in downbeats
        tick = db_tick if is_db else beat_tick
        end = min(idx + len(tick), n_total)
        track[idx:end, 0] += tick[: end - idx]
        track[idx:end, 1] += tick[: end - idx]
        if is_db:
            db_count += 1
        else:
            bt_count += 1

    np.clip(track, -1.0, 1.0, out=track)
    ensure_dir(out_path.parent)
    sf.write(str(out_path), track, sample_rate, subtype="FLOAT")

    return ClickResult(
        out_path=out_path,
        sample_rate=sample_rate,
        duration_sec=duration_sec,
        beats=bt_count + db_count,
        downbeats=db_count,
    )


def make_countin_pattern(
    sample_rate: int,
    bpm: float,
    n_beats: int = 3,
    downbeat_freq: float = 2200.0,
    beat_freq: float = 1500.0,
    amp: float = 0.6,
) -> np.ndarray:
    """A short standalone count-in burst (n ticks, evenly spaced at the BPM).

    Returned as a (samples, 2) stereo array. The first tick is the brighter
    'downbeat' tick (signals the very next beat = section downbeat).
    """
    beat_sec = 60.0 / max(bpm, 1.0)
    n_total = int(beat_sec * n_beats * sample_rate)
    out = np.zeros((n_total, 2), dtype=np.float32)
    for i in range(n_beats):
        idx = int(i * beat_sec * sample_rate)
        tick = _make_tick(
            sample_rate,
            downbeat_freq if i == 0 else beat_freq,
            dur_sec=0.05,
            amp=amp,
        )
        end = min(idx + len(tick), n_total)
        out[idx:end, 0] += tick[: end - idx]
        out[idx:end, 1] += tick[: end - idx]
    np.clip(out, -1.0, 1.0, out=out)
    return out
