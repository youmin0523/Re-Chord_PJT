"""Commercial-release accuracy gate.

Reads ``tests/fixtures/accuracy_thresholds.json`` and the latest QA report
under ``data/qa/`` (synth + real-world) and fails CI when a measured metric
falls below its declared 'min'. Warnings (target miss) are printed but
non-fatal.

The threshold file is the source of truth — bumping a number requires a
deliberate commit so accuracy regressions never sneak in unnoticed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = ROOT / "tests" / "fixtures" / "accuracy_thresholds.json"
QA_DIR = ROOT / "data" / "qa"


def _latest_qa(prefix: str) -> dict | None:
    """Return the most recent QA report whose filename starts with prefix."""
    if not QA_DIR.exists():
        return None
    candidates = sorted(QA_DIR.glob(f"{prefix}*.json"))
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_thresholds() -> dict:
    if not THRESHOLDS.exists():
        pytest.skip(f"thresholds file missing: {THRESHOLDS}")
    return json.loads(THRESHOLDS.read_text(encoding="utf-8"))


def _check(metric: str, value: float | None, spec: dict, *, lower_is_better: bool = False) -> tuple[str, str]:
    """Return ('pass'|'warn'|'fail', message). ``spec`` is {min, target, ...}."""
    if value is None:
        return ("skip", f"{metric}: no measurement available")
    mn = spec.get("min")
    tgt = spec.get("target")
    if mn is None:
        return ("skip", f"{metric}: no min defined")
    if lower_is_better:
        if value > mn:
            return ("fail", f"{metric}: {value} > min {mn}")
        if tgt is not None and value > tgt:
            return ("warn", f"{metric}: {value} > target {tgt}")
        return ("pass", f"{metric}: {value} (target {tgt})")
    else:
        if value < mn:
            return ("fail", f"{metric}: {value} < min {mn}")
        if tgt is not None and value < tgt:
            return ("warn", f"{metric}: {value} < target {tgt}")
        return ("pass", f"{metric}: {value} (target {tgt})")


def test_synth_accuracy_meets_threshold():
    thr = _load_thresholds()
    rep = _latest_qa("accuracy_")
    if rep is None:
        pytest.skip("no synth accuracy report under data/qa/accuracy_*.json")

    results: list[tuple[str, str]] = []

    key_acc = (rep.get("key") or {}).get("major_correct")
    results.append(_check("analyze.key_exact_acc", key_acc, thr["analyze"]["key_exact_acc"]))

    bpm = rep.get("bpm") or {}
    bpm_acc = bpm.get("tolerance_4pct_acc")
    results.append(_check("analyze.bpm_within_4pct_acc", bpm_acc, thr["analyze"]["bpm_within_4pct_acc"]))

    onset = rep.get("onset") or {}
    onset_f1 = onset.get("f1_50ms")
    results.append(_check("transcribe.onset_f1_50ms", onset_f1, thr["transcribe"]["onset_f1_50ms"]))

    chord = rep.get("chord") or {}
    chord_acc = chord.get("symbol_acc")
    results.append(_check("chord.f1_simple", chord_acc, thr["chord"]["f1_simple"]))

    failures = [m for s, m in results if s == "fail"]
    for s, m in results:
        prefix = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}[s]
        print(f"[{prefix}] {m}")
    assert not failures, "synth accuracy below release threshold:\n  " + "\n  ".join(failures)


def test_real_world_accuracy_meets_threshold():
    thr = _load_thresholds()
    rep = _latest_qa("real_accuracy_v4_")
    if rep is None:
        pytest.skip("no real-world v4 accuracy report under data/qa/real_accuracy_v4_*.json")

    summary = rep.get("summary") or {}
    results: list[tuple[str, str]] = []

    chord_recall = summary.get("chord_recall_transpose_mean")
    results.append(_check("chord.transposition_invariant_recall", chord_recall,
                          thr["chord"]["transposition_invariant_recall"]))

    # This gate is a BPM plausibility band (50-180), not 8% accuracy — named
    # honestly so a green CI doesn't imply tempo accuracy we never measured.
    bpm_plausible = summary.get("bpm_band_plausible_mean")
    results.append(_check("analyze.bpm_band_plausible_rate", bpm_plausible,
                          thr["analyze"]["bpm_band_plausible_rate"]))

    failures = [m for s, m in results if s == "fail"]
    for s, m in results:
        prefix = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}[s]
        print(f"[{prefix}] {m}")
    assert not failures, "real-world accuracy below release threshold:\n  " + "\n  ".join(failures)
