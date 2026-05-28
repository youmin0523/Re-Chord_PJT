"""Decode the ingested source to a working master wav.

Policy:
  work_sr = max(source_sr, 48000)   # preserve high-resolution sources, upsample only if below 48k
  channels = 2 (mono is duplicated, multi-channel is downmixed to stereo)
  sample_fmt = float32 (model-friendly)
  resampler = soxr precision 28 (transparent)
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..core.paths import ensure_dir


WORKING_SR_FLOOR = 48000


@dataclass
class DecodeResult:
    job_id: str
    master: Path
    sample_rate: int
    channels: int
    duration_sec: float


def pick_work_sr(source_sr: int) -> int:
    """Choose the working sample rate: max(source, 48k). Snap to common rates."""
    if source_sr <= 0:
        return WORKING_SR_FLOOR
    if source_sr >= 96000:
        return 96000
    if source_sr >= 88200:
        return 88200
    if source_sr >= 48000:
        return 48000
    return WORKING_SR_FLOOR  # upsample 44.1k or below to 48k


def decode_to_master(
    source: Path,
    work_dir: Path,
    source_sr: int,
    job_id: str,
) -> DecodeResult:
    """Decode the source media to a float32 stereo wav at the chosen working sr."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH")

    ensure_dir(work_dir)
    work_sr = pick_work_sr(source_sr)
    out = work_dir / f"master_{work_sr}_f32.wav"
    tmp = out.with_suffix(out.suffix + ".tmp")

    af = (
        f"aresample=resampler=soxr:precision=28:osr={work_sr}:"
        f"out_sample_fmt=fltp,"
        "aformat=sample_fmts=flt:channel_layouts=stereo"
    )

    cmd = [
        exe, "-y",
        "-i", str(source),
        "-vn",
        "-map_metadata", "-1",
        "-ac", "2",
        "-af", af,
        "-c:a", "pcm_f32le",
        "-f", "wav",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed: {proc.stderr.strip()}")
    tmp.replace(out)

    duration = _probe_duration(out)
    return DecodeResult(
        job_id=job_id,
        master=out,
        sample_rate=work_sr,
        channels=2,
        duration_sec=duration,
    )


def _probe_duration(path: Path) -> float:
    exe = shutil.which("ffprobe")
    if not exe:
        return 0.0
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0
