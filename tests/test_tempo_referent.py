"""Tests for the meter-aware tempo referent picker.

Worship/CCM frequently uses 12/8 and 6/8 (compound meters) where the
audience-felt beat is the dotted-quarter, not the quarter. The score
header should print ♩. = BPM (not ♩ = BPM) so the printed tempo
matches what readers actually count.

These tests cover the pure-Python helper without booting music21's
notation engine (we just check the returned referent's quarterLength
and the BPM scale factor).
"""

from __future__ import annotations

import pytest

# music21 is heavy — skip cleanly when unavailable in the test env.
try:
    import music21      # noqa: F401
except Exception:
    pytest.skip("music21 not installed", allow_module_level=True)

from backend.app.pipeline.score import _tempo_referent_for_meter


def _ql(referent):
    return float(referent.quarterLength)


# ── simple meters ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("meter", ["4/4", "3/4", "2/4", "5/4", "7/4"])
def test_simple_meter_quarter_referent(meter):
    ref, scale = _tempo_referent_for_meter(meter)
    assert _ql(ref) == 1.0           # quarter note
    assert scale == 1.0              # BPM unchanged


# ── compound meters ───────────────────────────────────────────────────────

@pytest.mark.parametrize("meter", ["6/8", "9/8", "12/8"])
def test_compound_meter_dotted_quarter_referent(meter):
    ref, scale = _tempo_referent_for_meter(meter)
    assert _ql(ref) == 1.5           # dotted-quarter = 1.5 quarter-lengths
    # quarter-pulse BPM divided by 1.5 gives the dotted-quarter pulse,
    # which is what a 12/8 listener feels.
    assert abs(scale - (1.0 / 1.5)) < 1e-6


def test_120_bpm_in_12_8_prints_as_80_dotted_quarter():
    ref, scale = _tempo_referent_for_meter("12/8")
    quarter_bpm = 120.0
    dotted_quarter_bpm = quarter_bpm * scale
    # 120 quarter-pulse → 80 dotted-quarter pulse (what the user counts).
    assert abs(dotted_quarter_bpm - 80.0) < 0.01


# ── cut time ──────────────────────────────────────────────────────────────

def test_alla_breve_half_referent():
    ref, scale = _tempo_referent_for_meter("2/2")
    assert _ql(ref) == 2.0           # half note
    assert scale == 0.5              # quarter-BPM halves to half-note BPM


# ── 3/8-style fast meters fall back to quarter ────────────────────────────

@pytest.mark.parametrize("meter", ["3/8", "6/16", "5/8"])
def test_uncommon_meters_fall_back_to_quarter(meter):
    ref, scale = _tempo_referent_for_meter(meter)
    assert _ql(ref) == 1.0
    assert scale == 1.0


# ── degenerate input ──────────────────────────────────────────────────────

@pytest.mark.parametrize("meter", [None, "", "garbage", "4-4", "4"])
def test_invalid_or_missing_meter_falls_back_to_quarter(meter):
    ref, scale = _tempo_referent_for_meter(meter)
    assert _ql(ref) == 1.0
    assert scale == 1.0
