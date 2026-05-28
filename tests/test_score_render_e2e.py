"""End-to-end score render: MIDI → MusicXML → SVG (Verovio) → PDF.

The per-builder unit tests stop at the music21 Score object. This test
exercises the *full* render path for all four notation styles, which is
where Verovio option errors and svglib colour-parse failures surface.

Skips gracefully when verovio / reportlab / svglib aren't installed
(they're core deps, so on a normal env this runs).
"""

from __future__ import annotations

from pathlib import Path

import pretty_midi
import pytest


def _make_midi(path: Path, *, poly=False, span_both_staves=False):
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0)
    if poly:
        for onset, chord in [(0.0, [72, 64, 55, 48]), (2.0, [71, 65, 55, 50])]:
            for p in chord:
                inst.notes.append(pretty_midi.Note(
                    velocity=80, pitch=p, start=onset, end=onset + 1.0))
    elif span_both_staves:
        # Piano-style line that populates BOTH the treble (>= C4) and the
        # bass (< C4) staves — otherwise the grand staff has an empty half.
        for i, p in enumerate([48, 55, 60, 64, 67, 72, 55, 48]):
            inst.notes.append(pretty_midi.Note(
                velocity=90, pitch=p, start=i * 0.5, end=i * 0.5 + 0.45))
    else:
        for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72]):
            inst.notes.append(pretty_midi.Note(
                velocity=90, pitch=p, start=i * 0.5, end=i * 0.5 + 0.45))
    pm.instruments.append(inst)
    pm.write(str(path))
    return path


CHORDS = [
    {"start_sec": 0.0, "end_sec": 2.0, "label": "C"},
    {"start_sec": 2.0, "end_sec": 4.0, "label": "G7"},
    {"start_sec": 4.0, "end_sec": 6.0, "label": "Am"},
]


@pytest.fixture(scope="module")
def deps_available():
    try:
        import verovio  # noqa: F401
        import svglib  # noqa: F401
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.parametrize("stem_kind,style,poly,both", [
    ("vocals", "lead_sheet", False, False),
    ("guitar", "guitar_tab", False, False),
    ("bass", "bass_tab", False, False),
    ("drums", "drum", False, False),
    ("piano", "grand_staff", False, True),
    ("vocals", "choir_satb", True, False),
])
def test_render_all_notation_styles(tmp_path, deps_available, stem_kind, style, poly, both):
    if not deps_available:
        pytest.skip("verovio/svglib/reportlab not installed")
    from backend.app.pipeline.score import build_score
    midi = _make_midi(tmp_path / f"{style}.mid", poly=poly, span_both_staves=both)
    sc = build_score(
        midi, tmp_path, stem_kind=stem_kind, title=f"E2E {style}",
        write_svg=True, write_pdf=True,
        chord_events=CHORDS, bpm=120.0,
        notation_style=style, key_name="C major",
    )
    # MusicXML always written — this is the core invariant.
    assert Path(sc.musicxml_path).exists()
    mx_size = Path(sc.musicxml_path).stat().st_size
    assert mx_size > 0, f"{style}: empty MusicXML"
    # At least one SVG page rendered without crashing.
    assert len(sc.svg_paths) >= 1, f"{style}: no SVG pages"
    assert all(Path(p).exists() for p in sc.svg_paths)
    # SVG content is non-empty (the real "render didn't crash" signal).
    assert all(Path(p).stat().st_size > 0 for p in sc.svg_paths), \
        f"{style}: empty SVG"
    # PDF stitched and is a valid (non-empty) file. We deliberately don't
    # assert a minimum byte count — Verovio/svglib occasionally emit a
    # compact-but-valid PDF and an arbitrary size floor made this flaky.
    assert sc.pdf_path is not None and Path(sc.pdf_path).exists(), \
        f"{style}: no PDF"
    assert Path(sc.pdf_path).stat().st_size > 0, f"{style}: empty PDF"


def test_sanitize_svg_colors_pads_five_digit_hex():
    from backend.app.pipeline.score import _sanitize_svg_colors
    svg = '<rect fill="#00000" stroke="#777777"/>'
    out = _sanitize_svg_colors(svg)
    assert "#00000\"" not in out          # the bad 5-digit form is gone
    assert "#777777" in out                # valid 6-digit untouched


def test_sanitize_svg_colors_leaves_valid_untouched():
    from backend.app.pipeline.score import _sanitize_svg_colors
    svg = '<g fill="#fff"><rect fill="#123456"/></g>'
    assert _sanitize_svg_colors(svg) == svg
