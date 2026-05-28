"""Pin the drum staff notation builder.

  * GM percussion pitches map to the correct kit lane + staff position.
  * Cymbals/hats get the 'x' notehead; drums get 'normal'.
  * Each lane is labelled only on its first occurrence (no text flood).
  * Non-GM (raw basic-pitch) input still produces a usable register split.
"""

from __future__ import annotations

import pretty_midi

from backend.app.pipeline.score import (
    _build_drum_score,
    GM_DRUM_LANES,
    DRUM_LANE_TO_STAFF,
)


def _drum_score(tmp_path, events):
    """events: list of (onset, midi_pitch)."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, is_drum=True, name="drums")
    for onset, pitch in events:
        inst.notes.append(pretty_midi.Note(
            velocity=100, pitch=pitch, start=onset, end=onset + 0.1))
    pm.instruments.append(inst)
    midi_path = tmp_path / "drums.mid"
    pm.write(str(midi_path))
    return _build_drum_score(midi_path, 120.0)


def test_gm_kick_snare_hat_map_to_distinct_positions(tmp_path):
    # 36 = kick, 38 = snare, 42 = closed hat.
    score = _drum_score(tmp_path, [(0.0, 36), (0.5, 38), (1.0, 42)])
    notes = list(score.recurse().notes)
    assert len(notes) == 3
    positions = sorted(n.pitch.midi for n in notes)
    # Three distinct staff positions.
    assert len(set(positions)) == 3


def test_cymbal_gets_x_notehead(tmp_path):
    # 42 = closed hat → x notehead.
    score = _drum_score(tmp_path, [(0.0, 42)])
    notes = list(score.recurse().notes)
    assert notes[0].notehead == "x"


def test_kick_gets_normal_notehead(tmp_path):
    score = _drum_score(tmp_path, [(0.0, 36)])
    notes = list(score.recurse().notes)
    assert notes[0].notehead == "normal"


def test_repeated_lane_labelled_once(tmp_path):
    # Eight hi-hats → only the first carries the "Hi-Hat" lyric.
    score = _drum_score(tmp_path, [(i * 0.25, 42) for i in range(8)])
    notes = sorted(score.recurse().notes, key=lambda n: n.offset)
    labelled = [n for n in notes if n.lyric]
    assert len(labelled) == 1, f"expected 1 label, got {len(labelled)}"


def test_kick_stem_down_hat_stem_up(tmp_path):
    score = _drum_score(tmp_path, [(0.0, 36), (0.5, 42)])
    by_pitch = {}
    for n in score.recurse().notes:
        # Identify by staff display pitch.
        by_pitch[n.pitch.midi] = n.stemDirection
    kick_pos = DRUM_LANE_TO_STAFF["kick"][1]
    hat_pos = DRUM_LANE_TO_STAFF["hh_closed"][1]
    assert by_pitch.get(kick_pos) == "down"
    assert by_pitch.get(hat_pos) == "up"


def test_non_gm_input_still_splits(tmp_path):
    """basic-pitch raw pitches (not GM percussion) should still produce
    a sensible kick/snare/tom/hat split rather than crashing."""
    # Pitches deliberately outside GM_DRUM_LANES keys.
    raw_pitches = [30, 46, 52, 60, 80]
    # 46 IS in GM (open hat); use 31/52/60/80 which are not standard kick/snare.
    raw_pitches = [31, 48, 54, 63, 84]
    score = _drum_score(tmp_path, [(i * 0.25, p) for i, p in enumerate(raw_pitches)])
    notes = list(score.recurse().notes)
    assert len(notes) == 5
