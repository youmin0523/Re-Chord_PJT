"""Measure REAL SI-SDR on MUSDB18-7s with the improved ensemble pipeline.

This is the ground-truth answer to "is the separation commercial-grade".
Published SOTA vocal SI-SDR on MUSDB18 is ~12-13 dB; commercial tools
(LALAL.AI, Moises) sit in a similar band. < 8 dB is amateur.

For each track we:
  1. run the 4-model improved ensemble (weighted_mag + phase-coherent)
     on the mixture
  2. compute SI-SDR of our vocals vs the ground-truth vocals stem, and
     our instrumental vs (drums+bass+other) ground-truth sum
  3. optionally run the iterative diff-mask and re-measure the instrumental

Reports mean ± std across tracks, and writes data/qa/sdr_musdb_<date>.json.

Usage:
    uv run python scripts/measure_sdr_musdb.py [--limit N] [--no-diffmask]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "datasets"


def _si_sdr(reference: np.ndarray, estimate: np.ndarray) -> float:
    """Scale-invariant SDR in dB (mono)."""
    if reference.ndim > 1:
        reference = reference.mean(axis=-1)
    if estimate.ndim > 1:
        estimate = estimate.mean(axis=-1)
    n = min(reference.shape[0], estimate.shape[0])
    reference = reference[:n].astype(np.float64)
    estimate = estimate[:n].astype(np.float64)
    reference = reference - reference.mean()
    estimate = estimate - estimate.mean()
    denom = (reference * reference).sum() + 1e-12
    proj = (estimate * reference).sum() / denom * reference
    noise = estimate - proj
    return float(10.0 * np.log10((proj * proj).sum() / ((noise * noise).sum() + 1e-12)))


def _find_tracks(root: Path) -> list[Path]:
    """Find MUSDB-shaped track dirs with mixture + stems.

    MUSDB18-7-WAV layout: <root>/<split>/<track>/{mixture,vocals,drums,
    bass,other}.wav. We accept any dir containing mixture.wav + vocals.wav.
    """
    tracks: list[Path] = []
    for p in root.rglob("mixture.wav"):
        d = p.parent
        if (d / "vocals.wav").exists():
            tracks.append(d)
    return sorted(tracks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=12,
                    help="number of tracks to measure (default 12)")
    ap.add_argument("--no-diffmask", action="store_true")
    ap.add_argument("--root", default=None,
                    help="MUSDB root (default: auto-find under data/datasets)")
    ap.add_argument("--vocal-specialist", default=None,
                    help="extra model alias added to the VOCAL ensemble only "
                         "(e.g. melband_kim_ft2_bleedless) to lift vocal SDR")
    args = ap.parse_args()

    if args.root:
        root = Path(args.root)
    else:
        # Auto-locate the extracted MUSDB18-7s.
        root = DATA / "musdb18_7s"
        if not root.exists():
            cands = list(DATA.rglob("mixture.wav"))
            root = cands[0].parent.parent.parent if cands else root

    tracks = _find_tracks(root)
    if not tracks:
        print(f"[fatal] no MUSDB-shaped tracks under {root}")
        return 1
    tracks = tracks[: args.limit]
    print(f"[info] measuring {len(tracks)} tracks from {root}")

    import soundfile as sf
    from backend.app.pipeline.separate import separate_two_stem, MODELS
    from backend.app.pipeline.ensemble import (
        ensemble_stems, apply_diff_mask_iterative, weight_for_model,
    )
    from backend.app.pipeline.quality import suggest_diff_mask_strength
    from backend.app.core.paths import ensure_dir

    model_aliases = ["mdx23c_instvoc_hq", "bs_roformer_1297",
                     "htdemucs_ft", "melband_kim_inst_v2"]
    work = ROOT / "data" / "work" / "sdr_musdb"
    ensure_dir(work)

    voc_sdrs, inst_sdrs, inst_dm_sdrs = [], [], []
    per_track = []
    t0 = time.perf_counter()

    for i, td in enumerate(tracks):
        name = td.name
        mix = td / "mixture.wav"
        print(f"\n[{i+1}/{len(tracks)}] {name}", flush=True)
        inst_sources, voc_sources = [], []
        voc_weights, inst_weights = [], []
        run_aliases = list(model_aliases)
        if args.vocal_specialist:
            run_aliases.append(args.vocal_specialist)
        for alias in run_aliases:
            fn = MODELS.get(alias, alias)
            try:
                r = separate_two_stem(mix, f"sdr_{name}_{alias}", fn)
            except Exception as e:
                print(f"  ! {alias} failed: {e!r}")
                continue
            w = weight_for_model(alias)
            # The vocal specialist contributes to the VOCAL ensemble only —
            # adding it to the instrumental ensemble could pull the inst SDR
            # the wrong way, so we keep instrumental on the original 4 models.
            if "vocals" in r.stems:
                voc_sources.append(r.stems["vocals"]); voc_weights.append(w)
            if alias != args.vocal_specialist and "instrumental" in r.stems:
                inst_sources.append(r.stems["instrumental"]); inst_weights.append(w)
        if not voc_sources or not inst_sources:
            print("  ! no stems; skip")
            continue

        vp = work / f"{name}_voc.wav"
        ip = work / f"{name}_inst.wav"
        ensemble_stems(voc_sources, vp, "weighted_mag", 44100, "lr",
                       weights=voc_weights, phase_coherent=True)
        ensemble_stems(inst_sources, ip, "weighted_mag", 44100, "lr",
                       weights=inst_weights, phase_coherent=True)

        # Ground truth.
        gt_voc, _ = sf.read(str(td / "vocals.wav"), dtype="float32", always_2d=True)
        # Instrumental GT = mixture - vocals (exact).
        gt_mix, _ = sf.read(str(mix), dtype="float32", always_2d=True)
        n = min(gt_mix.shape[0], gt_voc.shape[0])
        gt_inst = gt_mix[:n] - gt_voc[:n]

        est_voc, _ = sf.read(str(vp), dtype="float32", always_2d=True)
        est_inst, _ = sf.read(str(ip), dtype="float32", always_2d=True)

        v_sdr = _si_sdr(gt_voc, est_voc)
        i_sdr = _si_sdr(gt_inst, est_inst)
        voc_sdrs.append(v_sdr); inst_sdrs.append(i_sdr)
        row = {"track": name, "voc_sdr": round(v_sdr, 2), "inst_sdr": round(i_sdr, 2)}

        if not args.no_diffmask:
            sugg = suggest_diff_mask_strength(ip, vp, 44100, 7.0)
            dp = work / f"{name}_inst_dm.wav"
            apply_diff_mask_iterative(ip, vp, dp, target_sr=44100, passes=2,
                                      strength=sugg["strength"], decay=0.7)
            est_inst_dm, _ = sf.read(str(dp), dtype="float32", always_2d=True)
            i_dm_sdr = _si_sdr(gt_inst, est_inst_dm)
            inst_dm_sdrs.append(i_dm_sdr)
            row["inst_sdr_diffmask"] = round(i_dm_sdr, 2)

        per_track.append(row)
        extra = f", inst+dm={row.get('inst_sdr_diffmask')}" if 'inst_sdr_diffmask' in row else ""
        print(f"  voc_sdr={v_sdr:.2f}dB  inst_sdr={i_sdr:.2f}dB{extra}")

    def _stat(xs):
        return {"mean": round(float(np.mean(xs)), 2),
                "std": round(float(np.std(xs)), 2),
                "min": round(float(np.min(xs)), 2),
                "max": round(float(np.max(xs)), 2), "n": len(xs)} if xs else None

    report = {
        "date": dt.date.today().isoformat(),
        "dataset": str(root),
        "models": model_aliases,
        "vocal_si_sdr": _stat(voc_sdrs),
        "instrumental_si_sdr": _stat(inst_sdrs),
        "instrumental_si_sdr_diffmask": _stat(inst_dm_sdrs),
        "per_track": per_track,
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "reference": "Published SOTA vocal SI-SDR on full MUSDB18 ~12-13 dB",
    }
    out = ROOT / "data" / "qa" / f"sdr_musdb_{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 50)
    print(f"VOCAL  SI-SDR : {report['vocal_si_sdr']}")
    print(f"INSTR  SI-SDR : {report['instrumental_si_sdr']}")
    print(f"INSTR+dm SI-SDR: {report['instrumental_si_sdr_diffmask']}")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
