"""Environment diagnostics for the MR Platform.

Run with:  uv run python scripts/doctor.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table

console = Console(legacy_windows=False, force_terminal=True)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_python() -> CheckResult:
    v = sys.version_info
    ok = v.major == 3 and v.minor == 11
    return CheckResult(
        "Python 3.11",
        ok,
        f"{sys.version.split()[0]} @ {sys.executable}",
    )


def check_ffmpeg() -> CheckResult:
    exe = shutil.which("ffmpeg")
    if not exe:
        return CheckResult("ffmpeg", False, "not on PATH")
    proc = subprocess.run([exe, "-version"], capture_output=True, text=True)
    head = proc.stdout.splitlines()[0] if proc.stdout else "?"
    cfg = "\n".join(line for line in proc.stdout.splitlines() if "configuration" in line)
    features = [f for f in ("librubberband", "libsoxr", "chromaprint", "libmp3lame") if f in cfg]
    ok = "librubberband" in cfg and "libsoxr" in cfg
    return CheckResult("ffmpeg", ok, f"{head} | features: {', '.join(features) or 'minimal build'}")


def check_ffprobe() -> CheckResult:
    exe = shutil.which("ffprobe")
    if not exe:
        return CheckResult("ffprobe", False, "not on PATH")
    proc = subprocess.run([exe, "-version"], capture_output=True, text=True)
    head = proc.stdout.splitlines()[0] if proc.stdout else "?"
    return CheckResult("ffprobe", True, head)


def check_ytdlp() -> CheckResult:
    try:
        import yt_dlp  # noqa: F401
    except Exception as e:
        return CheckResult("yt-dlp", False, f"import failed: {e!r}")
    return CheckResult("yt-dlp", True, f"version {yt_dlp.version.__version__}")


def check_torch() -> CheckResult:
    try:
        import torch
    except Exception as e:
        return CheckResult("torch", False, f"import failed: {e!r}")
    detail = f"torch {torch.__version__}, cuda runtime {torch.version.cuda}"
    if not torch.cuda.is_available():
        return CheckResult("torch + CUDA", False, detail + " | CUDA not available")
    name = torch.cuda.get_device_name(0)
    cc = torch.cuda.get_device_capability(0)
    try:
        x = torch.randn(256, 256, device="cuda")
        _ = (x @ x).sum().item()
        h = torch.randn(64, 64, dtype=torch.float16, device="cuda")
        _ = (h @ h).sum().item()
        return CheckResult(
            "torch + CUDA",
            True,
            f"{detail} | {name}, sm_{cc[0]}{cc[1]} | matmul fp32+fp16 OK",
        )
    except Exception as e:
        return CheckResult(
            "torch + CUDA",
            False,
            f"{detail} | {name}, sm_{cc[0]}{cc[1]} | kernel test FAILED: {e!r}",
        )


def check_onnxruntime() -> CheckResult:
    try:
        import onnxruntime as ort
    except Exception as e:
        return CheckResult("onnxruntime", False, f"import failed: {e!r}")
    providers = ort.get_available_providers()
    has_cuda = "CUDAExecutionProvider" in providers
    return CheckResult(
        "onnxruntime",
        has_cuda,
        f"version {ort.__version__} | providers: {', '.join(providers)}",
    )


def check_audio_separator() -> CheckResult:
    try:
        from audio_separator.separator import Separator  # noqa: F401
        from importlib.metadata import version
        v = version("audio-separator")
    except Exception as e:
        return CheckResult("audio-separator", False, f"import failed: {e!r}")
    return CheckResult("audio-separator", True, f"version {v}")


def check_audio_io() -> CheckResult:
    try:
        import soundfile as sf
        import numpy as np
        import io

        # 1 second, 48 kHz, stereo sine
        sr = 48000
        t = np.linspace(0, 1, sr, endpoint=False)
        sig = np.column_stack([0.1 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, sig, sr, subtype="FLOAT", format="WAV")
        buf.seek(0)
        read_sig, read_sr = sf.read(buf, dtype="float32")
        ok = read_sr == sr and read_sig.shape == sig.shape
        return CheckResult(
            "soundfile (audio I/O)",
            ok,
            f"libsndfile via soundfile, round-trip 48 kHz stereo float32 OK",
        )
    except Exception as e:
        return CheckResult("soundfile (audio I/O)", False, f"failed: {e!r}")


def check_nvidia_smi() -> CheckResult:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return CheckResult("nvidia-smi", False, "not on PATH")
    proc = subprocess.run(
        [exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True,
    )
    line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "?"
    return CheckResult("nvidia-smi", True, line)


def check_rubberband_cli() -> CheckResult:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from backend.app.pipeline.transform import find_rubberband_cli
        cli = find_rubberband_cli()
    except Exception as e:
        return CheckResult("rubberband-cli (R3)", False, f"resolver failed: {e!r}")
    if not cli:
        return CheckResult(
            "rubberband-cli (R3)", False,
            "not found - falls back to ffmpeg R2 (lower quality)",
        )
    proc = subprocess.run([cli, "--version"], capture_output=True, text=True)
    head = (proc.stdout + proc.stderr).strip().splitlines()
    return CheckResult(
        "rubberband-cli (R3)", True,
        f"{cli} | {(head[0] if head else 'OK')}",
    )


def check_disk_space() -> CheckResult:
    """Need ~5GB free for model cache + working files on a typical 6-min track."""
    root = Path(__file__).resolve().parents[1]
    try:
        usage = shutil.disk_usage(root)
    except Exception as e:
        return CheckResult("disk space", False, f"disk_usage failed: {e!r}")
    free_gb = usage.free / (1024 ** 3)
    ok = free_gb >= 3.0
    return CheckResult(
        "disk space",
        ok,
        f"{free_gb:.1f} GB free on project drive (need ≥ 3 GB; "
        f"6-min job ≈ 1.5 GB working space)",
    )


def check_model_cache() -> CheckResult:
    """Are the key separation model files already downloaded?"""
    root = Path(__file__).resolve().parents[1] / "data" / "models"
    must_have = [
        "MDX23C-8KFFT-InstVoc_HQ.ckpt",
        "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "melband_roformer_inst_v2.ckpt",
    ]
    present = [m for m in must_have if (root / m).exists()]
    if len(present) == len(must_have):
        return CheckResult(
            "model cache", True,
            f"core ensemble models cached at {root}",
        )
    missing = [m for m in must_have if m not in present]
    return CheckResult(
        "model cache", False,
        f"missing {missing} — run `uv run python scripts/install_models.py ensemble`",
    )


def check_vram_headroom() -> CheckResult:
    """Warn if free VRAM is < 4 GB (won't fit BS-Roformer fp16 segment)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return CheckResult("VRAM headroom", False, "CUDA not available")
        free, total = torch.cuda.mem_get_info(0)
        free_gb = free / (1024 ** 3)
        total_gb = total / (1024 ** 3)
        ok = free_gb >= 3.5
        return CheckResult(
            "VRAM headroom",
            ok,
            f"{free_gb:.2f} / {total_gb:.2f} GB free "
            f"({'enough for fp16 BS-Roformer' if ok else 'tight — close other GPU apps'})",
        )
    except Exception as e:
        return CheckResult("VRAM headroom", False, f"probe failed: {e!r}")


CHECKS: list[Callable[[], CheckResult]] = [
    check_python,
    check_nvidia_smi,
    check_torch,
    check_vram_headroom,
    check_onnxruntime,
    check_ffmpeg,
    check_ffprobe,
    check_ytdlp,
    check_audio_separator,
    check_audio_io,
    check_rubberband_cli,
    check_disk_space,
    check_model_cache,
]


def main() -> int:
    table = Table(title="MR Platform - Environment Doctor")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")

    fail_count = 0
    for fn in CHECKS:
        try:
            r = fn()
        except Exception as e:  # pragma: no cover
            r = CheckResult(fn.__name__, False, f"check crashed: {e!r}")
        status = "[green]PASS[/green]" if r.ok else "[red]FAIL[/red]"
        if not r.ok:
            fail_count += 1
        table.add_row(r.name, status, r.detail)

    console.print(table)
    if fail_count == 0:
        console.print("\n[green]All checks passed.[/green]")
        return 0
    console.print(f"\n[red]{fail_count} check(s) failed.[/red]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
