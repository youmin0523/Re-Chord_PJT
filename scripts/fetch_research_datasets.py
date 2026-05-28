"""Fetch open / academic / CC-licensed music datasets for training + regression.

NO copyrighted catalogues. Every entry here is either:
  - academic public release (MUSDB18, MAESTRO, GTZAN, GuitarSet)
  - Creative Commons / public domain (FMA-small, GiantMIDI-Piano)
  - Apache-2.0 / MIT licensed (NSynth — already covered by AUX builder)

All downloads land in ``data/datasets/<name>/`` and are idempotent —
re-running skips files that are already on disk.

Usage::

    python scripts/fetch_research_datasets.py                  # all defaults
    python scripts/fetch_research_datasets.py --only musdb18 gtzan
    python scripts/fetch_research_datasets.py --skip maestro   # skip large ones
    python scripts/fetch_research_datasets.py --list           # just print plan

Defaults skip the very large MAESTRO download (>100 GB) — pass
``--include maestro`` to opt in.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_ROOT = ROOT / "data" / "datasets"


@dataclass
class Dataset:
    name: str
    url: str
    filename: str
    size_mb_estimate: int
    license: str
    notes: str
    archive_format: str = "zip"          # "zip" | "tar.gz" | "raw"
    default_on: bool = True              # included when no --only/--skip


DATASETS: list[Dataset] = [
    # MUSDB18-7s — 7-second clips of MUSDB18, ~150 MB. Drop-in for our
    # tests/test_separation_regression.py SI-SDR baseline.
    Dataset(
        name="musdb18_7s",
        url="https://zenodo.org/records/3270814/files/MUSDB18-7-WAV.zip",
        filename="MUSDB18-7-WAV.zip",
        size_mb_estimate=150,
        license="MUSDB18 license (research-only)",
        notes="7s mixture+stem clips, 100 tracks. For SI-SDR regression.",
        archive_format="zip",
    ),
    # GTZAN — 1000 30-second clips, 10 genres. Old but standard.
    Dataset(
        name="gtzan",
        url="http://opihi.cs.uvic.ca/sound/genres.tar.gz",
        filename="gtzan_genres.tar.gz",
        size_mb_estimate=1200,
        license="Academic (research-only)",
        notes="10 genres × 100 tracks × 30s. Genre/style classifier baseline.",
        archive_format="tar.gz",
    ),
    # GuitarSet — 360 short solo-guitar excerpts + MIDI annotations.
    Dataset(
        name="guitarset",
        url="https://zenodo.org/records/3371780/files/audio_mono-pickup_mix.zip",
        filename="guitarset_audio_mono.zip",
        size_mb_estimate=900,
        license="CC BY 4.0",
        notes="Guitar audio + per-string F0 ground truth. Use for TAB inference.",
        archive_format="zip",
    ),
    # GiantMIDI-Piano — 10,855 classical piano MIDIs.
    Dataset(
        name="giantmidi_piano",
        url="https://github.com/bytedance/GiantMIDI-Piano/releases/download/v1.0/midis_v1.0.zip",
        filename="giantmidi_v1.0.zip",
        size_mb_estimate=900,
        license="Apache-2.0",
        notes="ByteDance Research, 10,855 piano MIDIs. Polyphonic piano fine-tune.",
        archive_format="zip",
    ),
    # FMA-small — 8000 30-second clips, 8 balanced genres.
    Dataset(
        name="fma_small",
        url="https://os.unil.cloud.switch.ch/fma/fma_small.zip",
        filename="fma_small.zip",
        size_mb_estimate=7900,
        license="CC BY 4.0 (per-track metadata)",
        notes="Free Music Archive small subset. 8000 × 30s, 8 genres.",
        archive_format="zip",
    ),
    # MAESTRO v3 — piano audio paired with aligned MIDI. ~120 GB → off by default.
    Dataset(
        name="maestro",
        url="https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0.zip",
        filename="maestro-v3.0.0.zip",
        size_mb_estimate=120000,
        license="CC BY-NC-SA 4.0",
        notes="Piano performance + aligned MIDI. ~120 GB. Off by default — pass --include maestro.",
        archive_format="zip",
        default_on=False,
    ),
]


def _human_size(mb: int) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb} MB"


def _download(ds: Dataset, dest_dir: Path) -> Path | None:
    """Download (with resume if possible) and return the local path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / ds.filename
    # Skip if a sufficiently-large file is already there.
    threshold = max(1, int(ds.size_mb_estimate * 0.8)) * 1024 * 1024
    if out.exists() and out.stat().st_size >= threshold:
        print(f"  cached ({_human_size(out.stat().st_size // (1024 * 1024))})")
        return out
    try:
        print(f"  downloading … (~{_human_size(ds.size_mb_estimate)})")
        urllib.request.urlretrieve(ds.url, str(out))
    except Exception as e:
        print(f"  ! failed: {e}")
        # Don't leave a half-file lying around.
        if out.exists() and out.stat().st_size < threshold:
            try: out.unlink()
            except Exception: pass
        return None
    return out


def _extract(ds: Dataset, archive_path: Path, dest_dir: Path) -> bool:
    """Unpack the archive in-place. Idempotent — bails if anything is already there."""
    extract_marker = dest_dir / ".extracted"
    if extract_marker.exists():
        print("  already extracted")
        return True
    try:
        if ds.archive_format == "zip":
            import zipfile
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(dest_dir)
        elif ds.archive_format == "tar.gz":
            import tarfile
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(dest_dir)
        elif ds.archive_format == "raw":
            pass                              # nothing to do
        else:
            print(f"  unknown archive_format: {ds.archive_format}")
            return False
        extract_marker.touch()
        print(f"  extracted → {dest_dir}")
        return True
    except Exception as e:
        print(f"  ! extract failed: {e}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to these dataset names")
    ap.add_argument("--skip", nargs="*", default=[],
                    help="skip these dataset names")
    ap.add_argument("--include", nargs="*", default=[],
                    help="include datasets that are default_on=False")
    ap.add_argument("--list", action="store_true", help="just list the plan and exit")
    ap.add_argument("--no-extract", action="store_true",
                    help="download archives but skip extraction")
    args = ap.parse_args()

    queue: list[Dataset] = []
    for ds in DATASETS:
        if args.only is not None:
            if ds.name in args.only:
                queue.append(ds)
            continue
        if ds.name in args.skip:
            continue
        if not ds.default_on and ds.name not in args.include:
            continue
        queue.append(ds)

    if args.list or not queue:
        for ds in queue:
            print(f"  {ds.name:18s}  ~{_human_size(ds.size_mb_estimate)}  [{ds.license}]")
            print(f"  {' ' * 18}  {ds.notes}")
        if not queue:
            print("(no datasets selected)")
        if args.list:
            return

    total_mb = sum(ds.size_mb_estimate for ds in queue)
    print(f"\nplan: {len(queue)} datasets, ~{_human_size(total_mb)} total")
    print(f"target: {DATA_ROOT}")
    print()

    for ds in queue:
        print(f"=== {ds.name} ({_human_size(ds.size_mb_estimate)}) ===")
        dest = DATA_ROOT / ds.name
        archive = _download(ds, dest)
        if archive is None:
            continue
        if not args.no_extract:
            _extract(ds, archive, dest)

    print("\ndone.")


if __name__ == "__main__":
    main()
