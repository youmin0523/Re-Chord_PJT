"""Pin the SATB chord-grouped voice assignment.

The key invariant of a readable SATB reduction: at every chord onset,
Soprano >= Alto >= Tenor >= Bass in pitch. The old per-note midpoint
assignment violated this in the E4-C5 overlap zone; the chord-grouped
top-down assignment guarantees it.
"""

from __future__ import annotations

import pretty_midi

from backend.app.pipeline.score import _build_choir_satb_score


def _build_satb(tmp_path, chords):
    """chords: list of (onset, [pitches]) → MIDI → SATB score."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=52)  # choir aahs
    for onset, pitches in chords:
        for p in pitches:
            inst.notes.append(pretty_midi.Note(
                velocity=80, pitch=p, start=onset, end=onset + 1.0))
    pm.instruments.append(inst)
    midi_path = tmp_path / "choir.mid"
    pm.write(str(midi_path))
    return _build_choir_satb_score(midi_path, 120.0)


def _voice_pitches_at(score, onset_quarter):
    """Return {voice_id: midi_pitch} for notes starting at onset_quarter."""
    out = {}
    for part in score.parts:
        pid = part.id  # choir_s / choir_a / choir_t / choir_b
        for n in part.recurse().notes:
            if abs(float(n.offset) - onset_quarter) < 0.05:
                out[pid] = n.pitch.midi
    return out


def test_four_note_chord_assigns_top_down(tmp_path):
    # C major spread: C5(72) E4(64) G3(55) C3(48) → S A T B descending.
    score = _build_satb(tmp_path, [(0.0, [72, 64, 55, 48])])
    voices = _voice_pitches_at(score, 0.0)
    assert voices.get("choir_s") == 72
    assert voices.get("choir_a") == 64
    assert voices.get("choir_t") == 55
    assert voices.get("choir_b") == 48


def test_satb_invariant_s_ge_a_ge_t_ge_b(tmp_path):
    """Across several chords, S >= A >= T >= B must always hold."""
    chords = [
        (0.0, [67, 60, 52, 48]),   # G4 C4 E3 C3
        (2.0, [72, 64, 55, 48]),   # C5 E4 G3 C3
        (4.0, [69, 65, 60, 53]),   # A4 F4 C4 F3  (tight overlap zone)
    ]
    score = _build_satb(tmp_path, chords)
    for onset in (0.0, 2.0, 4.0):
        oq = onset * (120.0 / 60.0)
        v = _voice_pitches_at(score, oq)
        if {"choir_s", "choir_a", "choir_t", "choir_b"} <= set(v):
            assert v["choir_s"] >= v["choir_a"] >= v["choir_t"] >= v["choir_b"], \
                f"voice crossing at onset {onset}: {v}"


def test_extra_notes_fold_into_bass(tmp_path):
    # 5-note cluster — the 5th (lowest) note must not be dropped; it folds
    # into the Bass part alongside the 4th.
    score = _build_satb(tmp_path, [(0.0, [72, 67, 64, 55, 48])])
    total_notes = sum(len(list(p.recurse().notes)) for p in score.parts)
    assert total_notes == 5, f"expected all 5 notes kept, got {total_notes}"


def test_four_parts_always_present(tmp_path):
    score = _build_satb(tmp_path, [(0.0, [72, 64, 55, 48])])
    part_ids = {p.id for p in score.parts}
    assert {"choir_s", "choir_a", "choir_t", "choir_b"} <= part_ids
