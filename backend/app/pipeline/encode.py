"""Final encode to user-selected format / sample rate / bit depth.

Format matrix:
  WAV  - 16/24-bit / 32-bit float ; 44.1 / 48 / 88.2 / 96 kHz
  FLAC - 16/24-bit              ; 44.1 / 48 / 88.2 / 96 kHz
  AIFF - 16/24-bit / 32-bit float ; 44.1 / 48 / 88.2 / 96 kHz
  MP3  - 320 kbps lossy         ; 44.1 / 48 kHz
  AAC  - 256 kbps lossy (m4a)   ; 44.1 / 48 kHz

Dithering: TPDF (triangular_hp) applied automatically when downcasting
float -> integer PCM at 24-bit or lower. Float-to-float never dithered.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..core.paths import ensure_dir


Format = Literal["wav", "flac", "aiff", "mp3", "aac"]
BitDepth = Literal["16", "24", "32f"]

# Valid (format, bit_depth) combinations.
ALLOWED_BIT_DEPTHS: dict[Format, set[BitDepth]] = {
    "wav": {"16", "24", "32f"},
    "flac": {"16", "24"},
    "aiff": {"16", "24", "32f"},
    "mp3": set(),  # lossy, bit_depth ignored
    "aac": set(),
}

ALLOWED_SR: dict[Format, set[int]] = {
    "wav": {44100, 48000, 88200, 96000},
    "flac": {44100, 48000, 88200, 96000},
    "aiff": {44100, 48000, 88200, 96000},
    "mp3": {44100, 48000},
    "aac": {44100, 48000},
}

EXT: dict[Format, str] = {
    "wav": ".wav",
    "flac": ".flac",
    "aiff": ".aif",
    "mp3": ".mp3",
    "aac": ".m4a",
}


@dataclass
class EncodeResult:
    out_path: Path
    format: Format
    sample_rate: int
    bit_depth: BitDepth | None
    file_size_bytes: int


def _build_filter(target_sr: int, dither: bool) -> str:
    if dither:
        return (
            f"aresample=resampler=soxr:precision=28:osr={target_sr}:"
            "dither_method=triangular_hp"
        )
    return f"aresample=resampler=soxr:precision=28:osr={target_sr}"


def encode(
    input_path: Path,
    out_path: Path,
    format: Format,
    sample_rate: int = 48000,
    bit_depth: BitDepth = "24",
    mp3_bitrate_kbps: int = 320,
    aac_bitrate_kbps: int = 256,
) -> EncodeResult:
    """Encode the float wav stem to the user's chosen format."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH")

    if sample_rate not in ALLOWED_SR[format]:
        raise ValueError(
            f"sample_rate {sample_rate} not allowed for {format}; "
            f"choose one of {sorted(ALLOWED_SR[format])}"
        )
    if format in ("mp3", "aac"):
        bit_depth_eff: BitDepth | None = None
    else:
        if bit_depth not in ALLOWED_BIT_DEPTHS[format]:
            raise ValueError(
                f"bit_depth {bit_depth!r} not allowed for {format}; "
                f"choose one of {sorted(ALLOWED_BIT_DEPTHS[format])}"
            )
        bit_depth_eff = bit_depth

    # Force the file extension to match the format.
    out_path = out_path.with_suffix(EXT[format])
    ensure_dir(out_path.parent)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")

    cmd: list[str] = [exe, "-y", "-i", str(input_path), "-vn", "-map_metadata", "-1"]

    if format == "wav":
        if bit_depth == "32f":
            af = _build_filter(sample_rate, dither=False)
            codec = ["-c:a", "pcm_f32le"]
        elif bit_depth == "24":
            af = _build_filter(sample_rate, dither=True)
            codec = ["-c:a", "pcm_s24le"]
        else:  # 16
            af = _build_filter(sample_rate, dither=True)
            codec = ["-c:a", "pcm_s16le"]
        cmd += ["-af", af, *codec, "-f", "wav", str(tmp)]

    elif format == "flac":
        if bit_depth == "24":
            af = _build_filter(sample_rate, dither=True)
            sample_fmt = ["-sample_fmt", "s32"]  # 24-bit packed in s32 container
        else:
            af = _build_filter(sample_rate, dither=True)
            sample_fmt = ["-sample_fmt", "s16"]
        cmd += ["-af", af, "-c:a", "flac", "-compression_level", "8",
                *sample_fmt, "-f", "flac", str(tmp)]

    elif format == "aiff":
        if bit_depth == "32f":
            af = _build_filter(sample_rate, dither=False)
            codec = ["-c:a", "pcm_f32be"]
        elif bit_depth == "24":
            af = _build_filter(sample_rate, dither=True)
            codec = ["-c:a", "pcm_s24be"]
        else:
            af = _build_filter(sample_rate, dither=True)
            codec = ["-c:a", "pcm_s16be"]
        cmd += ["-af", af, *codec, "-f", "aiff", str(tmp)]

    elif format == "mp3":
        af = f"aresample=resampler=soxr:precision=28:osr={sample_rate}"
        cmd += ["-af", af, "-c:a", "libmp3lame",
                "-b:a", f"{mp3_bitrate_kbps}k", "-f", "mp3", str(tmp)]

    elif format == "aac":
        af = f"aresample=resampler=soxr:precision=28:osr={sample_rate}"
        cmd += ["-af", af, "-c:a", "aac",
                "-b:a", f"{aac_bitrate_kbps}k", "-f", "ipod", str(tmp)]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"encode failed: {proc.stderr.strip()}")
    tmp.replace(out_path)

    return EncodeResult(
        out_path=out_path,
        format=format,
        sample_rate=sample_rate,
        bit_depth=bit_depth_eff,
        file_size_bytes=out_path.stat().st_size,
    )
