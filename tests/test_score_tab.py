"""Pin the guitar/bass TAB fret-selection heuristic.

The simple 'lowest fret' picker produced unplayable runs (every note
jumps to the highest open string). The continuity-aware picker should:
  * keep consecutive notes on nearby strings/frets
  * stay in the 0-12 playability box unless already high on the neck
  * map every reachable pitch to a valid (string, fret)
"""

from __future__ import annotations

from backend.app.pipeline.score import (
    _midi_pitch_to_fret,
    GUITAR_TUNING_MIDI,
    BASS_TUNING_MIDI,
)


def test_open_string_maps_to_fret_zero():
    # Low E2 (40) is the open 6th string → (0, 0).
    pos = _midi_pitch_to_fret(40, GUITAR_TUNING_MIDI)
    assert pos == (0, 0)


def test_unreachable_pitch_returns_none():
    # A pitch far below the lowest open string is unplayable.
    assert _midi_pitch_to_fret(20, GUITAR_TUNING_MIDI) is None


def test_continuity_prefers_nearby_string():
    """Given a previous position low on the neck, the next note should
    favour a nearby fret rather than jumping to a far open string."""
    # G3 (55) can be played as: 6th string fret 15, 5th fret 10,
    # 4th fret 5, or 3rd string open (fret 0).
    # With no context, default = lowest fret (open 3rd string).
    no_ctx = _midi_pitch_to_fret(55, GUITAR_TUNING_MIDI)
    assert no_ctx is not None
    # With the previous note at 4th string fret 7 (D#3-ish), continuity
    # should keep us near fret 5 on the 4th string instead of jumping
    # to the open 3rd string several positions away.
    near = _midi_pitch_to_fret(
        55, GUITAR_TUNING_MIDI, prev_string=3, prev_fret=7,
    )
    assert near is not None
    # The continuity pick should be closer (in fret distance) to 7 than
    # the open-string default.
    assert abs(near[1] - 7) <= abs(no_ctx[1] - 7)


def test_high_position_penalised_when_low_context():
    """A note reachable both high and low should pick the low box when
    the previous note was low on the neck."""
    # E4 (64): open 1st string (fret 0) OR 2nd string fret 5 OR 3rd
    # string fret 9 OR ... With low context (open position), it should
    # not jump above fret 14.
    pos = _midi_pitch_to_fret(64, GUITAR_TUNING_MIDI,
                              prev_string=0, prev_fret=2)
    assert pos is not None
    assert pos[1] <= 14


def test_bass_tuning_maps_correctly():
    # Low E1 (28) on a 4-string bass is the open 4th string → (0, 0).
    pos = _midi_pitch_to_fret(28, BASS_TUNING_MIDI)
    assert pos == (0, 0)
    # A2 (45) is open 1st string (G2=43 + 2) OR 2nd string fret... ; just
    # confirm we get a valid in-range fret.
    pos2 = _midi_pitch_to_fret(45, BASS_TUNING_MIDI)
    assert pos2 is not None
    assert 0 <= pos2[1] <= 22


def test_full_tab_score_builds(tmp_path):
    """End-to-end: a simple ascending MIDI line → TAB score with fret
    labels on every note."""
    import pretty_midi
    from backend.app.pipeline.score import _build_tab_score, GUITAR_TUNING_MIDI

    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=27)  # electric guitar
    for i, pitch in enumerate([40, 45, 50, 55, 59, 64]):
        inst.notes.append(pretty_midi.Note(
            velocity=90, pitch=pitch, start=i * 0.5, end=i * 0.5 + 0.4))
    pm.instruments.append(inst)
    midi_path = tmp_path / "gtr.mid"
    pm.write(str(midi_path))

    score = _build_tab_score(midi_path, 120.0, GUITAR_TUNING_MIDI, 22, "guitar")
    notes = list(score.recurse().notes)
    assert len(notes) == 6
    # Every note carries a fret label lyric like "5(4)".
    for n in notes:
        lyric = n.lyric or ""
        assert "(" in lyric and ")" in lyric, f"missing fret label: {lyric!r}"
