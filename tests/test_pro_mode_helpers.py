"""Pin Pro-mode helpers:

  * suggest_diff_mask_strength clamps to [floor, ceil] and scales with
    measured vocal-band leakage.
  * ChordEvent.source defaults to 'template' and refine_chords tags
    changed events + emits a source histogram.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from backend.app.pipeline.quality import suggest_diff_mask_strength
from backend.app.pipeline.chords import ChordEvent, refine_chords


SR = 22050


def _write(path: Path, mono: np.ndarray) -> None:
    stereo = np.stack([mono, mono], axis=1)
    stereo = np.clip(stereo, -1.0, 1.0)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def _vocal_band_tone(dur=3.0):
    t = np.arange(int(dur * SR)) / SR
    # 1 kHz lands squarely in the vocal band.
    return (0.4 * np.sin(2 * math.pi * 1000 * t)).astype(np.float32)


def test_diff_mask_strength_clean_separation_is_light(tmp_path):
    """Instrumental uncorrelated with vocals → light mask near floor."""
    rng = np.random.default_rng(0)
    inst = tmp_path / "inst.wav"
    voc = tmp_path / "voc.wav"
    _write(inst, (0.3 * rng.standard_normal(int(3 * SR))).astype(np.float32))
    _write(voc, _vocal_band_tone())
    sugg = suggest_diff_mask_strength(inst, voc, target_sr=SR, sample_seconds=3.0)
    assert sugg["strength"] <= 0.5, sugg
    assert sugg["measured_xcorr"] is not None


def test_diff_mask_strength_heavy_bleed_is_aggressive(tmp_path):
    """Instrumental contains a copy of the vocal → heavy mask near ceil."""
    voc_sig = _vocal_band_tone()
    rng = np.random.default_rng(1)
    inst_sig = voc_sig + 0.05 * rng.standard_normal(len(voc_sig)).astype(np.float32)
    inst = tmp_path / "inst.wav"
    voc = tmp_path / "voc.wav"
    _write(inst, inst_sig)
    _write(voc, voc_sig)
    sugg = suggest_diff_mask_strength(inst, voc, target_sr=SR, sample_seconds=3.0)
    assert sugg["strength"] >= 0.6, sugg


def test_diff_mask_strength_clamps_to_range(tmp_path):
    rng = np.random.default_rng(2)
    inst = tmp_path / "inst.wav"; voc = tmp_path / "voc.wav"
    _write(inst, (0.3 * rng.standard_normal(int(3 * SR))).astype(np.float32))
    _write(voc, (0.3 * rng.standard_normal(int(3 * SR))).astype(np.float32))
    sugg = suggest_diff_mask_strength(inst, voc, target_sr=SR, sample_seconds=3.0,
                                      floor=0.35, ceil=0.75)
    assert 0.35 <= sugg["strength"] <= 0.75


def test_chord_event_source_defaults_to_template():
    ev = ChordEvent(0.0, 1.0, "C", "maj", "C", 0.8)
    assert ev.source == "template"


def test_refine_chords_emits_source_histogram():
    events = [
        ChordEvent(0.0, 2.0, "C", "maj", "C", 0.9),
        ChordEvent(2.0, 4.0, "G", "maj", "G", 0.9),
    ]
    report: dict = {}
    # No CREMA / no LLM / no key → only stabilize runs; everything stays
    # 'template'. The histogram must still be present and sum to len.
    refined = refine_chords(
        events, use_crema=False, use_theory=False, use_llm=False,
        report=report,
    )
    assert "source_histogram" in report
    assert sum(report["source_histogram"].values()) == len(refined)
    assert report["source_histogram"].get("template") == len(refined)
