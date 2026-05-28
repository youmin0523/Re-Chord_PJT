"""Export-completeness regression: every overlay must survive MusicXML.

The lesson from the chord-symbol bug: an in-memory music21 element can
be silently dropped on ``.write('musicxml')`` if it isn't inside a
measure. This suite renders each notation style to *actual MusicXML*
and asserts the overlays (section markers, tempo, chord symbols, key
signature, lyrics, fret/notehead) are present in the serialized output.

If an overlay regresses to part-level insertion, these tests fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pretty_midi
import pytest

from backend.app.pipeline.score import midi_to_musicxml


SECTIONS = [
    {"start_sec": 0.0, "end_sec": 2.0, "label": "verse"},
    {"start_sec": 2.0, "end_sec": 4.0, "label": "chorus"},
]
CHORDS = [
    {"start_sec": 0.0, "end_sec": 2.0, "label": "C"},
    {"start_sec": 2.0, "end_sec": 4.0, "label": "G7"},
]


def _mk_midi(path: Path, *, poly=False):
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0)
    if poly:
        for onset, ch in [(0.0, [72, 64, 55, 48]), (2.0, [71, 65, 55, 50])]:
            for p in ch:
                inst.notes.append(pretty_midi.Note(velocity=80, pitch=p,
                                                   start=onset, end=onset + 1.0))
    else:
        for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72]):
            inst.notes.append(pretty_midi.Note(velocity=90, pitch=p,
                                               start=i * 0.5, end=i * 0.5 + 0.45))
    pm.instruments.append(inst)
    pm.write(str(path))
    return path


def _render(tmp_path, stem_kind, style, *, poly=False, lyrics=None, aux=None):
    midi = _mk_midi(tmp_path / f"{style}.mid", poly=poly)
    out = tmp_path / f"{style}.musicxml"
    midi_to_musicxml(
        midi, out, stem_kind=stem_kind, title="T", bpm=120.0,
        chord_events=CHORDS, sections=SECTIONS, lyrics_words=lyrics,
        aux_cues=aux, notation_style=style, key_name="C major",
        time_signature="4/4",
    )
    return out.read_text(encoding="utf-8")


def _count(pat, xml):
    return len(re.findall(pat, xml))


@pytest.mark.parametrize("stem_kind,style,poly", [
    ("vocals", "lead_sheet", False),
    ("guitar", "guitar_tab", False),
    ("bass", "bass_tab", False),
    ("drums", "drum", False),
    ("vocals", "choir_satb", True),
])
def test_section_markers_survive_export(tmp_path, stem_kind, style, poly):
    xml = _render(tmp_path, stem_kind, style, poly=poly)
    assert _count(r"<rehearsal", xml) >= 2, \
        f"{style}: section rehearsal marks dropped on export"


@pytest.mark.parametrize("stem_kind,style,poly", [
    ("vocals", "lead_sheet", False),
    ("guitar", "guitar_tab", False),
    ("drums", "drum", False),
    ("vocals", "choir_satb", True),
])
def test_tempo_survives_export(tmp_path, stem_kind, style, poly):
    xml = _render(tmp_path, stem_kind, style, poly=poly)
    assert _count(r"<metronome", xml) >= 1 or _count(r"<per-minute", xml) >= 1, \
        f"{style}: tempo mark dropped on export"


@pytest.mark.parametrize("stem_kind,style,poly", [
    ("vocals", "lead_sheet", False),
    ("guitar", "guitar_tab", False),
    ("drums", "drum", False),
])
def test_chord_symbols_survive_export(tmp_path, stem_kind, style, poly):
    xml = _render(tmp_path, stem_kind, style, poly=poly)
    assert _count(r"<harmony", xml) >= 1, \
        f"{style}: chord symbols dropped on export"


def test_key_signature_survives_export(tmp_path):
    xml = _render(tmp_path, "vocals", "lead_sheet")
    assert "<fifths>" in xml, "key signature dropped on export"


def test_lyrics_survive_export(tmp_path):
    lyrics = [
        {"word": "주", "start_sec": 0.0, "end_sec": 0.5, "confidence": 0.9, "verse": 1},
        {"word": "님", "start_sec": 0.5, "end_sec": 1.0, "confidence": 0.9, "verse": 1},
    ]
    xml = _render(tmp_path, "vocals", "lead_sheet", lyrics=lyrics)
    assert "<lyric" in xml, "lyrics dropped on export"


def test_satb_keeps_four_parts_on_export(tmp_path):
    xml = _render(tmp_path, "vocals", "choir_satb", poly=True)
    assert _count(r"<score-part ", xml) == 4, "SATB lost parts on export"


def test_drum_noteheads_survive_export(tmp_path):
    xml = _render(tmp_path, "drums", "drum")
    # 'x' noteheads for cymbals/hats must serialize.
    assert "notehead" in xml.lower(), "drum noteheads dropped on export"
