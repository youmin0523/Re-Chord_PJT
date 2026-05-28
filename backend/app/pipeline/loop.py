"""Loop / A-B repeat export.

Take a segment [start, end] of an audio file and repeat it N times into a
single wav. Optionally prepend a count-in bar so practice loops start in
tempo, and optionally fade in/out at the boundaries for clean repeats.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir
from .click import make_countin_pattern


@dataclass
class LoopResult:
    out_path: Path
    sample_rate: int
    duration_sec: float
    repeats: int
    segment_sec: float
    has_countin: bool


def _trim_segment(
    input_path: Path,
    start_sec: float,
    end_sec: float,
    out_wav: Path,
    target_sr: int,
) -> None:
    """Cut [start, end] out of input via ffmpeg into a stereo float wav at target_sr."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH")
    duration = max(0.001, end_sec - start_sec)
    cmd = [
        exe, "-y",
        "-ss", f"{start_sec:.4f}",
        "-i", str(input_path),
        "-t", f"{duration:.4f}",
        "-vn", "-map_metadata", "-1",
        "-ac", "2",
        "-af",
        f"aresample=resampler=soxr:precision=28:osr={target_sr},"
        "aformat=sample_fmts=flt:channel_layouts=stereo",
        "-c:a", "pcm_f32le",
        "-f", "wav",
        str(out_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg trim failed: {proc.stderr.strip()}")


def _apply_edge_fades(buf: np.ndarray, sr: int, fade_ms: float = 8.0) -> None:
    """Tiny linear fade-in/out on each segment so repeats don't click."""
    n = int(sr * fade_ms / 1000.0)
    if n <= 0 or buf.shape[0] < 2 * n:
        return
    ramp_in = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    ramp_out = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
    buf[:n] *= ramp_in
    buf[-n:] *= ramp_out


def loop_segment(
    input_path: Path,
    out_path: Path,
    start_sec: float,
    end_sec: float,
    repeats: int = 4,
    target_sr: int = 48000,
    with_countin: bool = True,
    bpm: float = 0.0,
    meter: int = 4,
    fades_ms: float = 8.0,
) -> LoopResult:
    """Build a looped wav.

    Output layout:
        [optional 1-bar count-in if with_countin and bpm > 0]
        [segment * repeats] (each with tiny edge fades to avoid clicks)
    """
    if repeats < 1:
        repeats = 1
    if end_sec <= start_sec:
        raise ValueError(f"end_sec ({end_sec}) must be > start_sec ({start_sec})")

    with tempfile.TemporaryDirectory() as tmp:
        seg_path = Path(tmp) / "segment.wav"
        _trim_segment(input_path, start_sec, end_sec, seg_path, target_sr)
        seg, sr = sf.read(str(seg_path), dtype="float32", always_2d=True)
        if seg.shape[1] == 1:
            seg = np.repeat(seg, 2, axis=1)
        elif seg.shape[1] > 2:
            seg = seg[:, :2]

        _apply_edge_fades(seg, sr, fade_ms=fades_ms)

        parts: list[np.ndarray] = []
        has_countin = False
        if with_countin and bpm > 0:
            countin = make_countin_pattern(sample_rate=sr, bpm=bpm, n_beats=meter)
            parts.append(countin)
            has_countin = True

        for _ in range(repeats):
            parts.append(seg)

        out = np.concatenate(parts, axis=0) if parts else seg
        np.clip(out, -1.0, 1.0, out=out)
        ensure_dir(out_path.parent)
        sf.write(str(out_path), out, sr, subtype="FLOAT")

        return LoopResult(
            out_path=out_path,
            sample_rate=sr,
            duration_sec=out.shape[0] / sr,
            repeats=repeats,
            segment_sec=(end_sec - start_sec),
            has_countin=has_countin,
        )
