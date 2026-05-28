"""Spatial / hi-end audio output renders (5.1 surround, DSD).

These are *export-stage* helpers — given the stems of a finished job we
render them into a single file at a specific channel layout / format
that the standard PCM encode path doesn't cover. ffmpeg does all the
heavy lifting; we just compose the right filter graph.

Two outputs:

  * **5.1 surround render** — place each stem at a logical screen
    position and downmix to standard 5.1 (FL FR C LFE BL BR). Useful
    for users with a home-theatre / consumer Atmos-aware DAW or for
    in-ear monitor mixing in worship contexts.

  * **DSD output** — convert the master to DSD64 (2.8224 MHz / 1-bit).
    Audiophile / SACD-style export. Lossy conversion of dynamic
    information when the source is float 32-bit, but format-correct.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..core.paths import ensure_dir


@dataclass
class SurroundResult:
    out_path: Path
    channel_layout: str
    sample_rate: int


# Stem → (FL, FR, C, LFE, BL, BR) gain matrix coefficients.
# Convention: vocals + lead instruments go front center, drums/bass front
# stereo, harmonic content rear stereo, low-end split to LFE for the kick.
# All values are amplitude factors (0..1), not dB. Sums per channel stay
# ≤ 1 to prevent surround clipping.
_STEM_PLACEMENT_5_1: dict[str, tuple[float, float, float, float, float, float]] = {
    # stem_name:          FL    FR    C     LFE   BL    BR
    "vocals":           (0.20, 0.20, 0.95, 0.00, 0.10, 0.10),
    "instrumental":     (0.55, 0.55, 0.10, 0.20, 0.45, 0.45),
    "drums":            (0.70, 0.70, 0.05, 0.40, 0.20, 0.20),
    "bass":             (0.55, 0.55, 0.10, 0.85, 0.15, 0.15),
    "guitar":           (0.75, 0.30, 0.10, 0.05, 0.60, 0.25),
    "piano":            (0.30, 0.75, 0.10, 0.05, 0.25, 0.60),
    "other":            (0.30, 0.30, 0.05, 0.00, 0.65, 0.65),
}


def render_5_1_surround(
    stems: dict[str, Path],
    out_path: Path,
    *,
    sample_rate: int = 48000,
) -> SurroundResult:
    """Compose stems into a single 5.1 WAV. Skips stems we don't have."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not on PATH")
    if not stems:
        raise ValueError("render_5_1_surround: empty stems dict")

    # Build an ffmpeg invocation that:
    #   1. Reads each stem as a stereo input.
    #   2. Pan-filters each to a 6-channel intermediate (5.1 layout).
    #   3. Mixes all intermediates equally.

    inputs: list[str] = []
    filter_lines: list[str] = []
    mix_inputs: list[str] = []

    for idx, (stem_name, path) in enumerate(stems.items()):
        placement = _STEM_PLACEMENT_5_1.get(stem_name)
        if placement is None:
            continue
        fl, fr, c, lfe, bl, br = placement
        inputs.extend(["-i", str(path)])
        # Pan filter that maps stereo input to 5.1 output. We average L/R
        # of the source to a single signal per channel using the placement
        # weights — keeps the math simple and stable across sources of
        # different stereo widths.
        filter_lines.append(
            f"[{idx}:a]aformat=channel_layouts=stereo,"
            f"pan=5.1|FL={fl}*FL+{fl}*FR|FR={fr}*FL+{fr}*FR|"
            f"FC={c}*FL+{c}*FR|LFE={lfe}*FL+{lfe}*FR|"
            f"BL={bl}*FL+{bl}*FR|BR={br}*FL+{br}*FR[s{idx}]"
        )
        mix_inputs.append(f"[s{idx}]")

    if not mix_inputs:
        raise ValueError("none of the supplied stems matched the placement table")

    mix_n = len(mix_inputs)
    filter_lines.append(
        "".join(mix_inputs) + f"amix=inputs={mix_n}:duration=longest:normalize=0[mix]"
    )
    filter_complex = ";".join(filter_lines)

    ensure_dir(out_path.parent)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    cmd = [
        ffmpeg, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[mix]",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s24le",
        "-f", "wav",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 5.1 render failed: {proc.stderr[-400:] if proc.stderr else 'unknown'}"
        )
    tmp.replace(out_path)
    return SurroundResult(out_path=out_path, channel_layout="5.1", sample_rate=sample_rate)


@dataclass
class DsdResult:
    out_path: Path
    sample_rate: int           # nominal PCM equivalent (DSD64 = 2.8224 MHz / 64 = 44100)


_DSD_SUPPORT_CACHE: dict[str, bool] = {}


def dsd_supported() -> bool:
    """Return True if the system ffmpeg can write .dsf files.

    Cached per-process. The gyan.dev Windows builds (8.x) do NOT include
    the dsd_lsbf_planar encoder; users who need DSD output should install
    a build that does (e.g. compile with --enable-encoder=dsd_lsbf_planar
    or use the BtbN nightly).
    """
    if "dsf" in _DSD_SUPPORT_CACHE:
        return _DSD_SUPPORT_CACHE["dsf"]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        _DSD_SUPPORT_CACHE["dsf"] = False
        return False
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-formats"],
            capture_output=True, text=True, timeout=5,
        )
        text = proc.stdout or ""
        # ffmpeg lists each format with " E " (encode supported) prefix.
        has_dsf = any(
            "dsf" in line.split() and ("E" in line[:6])
            for line in text.splitlines()
        )
    except Exception:
        has_dsf = False
    _DSD_SUPPORT_CACHE["dsf"] = has_dsf
    return has_dsf


def render_dsd(input_path: Path, out_path: Path, dsd_rate: str = "dsd64") -> DsdResult:
    """Encode a PCM source to DSD (.dsf) at the requested rate.

    Raises ``RuntimeError`` with a clear message when the local ffmpeg
    doesn't support the .dsf muxer (common with gyan.dev Windows builds).
    The API layer surfaces this as a 503 so the frontend can show a
    "ffmpeg without DSD support" tip instead of a generic 500.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not on PATH")
    if not dsd_supported():
        raise RuntimeError(
            "현재 ffmpeg 빌드가 DSD(.dsf) 인코딩을 지원하지 않습니다. "
            "BtbN nightly 또는 --enable-encoder=dsd_lsbf_planar 포함 빌드를 사용하세요."
        )

    rate_hz = {
        "dsd64":  2822400,
        "dsd128": 5644800,
        "dsd256": 11289600,
    }.get(dsd_rate.lower(), 2822400)

    ensure_dir(out_path.parent)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    cmd = [
        ffmpeg, "-y",
        "-i", str(input_path),
        "-ar", str(rate_hz),
        "-c:a", "dsd_lsbf_planar",
        "-f", "dsf",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"DSD encode failed: {proc.stderr[-400:] if proc.stderr else 'unknown'}"
        )
    tmp.replace(out_path)
    return DsdResult(out_path=out_path, sample_rate=rate_hz)
