"""Pin the dynamics + articulation auto-attach behaviour.

These tests ensure that:
  * a quiet measure gets a soft marking (p/mp)
  * a loud measure gets a loud marking (f/ff)
  * the marking only fires on *change* (not duplicated bar to bar)
  * very short notes get staccato
  * long notes get tenuto
  * per-note velocity spikes get accent
"""

from __future__ import annotations

from music21 import (
    articulations,
    dynamics as m21_dyn,
    instrument,
    meter,
    note as m21_note,
    stream,
)

from backend.app.pipeline.score import _attach_dynamics_and_articulation


def _build_score(measures: list[list[tuple[int, float]]]):
    """Construct a single-part score from a list of measures, each given
    as a list of (velocity, quarterLength) tuples.
    """
    s = stream.Score()
    p = stream.Part()
    p.insert(0, instrument.Piano())
    p.insert(0, meter.TimeSignature("4/4"))
    for mi, m_notes in enumerate(measures, start=1):
        m = stream.Measure(number=mi)
        for v, ql in m_notes:
            n = m21_note.Note("C4", quarterLength=ql)
            n.volume.velocity = v
            m.append(n)
        p.append(m)
    s.insert(0, p)
    return s


def _dyn_values(m):
    return [d.value for d in m.recurse().getElementsByClass(m21_dyn.Dynamic)]


def _has_articulation(n, kind):
    return any(isinstance(a, kind) for a in getattr(n, "articulations", []))


def test_quiet_measure_gets_soft_marking():
    s = _build_score([[(50, 1.0), (50, 1.0), (50, 1.0), (50, 1.0)]])
    _attach_dynamics_and_articulation(s)
    m1 = s.parts[0].getElementsByClass("Measure")[0]
    assert _dyn_values(m1) == ["p"]


def test_loud_measure_gets_loud_marking():
    # Velocity 110 lands in the 'ff' band (105 < v <= 118 by the
    # LADDER in _attach_dynamics_and_articulation).
    s = _build_score([[(110, 1.0), (110, 1.0), (110, 1.0), (110, 1.0)]])
    _attach_dynamics_and_articulation(s)
    m1 = s.parts[0].getElementsByClass("Measure")[0]
    assert _dyn_values(m1) == ["ff"]


def test_forte_threshold_emits_f():
    # Velocity 100 is squarely in the 'f' band (90 < v <= 105).
    s = _build_score([[(100, 1.0), (100, 1.0), (100, 1.0), (100, 1.0)]])
    _attach_dynamics_and_articulation(s)
    m1 = s.parts[0].getElementsByClass("Measure")[0]
    assert _dyn_values(m1) == ["f"]


def test_marking_emitted_only_on_change():
    """Two identical measures get one marking, not two."""
    s = _build_score([
        [(60, 1.0), (60, 1.0), (60, 1.0), (60, 1.0)],
        [(60, 1.0), (60, 1.0), (60, 1.0), (60, 1.0)],
    ])
    _attach_dynamics_and_articulation(s)
    m1, m2 = s.parts[0].getElementsByClass("Measure")[:2]
    assert _dyn_values(m1) == ["p"]
    assert _dyn_values(m2) == []


def test_short_notes_get_staccato():
    s = _build_score([[(80, 0.2), (80, 0.2), (80, 0.2), (80, 0.2),
                       (80, 0.2), (80, 0.2)]])
    _attach_dynamics_and_articulation(s)
    notes = list(s.parts[0].recurse().notes)
    assert all(_has_articulation(n, articulations.Staccato) for n in notes)


def test_long_notes_get_tenuto():
    s = _build_score([[(80, 2.0), (80, 2.0)]])
    _attach_dynamics_and_articulation(s)
    notes = list(s.parts[0].recurse().notes)
    assert all(_has_articulation(n, articulations.Tenuto) for n in notes)


def test_accent_on_per_note_velocity_spike():
    """A note with velocity > 1.3 × bar mean gets an Accent."""
    # Mean = (50+50+50+110)/4 = 65; the v=110 note is at 1.69× mean → accent.
    s = _build_score([[(50, 1.0), (50, 1.0), (50, 1.0), (110, 1.0)]])
    _attach_dynamics_and_articulation(s)
    notes = list(s.parts[0].recurse().notes)
    accents = [n for n in notes if _has_articulation(n, articulations.Accent)]
    assert len(accents) == 1
    assert accents[0].volume.velocity == 110


def test_returns_stats():
    s = _build_score([[(50, 1.0)], [(110, 0.2), (110, 2.0)]])
    stats = _attach_dynamics_and_articulation(s)
    # 2 measure markings (p, f) + 1 staccato (0.2 ql) + 1 tenuto (2.0 ql).
    assert stats["measures_marked"] == 2
    assert stats["notes_articulated"] >= 2
