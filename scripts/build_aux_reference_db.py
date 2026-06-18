"""Master build script for the AUX patch reference database.

Aggregates legal, openly-licensed sound sources into a single CLAP-embedded
bank that ``aux_classifier.py`` queries at inference time. Resumable —
rerunning with already-fetched sources skips download/render and only
re-embeds new items.

Sources currently wired (all CC/GPL/CC0):
    * NSynth ``valid`` split (Google Magenta, CC BY 4.0)
    * Arachno SoundFont v1.0 (Maxime Abbey, CC BY-SA 3.0)

To add a source: drop ``scripts/sources/fetch_<name>.py`` with a top-level
``fetch(out_dir) -> list[ReferenceItem]`` and append it to ``SOURCES`` below.

Usage::

    python scripts/build_aux_reference_db.py
    python scripts/build_aux_reference_db.py --skip nsynth
    python scripts/build_aux_reference_db.py --max-per-family 200

Output: ``data/reference_db/aux/``
    embeddings.npy       (N, 512) float32 L2-normalised
    metadata.json        {"categories":[...], "sources":[...], "instruments":[...]}
    MANIFEST.json        build info, source list, totals per category
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# Make ``backend`` and ``scripts`` importable regardless of cwd.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.sources._common import CATEGORIES, ReferenceItem  # noqa: E402


SOURCES: list[str] = ["arachno", "arachno_aug", "nsynth"]


def _run_source(name: str, raw_dir: Path, **kwargs) -> list[ReferenceItem]:
    """Dispatch to ``scripts.sources.fetch_<name>.fetch``."""
    mod = __import__(f"scripts.sources.fetch_{name}", fromlist=["fetch"])
    return list(mod.fetch(raw_dir / name, **kwargs))


def _embed_items(items: list[ReferenceItem], batch_log_every: int = 50) -> np.ndarray:
    """Compute one normalised 512-dim CLAP embedding per item."""
    from backend.app.pipeline.aux_classifier import _embed_audio
    import soundfile as sf

    N = len(items)
    emb = np.zeros((N, 512), dtype=np.float32)
    last_log = time.time()
    failures = 0
    for i, it in enumerate(items):
        try:
            audio, sr = sf.read(str(it.wav_path), dtype="float32", always_2d=False)
            emb[i] = _embed_audio(audio, sr)
        except Exception as e:
            failures += 1
            if failures < 5:
                print(f"  ! embed failed for {it.wav_path.name}: {e!r}")
        if (i + 1) % batch_log_every == 0 or i == N - 1:
            now = time.time()
            rate = batch_log_every / max(1e-6, now - last_log)
            print(f"  [{i + 1}/{N}] {rate:.1f}/s")
            last_log = now
    if failures:
        print(f"  total embed failures: {failures}")
    return emb


def build(
    out_dir: Path,
    raw_dir: Path,
    skip: set[str],
    nsynth_max_per_family: int = 600,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_items: list[ReferenceItem] = []
    used_sources: list[str] = []
    t0 = time.time()

    for src in SOURCES:
        if src in skip:
            print(f"[{src}] skipped by --skip")
            continue
        print(f"\n=== source: {src} ===")
        kwargs: dict = {}
        if src == "nsynth":
            kwargs["max_per_family"] = nsynth_max_per_family
        items = _run_source(src, raw_dir, **kwargs)
        if items:
            all_items.extend(items)
            used_sources.append(src)
        else:
            print(f"[{src}] produced no items (skipped or failed)")

    if not all_items:
        print("\nERROR: no items collected. Bail.", file=sys.stderr)
        sys.exit(2)

    # Per-category census so we know if some labels are starved.
    counts: dict[str, int] = {c: 0 for c in CATEGORIES}
    for it in all_items:
        counts[it.category] = counts.get(it.category, 0) + 1
    print("\n=== per-category counts ===")
    for c in CATEGORIES:
        print(f"  {c:14s}  {counts[c]:6d}")

    print(f"\n=== embedding {len(all_items)} items with CLAP ===")
    emb = _embed_items(all_items)

    # Drop rows that ended up all-zero (embed failed).
    keep_mask = np.any(emb != 0, axis=1)
    if not keep_mask.all():
        n_drop = int((~keep_mask).sum())
        print(f"  dropping {n_drop} failed-embed rows")
        emb = emb[keep_mask]
        all_items = [it for it, k in zip(all_items, keep_mask) if k]

    np.save(out_dir / "embeddings.npy", emb)
    meta = {
        "version": 1,
        "categories": [it.category for it in all_items],
        "sources": [it.source for it in all_items],
        "instruments": [it.instrument for it in all_items],
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8",
    )

    elapsed = time.time() - t0
    manifest = {
        "built_at": int(time.time()),
        "elapsed_sec": elapsed,
        "n_items": len(all_items),
        "sources": used_sources,
        "counts_per_category": {
            c: sum(1 for it in all_items if it.category == c) for c in CATEGORIES
        },
        "embedding_dim": int(emb.shape[1]),
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\n[done] wrote {emb.shape[0]} vectors to {out_dir} in {elapsed/60:.1f} min")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", type=Path, default=ROOT / "data" / "reference_db" / "aux",
        help="output directory for embeddings.npy + metadata.json",
    )
    ap.add_argument(
        "--raw", type=Path, default=ROOT / "data" / "reference_db" / "_raw",
        help="working directory for downloaded + rendered audio",
    )
    ap.add_argument(
        "--skip", nargs="*", default=[],
        help="source names to skip (e.g. --skip nsynth)",
    )
    ap.add_argument(
        "--max-per-family", type=int, default=600,
        help="cap NSynth samples per instrument family (0 = all)",
    )
    args = ap.parse_args()
    build(args.out, args.raw, set(args.skip),
          nsynth_max_per_family=args.max_per_family)


if __name__ == "__main__":
    main()
