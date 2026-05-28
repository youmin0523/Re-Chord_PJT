"""Re-measure separation quality on a retained master with the CURRENT
improved pipeline (weighted_mag + phase-coherent ensemble + iterative
diff-mask) and compare the resulting null-test grade to the old one.

This is the first time the ensemble/phase/diff-mask improvements are
exercised on REAL audio (they were only synth-tested before).

Usage:
    uv run python scripts/remeasure_separation.py <job_id>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: remeasure_separation.py <job_id>")
        return 1
    job_id = sys.argv[1]
    master = ROOT / "data" / "work" / job_id / f"master_48000_f32.wav"
    if not master.exists():
        # fall back to any wav in the work dir
        cands = list((ROOT / "data" / "work" / job_id).glob("master*.wav"))
        if not cands:
            print(f"no master found for {job_id}")
            return 1
        master = cands[0]
    print(f"[master] {master}")

    from backend.app.pipeline.separate import separate_two_stem, MODELS
    from backend.app.pipeline.ensemble import (
        ensemble_stems, apply_diff_mask_iterative, weight_for_model,
    )
    from backend.app.pipeline.quality import (
        compute_quality, suggest_diff_mask_strength,
    )
    from backend.app.core.paths import ensure_dir

    # The karaoke/pro default 4-model ensemble (matches core/jobs.py).
    model_aliases = ["mdx23c_instvoc_hq", "bs_roformer_1297",
                     "htdemucs_ft", "melband_kim_inst_v2"]
    work = ROOT / "data" / "work" / job_id / "remeasure"
    ensure_dir(work)

    inst_sources, voc_sources = [], []
    t0 = time.perf_counter()
    for alias in model_aliases:
        fn = MODELS.get(alias, alias)
        print(f"[separate] {alias} ...", flush=True)
        try:
            r = separate_two_stem(master, f"{job_id}_remeasure", fn)
        except Exception as e:
            print(f"  ! {alias} failed: {e!r}")
            continue
        if "instrumental" in r.stems:
            inst_sources.append(r.stems["instrumental"])
        if "vocals" in r.stems:
            voc_sources.append(r.stems["vocals"])
        print(f"  done ({r.elapsed_sec:.1f}s, {r.realtime_factor:.1f}x RT)")

    if not inst_sources or not voc_sources:
        print("no stems produced")
        return 1

    weights = [weight_for_model(a) for a in model_aliases]
    print(f"[ensemble] weighted_mag + phase_coherent, weights={[round(w,2) for w in weights]}")
    inst_path = work / "instrumental.wav"
    voc_path = work / "vocals.wav"
    ensemble_stems(inst_sources, inst_path, "weighted_mag", 48000, "lr",
                   weights=weights[:len(inst_sources)], phase_coherent=True)
    ensemble_stems(voc_sources, voc_path, "weighted_mag", 48000, "lr",
                   weights=weights[:len(voc_sources)], phase_coherent=True)

    # Auto-tuned iterative diff-mask.
    sugg = suggest_diff_mask_strength(inst_path, voc_path, 48000, 30.0)
    print(f"[diff-mask] auto strength={sugg['strength']} ({sugg['reason']})")
    masked = work / "instrumental_masked.wav"
    apply_diff_mask_iterative(inst_path, voc_path, masked, target_sr=48000,
                              passes=2, strength=sugg["strength"], decay=0.7)

    # Quality before vs after diff-mask.
    print("\n=== QUALITY (current improved pipeline) ===")
    q_pre = compute_quality(master, inst_path, voc_path, 48000, 90.0)
    print(f"  ensemble-only : grade={q_pre.grade()}  null={q_pre.null_rms_dbfs:.1f}dB  "
          f"corr={q_pre.reconstruction_corr:.3f}  xcorr={q_pre.voc_inst_xcorr:.3f}")
    q_post = compute_quality(master, masked, voc_path, 48000, 90.0)
    print(f"  + diff-mask   : grade={q_post.grade()}  null={q_post.null_rms_dbfs:.1f}dB  "
          f"corr={q_post.reconstruction_corr:.3f}  xcorr={q_post.voc_inst_xcorr:.3f}")

    # Old grade for comparison.
    import json
    old = ROOT / "data" / "output" / job_id / "quality.json"
    if old.exists():
        od = json.loads(old.read_text(encoding="utf-8"))
        print(f"\n  OLD (2026-05-21): grade={od.get('grade')}  "
              f"null={od.get('null_rms_dbfs'):.1f}dB  "
              f"corr={od.get('reconstruction_corr'):.3f}  "
              f"xcorr={od.get('voc_inst_xcorr'):.3f}")
    print(f"\n[total] {time.perf_counter()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
