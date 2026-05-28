"""Pre-download separation model weights to data/models.

Run with:  uv run python scripts/install_models.py [--all|--core|<model_filename>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "data" / "models"

console = Console(legacy_windows=False, force_terminal=True)


# (filename, role, approx_size_mb) — sized for the Phase A 8GB VRAM ensemble.
MODEL_SETS = {
    "core": [
        ("MDX23C-8KFFT-InstVoc_HQ.ckpt", "MDX23C-InstVoc HQ (vocal/instrumental, D3 main)", 700),
    ],
    "ensemble": [
        ("MDX23C-8KFFT-InstVoc_HQ.ckpt", "MDX23C-InstVoc HQ", 700),
        ("model_bs_roformer_ep_317_sdr_12.9755.ckpt", "BS-Roformer-Viperx-1297", 700),
        ("htdemucs_ft.yaml", "Demucs v4 htdemucs_ft (4-stem)", 1100),
    ],
    "stems": [
        ("htdemucs_6s.yaml", "Demucs v4 htdemucs_6s (6-stem)", 300),
    ],
}


def download_one(model_filename: str) -> None:
    from audio_separator.separator import Separator
    sep = Separator(model_file_dir=str(MODELS_DIR), output_dir=str(MODELS_DIR))
    console.print(f"[bold]==> downloading[/bold] {model_filename}")
    sep.download_model_files(model_filename)


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    p = argparse.ArgumentParser(description="Pre-download separation models")
    p.add_argument("targets", nargs="*", help="model filenames, or one of: core, ensemble, stems, all")
    args = p.parse_args()

    targets = args.targets or ["core"]
    files: list[str] = []
    for t in targets:
        if t == "all":
            for vals in MODEL_SETS.values():
                files.extend(f for f, _, _ in vals)
        elif t in MODEL_SETS:
            files.extend(f for f, _, _ in MODEL_SETS[t])
        else:
            files.append(t)

    files = list(dict.fromkeys(files))  # de-dupe, preserve order
    console.print(f"[bold]Models to fetch:[/bold] {files}")
    console.print(f"[bold]Cache dir:[/bold] {MODELS_DIR}\n")

    for f in files:
        try:
            download_one(f)
        except Exception as e:
            console.print(f"[red]FAIL[/red] {f}: {e!r}")
            return 1

    console.print("\n[green]All requested models present in cache.[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
