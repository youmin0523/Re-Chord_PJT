"""Qualitative real-audio probe of chord-tension + AUX on a cached worship
instrumental. No ground-truth labels exist for this song, so this reports
BEHAVIOUR (what fires, distribution, confidence) — not an accuracy %.
"""
from __future__ import annotations
import sys, json, tempfile
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

import backend.app.pipeline._numpy_compat  # noqa: F401  (madmom shim first)

SRC = Path("data/stems/49a819709c6c/ensemble_min/instrumental.wav")
_a = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
_b = float(sys.argv[2]) if len(sys.argv) > 2 else 135.0
SLICE = (_a, _b)

def main() -> None:
    info = sf.info(str(SRC))
    sr = info.samplerate
    y, _ = sf.read(str(SRC), start=int(SLICE[0]*sr), stop=int(SLICE[1]*sr))
    tmp = Path(tempfile.gettempdir()) / "probe_slice.wav"
    sf.write(str(tmp), y, sr)
    dur = len(y)/sr
    print(f"# Real worship instrumental slice: {SRC.name} [{SLICE[0]:.0f}-{SLICE[1]:.0f}]s, {dur:.1f}s @ {sr}Hz\n")

    # ── 1. CHORD + TENSION (full production refine path) ──────────────
    from backend.app.pipeline.chords import analyze_chords, refine_chords as _refine
    events = analyze_chords(tmp)
    report: dict = {}
    events = _refine(
        events, key_root="?", key_mode="major", audio_path=tmp,
        downbeats_sec=[], use_crema=True, use_theory=True, use_llm=False,
        report=report,
    )
    labels = [e.label for e in events if e.label not in ("N", "?")]
    uniq = sorted(set(labels))
    def has(sub): return sum(1 for l in labels if sub in l)
    sevenths = sum(1 for l in labels if l.endswith("7") or "maj7" in l or "m7" in l)
    exts = sum(1 for l in labels if any(x in l for x in ("9","11","13")))
    adds = sum(1 for l in labels if "add" in l or l.endswith("6"))
    sus  = sum(1 for l in labels if "sus" in l)
    alts = sum(1 for l in labels if any(x in l for x in ("b9","#9","#11","#5","b13","alt","b5")))
    print("## CHORD + TENSION (real audio)")
    print(f"refine stages run: {report.get('stages_run')}  skipped: {[s.get('stage') if isinstance(s,dict) else s for s in report.get('stages_skipped',[])]}")
    print(f"total chords: {len(labels)}  unique: {len(uniq)}")
    print(f"unique labels: {uniq}")
    print(f"with 7th: {sevenths}  | 9/11/13: {exts}  | add/6: {adds}  | sus: {sus}  | altered: {alts}")
    rich = sevenths+exts+adds+sus+alts
    print(f"→ {rich}/{len(labels)} chords carry a 7th/extension/sus/alt "
          f"({100*rich/max(1,len(labels)):.0f}% beyond plain triad)\n")

    # ── 2. AUX timbre classification (real audio) ─────────────────────
    from backend.app.pipeline.sections import analyze_sections
    from backend.app.pipeline.aux_classifier import classify_measures
    from backend.app.config import settings
    sec = analyze_sections(tmp)
    downbeats = list(sec.beat_grid.downbeats_sec)
    db_dir = settings.data_dir / "reference_db" / "aux"
    res = classify_measures(
        audio_path=tmp, downbeats_sec=downbeats, duration_sec=dur,
        db_dir=db_dir if db_dir.exists() else None,
        measures_per_window=1, top_k=16,
    )
    cands = res.candidates
    patches = Counter(c.patch for c in cands)
    confs = [c.confidence for c in cands]
    weak = {"epiano","synth_lead","fx"}
    weak_hits = sum(1 for c in cands if c.patch in weak)
    print("## AUX TIMBRE (real audio)")
    print(f"mode: {res.mode}  | reference DB size: {res.db_size}  | measures classified: {len(cands)}")
    print(f"patch distribution: {dict(patches.most_common())}")
    if confs:
        print(f"confidence: mean={np.mean(confs):.3f}  median={np.median(confs):.3f}  "
              f"min={np.min(confs):.3f}  max={np.max(confs):.3f}")
    print(f"weak-category predictions (epiano/synth_lead/fx): {weak_hits}/{len(cands)}")
    print(f"merged cue ranges: {len(res.cues)}")
    if res.cues[:6]:
        print("sample cues:", [(c.get('start_measure'),c.get('end_measure'),c.get('patch')) for c in res.cues[:6]])

if __name__ == "__main__":
    main()
