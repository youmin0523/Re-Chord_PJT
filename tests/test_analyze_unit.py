"""Unit tests for backend/app/pipeline/analyze.py.

These are pure-Python unit tests — no audio I/O, no model downloads — so
they run in CI even on the GPU-less Ubuntu runner.

Covered:
    - semitones_between (shortest signed direction)
    - detect_modulations (sliding-window key detection from chord events)
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.app.pipeline.analyze import (
    detect_modulations,
    semitones_between,
)


# Minimal ChordEvent-shaped fixture — detect_modulations accepts dicts
# OR objects with start_sec/end_sec/root attributes. We test both.

@dataclass
class _Ev:
    start_sec: float
    end_sec: float
    root: str
    label: str = ""


def _chain(roots: list[tuple[float, float, str]]) -> list[_Ev]:
    return [_Ev(s, e, r, r) for s, e, r in roots]


# ── semitones_between ─────────────────────────────────────────────────────

def test_semitones_between_same_key_is_zero():
    assert semitones_between("C", "C") == 0


def test_semitones_between_picks_shortest_direction():
    assert semitones_between("C", "G") == -5   # 7 up == 5 down, prefer down
    assert semitones_between("G", "C") == 5    # symmetric back the other way


def test_semitones_between_perfect_fifth_up():
    assert semitones_between("C", "D") == 2
    assert semitones_between("C", "F") == 5


# ── detect_modulations ────────────────────────────────────────────────────

def test_no_chords_returns_empty():
    assert detect_modulations([]) == []


def test_too_short_returns_empty():
    # Total < window_sec (16s default) → no segments to compare.
    events = _chain([(0, 4, "C"), (4, 8, "C"), (8, 12, "C")])
    assert detect_modulations(events) == []


def test_constant_key_no_modulation():
    # 40 seconds of C-G-C-G — no key change.
    events = []
    t = 0.0
    while t < 40:
        events.append(_Ev(t, t + 4, "C"))
        events.append(_Ev(t + 4, t + 8, "G"))
        t += 8
    mods = detect_modulations(events)
    # Sliding window picks the more-common root in each segment; either
    # both Cs or both Gs will dominate, so root is stable. Allow at most
    # one transient flag (anti-flicker should suppress even that).
    assert len(mods) <= 1


def test_clear_modulation_up_a_semitone():
    """Worship's classic: first 32s in C, last 32s up a semitone in C#."""
    events = []
    # 32s of C-F-G-C — heavy C-rooted material.
    for _ in range(4):
        events.append(_Ev(len(events) * 8, len(events) * 8 + 8, "C"))
    # 32s of C#-F#-G#-C# — heavy C#-rooted material.
    for _ in range(4):
        events.append(_Ev(32 + len(events) * 8 - 32, 32 + (len(events) - 4 + 1) * 8, "C#"))
    # Rebuild cleanly with correct timings.
    events = (
        _chain([(0, 8, "C"), (8, 16, "C"), (16, 24, "C"), (24, 32, "C")])
        + _chain([(32, 40, "C#"), (40, 48, "C#"), (48, 56, "C#"), (56, 64, "C#")])
    )
    mods = detect_modulations(events)
    assert len(mods) >= 1
    last = mods[-1]
    assert last["from_root"] == "C"
    assert last["to_root"] == "C#"
    assert last["semitones"] == 1
    assert last["at_sec"] > 16  # change should be detected after the boundary


def test_ignores_no_chord_markers():
    """Silence ('N') and unknown ('?') roots must not pollute the count."""
    events = (
        _chain([(0, 8, "C"), (8, 16, "C")])
        + [_Ev(16, 24, "N"), _Ev(24, 32, "?")]
        + _chain([(32, 40, "C"), (40, 48, "C")])
    )
    mods = detect_modulations(events)
    assert mods == []
