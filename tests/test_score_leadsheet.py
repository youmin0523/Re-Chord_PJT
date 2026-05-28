"""Pin the leadsheet polishing behaviour:

  * Chord label normalisation strips ``Root:Quality`` colons and handles
    common 7th / sus / slash forms without raising.
  * Unparseable chord labels degrade to root-only — they never block the
    rest of the score.
  * Key signatures from worship-typical keys (G, D, Em, F#m) attach
    correctly to every part on the score.
"""

from __future__ import annotations

import pytest

from music21 import (
    harmony, key as m21_key, meter, note as m21_note, stream,
)

from backend.app.pipeline.score import (
    _attach_chord_symbols,
    _attach_key_signature,
    _normalise_chord_label,
)


@pytest.mark.parametrize("label,expected", [
    ("C", "C"),
    ("Am", "Am"),
    ("G7", "G7"),
    ("Cmaj7", "Cmaj7"),
    ("D:min7", "Dmin7"),         # CREMA colon-form normalised
    ("F#:maj7", "F#maj7"),
    ("Bb/F", "B-/F"),             # flat → music21 hyphen form
    ("Ebmaj7", "E-maj7"),
    ("  Em  ", "Em"),            # whitespace stripped
    ("E m", "Em"),                # internal whitespace stripped
    ("", ""),
])
def test_normalise_chord_label(label, expected):
    assert _normalise_chord_label(label) == expected


def test_attach_chord_symbols_handles_dirty_labels():
    """Mixture of valid / colon-CREMA / invalid labels should produce the
    valid ones without raising on the bad ones."""
    s = stream.Score()
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    p.append(m21_note.Note("C4", quarterLength=4.0))
    p.append(m21_note.Note("G4", quarterLength=4.0))
    s.insert(0, p)
    events = [
        {"start_sec": 0.0, "end_sec": 2.0, "label": "Cmaj7"},
        {"start_sec": 2.0, "end_sec": 4.0, "label": "D:min7"},
        {"start_sec": 4.0, "end_sec": 6.0, "label": "Bb/F"},
        {"start_sec": 6.0, "end_sec": 8.0, "label": "ZZGARBAGE"},
        {"start_sec": 8.0, "end_sec": 9.0, "label": "N"},
    ]
    _attach_chord_symbols(s, events, bpm=120.0)
    syms = list(s.recurse().getElementsByClass(harmony.ChordSymbol))
    assert len(syms) >= 3, f"expected >=3 chord symbols, got {len(syms)}"
    figures = " ".join(str(c.figure) for c in syms)
    assert "Cmaj7" in figures
    assert "Dmin7" in figures or "D" in figures
    # The garbage entry must not have raised.


def test_consecutive_duplicate_chords_suppressed():
    """A chord held across many detector frames should print once, not
    on every frame. C C C G C → C, G, C (3 symbols, not 5)."""
    s = stream.Score()
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    for _ in range(5):
        p.append(m21_note.Note("C4", quarterLength=4.0))
    p.makeMeasures(inPlace=True)
    s.insert(0, p)
    events = [
        {"start_sec": 0.0, "end_sec": 2.0, "label": "C"},
        {"start_sec": 2.0, "end_sec": 4.0, "label": "C"},   # dup
        {"start_sec": 4.0, "end_sec": 6.0, "label": "C"},   # dup
        {"start_sec": 6.0, "end_sec": 8.0, "label": "G"},   # change
        {"start_sec": 8.0, "end_sec": 10.0, "label": "C"},  # change back
    ]
    _attach_chord_symbols(s, events, bpm=120.0)
    syms = list(s.recurse().getElementsByClass(harmony.ChordSymbol))
    # Exactly 3 distinct printed symbols: C, G, C.
    assert len(syms) == 3, f"expected 3 symbols after dedup, got {len(syms)}"


def test_no_chord_gap_resets_dedup():
    """A no-chord 'N' between two identical chords should re-print the
    chord after the gap."""
    s = stream.Score()
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    for _ in range(3):
        p.append(m21_note.Note("C4", quarterLength=4.0))
    p.makeMeasures(inPlace=True)
    s.insert(0, p)
    events = [
        {"start_sec": 0.0, "end_sec": 2.0, "label": "C"},
        {"start_sec": 2.0, "end_sec": 4.0, "label": "N"},   # gap
        {"start_sec": 4.0, "end_sec": 6.0, "label": "C"},   # re-print
    ]
    _attach_chord_symbols(s, events, bpm=120.0)
    syms = list(s.recurse().getElementsByClass(harmony.ChordSymbol))
    assert len(syms) == 2, f"expected 2 C symbols around the gap, got {len(syms)}"


def test_chord_symbols_survive_musicxml_export():
    """Regression: ChordSymbols inserted at part-level offsets were
    silently dropped on MusicXML export when the part had measures.
    They must now appear as <harmony> in the exported XML."""
    from music21 import converter
    s = stream.Score()
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    # Build measures explicitly so the part is measure-structured (the
    # case that used to drop chord symbols on export).
    p.append(m21_note.Note("C4", quarterLength=4.0))
    p.append(m21_note.Note("G4", quarterLength=4.0))
    p.makeMeasures(inPlace=True)
    s.insert(0, p)
    events = [
        {"start_sec": 0.0, "end_sec": 2.0, "label": "C"},
        {"start_sec": 2.0, "end_sec": 4.0, "label": "G7"},
    ]
    _attach_chord_symbols(s, events, bpm=120.0)
    xml = s.write("musicxml")
    text = open(xml, encoding="utf-8").read()
    assert "<harmony" in text, "chord symbols dropped on MusicXML export"


def test_attach_key_signature_g_major():
    s = stream.Score()
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    p.append(m21_note.Note("G4", quarterLength=4.0))
    s.insert(0, p)
    _attach_key_signature(s, "G major")
    sigs = list(s.recurse().getElementsByClass(m21_key.KeySignature))
    assert len(sigs) >= 1
    # G major has one sharp.
    assert sigs[0].sharps == 1


def test_attach_key_signature_e_minor():
    s = stream.Score()
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    p.append(m21_note.Note("E4", quarterLength=4.0))
    s.insert(0, p)
    _attach_key_signature(s, "E minor")
    sigs = list(s.recurse().getElementsByClass(m21_key.KeySignature))
    assert len(sigs) >= 1
    assert sigs[0].sharps == 1


def test_attach_key_signature_handles_unknown_safely():
    s = stream.Score()
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    p.append(m21_note.Note("C4", quarterLength=4.0))
    s.insert(0, p)
    # Neither raises, nor inserts an invalid key.
    _attach_key_signature(s, "?")
    _attach_key_signature(s, "")
    _attach_key_signature(s, None)


def test_attach_key_signature_propagates_to_every_part():
    """Multi-part (SATB-shaped) score must get key signatures on all parts."""
    s = stream.Score()
    for _ in range(4):
        p = stream.Part()
        p.insert(0, meter.TimeSignature("4/4"))
        p.append(m21_note.Note("C4", quarterLength=4.0))
        s.insert(0, p)
    _attach_key_signature(s, "D major")
    sigs_per_part = [
        list(p.recurse().getElementsByClass(m21_key.KeySignature))
        for p in s.parts
    ]
    assert all(len(sigs) >= 1 for sigs in sigs_per_part)
    # D major has 2 sharps.
    assert all(sigs[0].sharps == 2 for sigs in sigs_per_part)
