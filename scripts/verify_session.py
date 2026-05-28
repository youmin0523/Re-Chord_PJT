"""Session 12 verification — runs through every symbol/signature added in
the worship-features + score-improvements batch and prints PASS/FAIL.

Pure import + introspection; no audio I/O.
"""
from __future__ import annotations

import inspect
import sys

OK, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    results.append((OK if condition else FAIL, label, detail))


# ── A. Main app ───────────────────────────────────────────────────────────
from backend.app.main import app, _scheduled_prewarm_loop, ops_prewarm
n = sum(1 for _ in app.routes)
check("FastAPI app loads", n >= 40, f"{n} routes")
check("ops_prewarm exists", callable(ops_prewarm))
check("scheduled prewarm loop exists", callable(_scheduled_prewarm_loop))

# ── B. analyze.py ────────────────────────────────────────────────────────
from backend.app.pipeline.analyze import detect_modulations, _ev_get
check("analyze.detect_modulations", callable(detect_modulations))
check("analyze._ev_get duck-type helper", callable(_ev_get))

# Quick smoke: empty input returns empty list
check("detect_modulations([]) == []", detect_modulations([]) == [])

# ── C. score.py ──────────────────────────────────────────────────────────
from backend.app.pipeline.score import (
    _attach_tempo_mark, _attach_section_markers, _tempo_referent_for_meter,
    _extract_measure_timemap, build_score, midi_to_musicxml, ScoreResult,
)
sig_b = inspect.signature(build_score).parameters
sig_m = inspect.signature(midi_to_musicxml).parameters
check("build_score has time_signature kwarg", "time_signature" in sig_b)
check("build_score has sections kwarg", "sections" in sig_b)
check("midi_to_musicxml has time_signature kwarg", "time_signature" in sig_m)
check("midi_to_musicxml has sections kwarg", "sections" in sig_m)
check(
    "ScoreResult.timemap_path field",
    "timemap_path" in ScoreResult.__dataclass_fields__,
    str(ScoreResult.__dataclass_fields__["timemap_path"].default),
)

# Meter logic spot-checks
ref_4, sc_4 = _tempo_referent_for_meter("4/4")
ref_12, sc_12 = _tempo_referent_for_meter("12/8")
ref_2_2, sc_2_2 = _tempo_referent_for_meter("2/2")
check("4/4 → quarter referent", ref_4.quarterLength == 1.0 and sc_4 == 1.0,
      f"ql={ref_4.quarterLength} scale={sc_4}")
check("12/8 → dotted-quarter referent", ref_12.quarterLength == 1.5 and abs(sc_12 - (1/1.5)) < 1e-6,
      f"ql={ref_12.quarterLength} scale={sc_12:.4f}, 120bpm → {120*sc_12:.1f}")
check("2/2 → half referent", ref_2_2.quarterLength == 2.0 and sc_2_2 == 0.5,
      f"ql={ref_2_2.quarterLength} scale={sc_2_2}")

# ── D. transcribe.py ─────────────────────────────────────────────────────
from backend.app.pipeline.transcribe import TranscribeResult
check("TranscribeResult.low_midi field", "low_midi" in TranscribeResult.__dataclass_fields__)
check("TranscribeResult.high_midi field", "high_midi" in TranscribeResult.__dataclass_fields__)

# ── E. lyrics.py ─────────────────────────────────────────────────────────
from backend.app.pipeline.lyrics import save_edited_lyrics
sig_l = inspect.signature(save_edited_lyrics).parameters
check("save_edited_lyrics has translations kwarg", "translations" in sig_l)

# ── F. orchestrator.py ──────────────────────────────────────────────────
from backend.app.workers.orchestrator import _mirror_artifacts_to_storage
check("orchestrator._mirror_artifacts_to_storage", callable(_mirror_artifacts_to_storage))

from backend.app.core.jobs import Job
check("Job.storage_urls field", "storage_urls" in Job.__dataclass_fields__)

# ── G. spatial.py DSD probe ─────────────────────────────────────────────
try:
    from backend.app.pipeline.spatial import dsd_supported
    check("spatial.dsd_supported helper", callable(dsd_supported))
except Exception as e:
    check("spatial.dsd_supported helper", False, repr(e))


# ── Report ───────────────────────────────────────────────────────────────
passed = sum(1 for r in results if r[0] == OK)
total = len(results)
for status, label, detail in results:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{suffix}")
print(f"\n  --- {passed}/{total} checks passed ---")
sys.exit(0 if passed == total else 1)
