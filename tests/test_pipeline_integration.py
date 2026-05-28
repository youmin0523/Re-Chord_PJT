"""Full-pipeline integration test on a synthetic song.

Unlike the per-stage unit tests, this drives a *real* synthesized audio
file (known key, BPM, and chord progression) through the actual analysis
stages — analyze (key/BPM) → chords → sections → score → quality — and
asserts each produces a sane, non-degenerate result.

We synthesize a 12-second C-major I-IV-V-I progression (C-F-G-C) at
120 BPM with a 4-on-the-floor kick so beat detection has something to
lock onto. The separator is NOT involved (these stages run on the mixed
or instrumental audio directly), so no GPU / model weights are needed.

This is the test that would have caught "analyze returns key=unknown on
real audio" or "chords.json is empty" — failure modes the unit tests
can't see because they stub the audio.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest


SR = 22050
BPM = 120.0
DUR = 12.0


def _synth_song(path: Path) -> Path:
    """C major I-IV-V-I, 120 BPM, with kick on every beat.

    Each chord = 3 seconds (one bar of 4/4 at 120 = 2s, so 1.5 bars —
    close enough; we just need stable harmony + a clear pulse).
    """
    n_total = int(DUR * SR)
    t = np.arange(n_total) / SR
    out = np.zeros(n_total, dtype=np.float32)

    # Chord triads (root position) in Hz — C4 E4 G4 etc.
    chords = {
        "C": [261.63, 329.63, 392.00],
        "F": [349.23, 440.00, 523.25],
        "G": [392.00, 493.88, 587.33],
    }
    progression = ["C", "F", "G", "C"]
    seg = DUR / len(progression)
    for i, ch in enumerate(progression):
        s = int(i * seg * SR)
        e = int((i + 1) * seg * SR)
        for f in chords[ch]:
            out[s:e] += 0.15 * np.sin(2 * math.pi * f * t[s:e]).astype(np.float32)

    # Kick on every beat (120 BPM → 0.5s spacing) for tempo lock.
    beat = 60.0 / BPM
    n_beats = int(DUR / beat)
    for b in range(n_beats):
        ks = int(b * beat * SR)
        kn = int(0.12 * SR)
        ke = min(n_total, ks + kn)
        tt = np.arange(ke - ks) / SR
        sweep = np.linspace(110.0, 50.0, ke - ks)
        phase = 2 * math.pi * np.cumsum(sweep) / SR
        env = np.exp(-tt / 0.08).astype(np.float32)
        out[ks:ke] += 0.4 * (np.sin(phase).astype(np.float32) * env)

    out = np.clip(out, -1.0, 1.0)
    stereo = np.stack([out, out], axis=1)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    return path


@pytest.fixture(scope="module")
def synth_song(tmp_path_factory):
    return _synth_song(tmp_path_factory.mktemp("pipe") / "song.wav")


def test_analyze_returns_sane_key_and_bpm(synth_song):
    from backend.app.pipeline.analyze import analyze
    res = analyze(synth_song)
    # Key detected (not "unknown"); confidence is a real number.
    assert res.key_name and res.key_name != "unknown"
    assert 0.0 <= res.key_confidence <= 1.0
    # The synth is unambiguously C major — accept C major or its relative
    # A minor (Krumhansl can land on the relative on triad-only audio).
    assert res.key_root in ("C", "A"), f"unexpected key root {res.key_root}"
    # BPM should land near 120 (or a clean multiple/divisor the detector
    # might pick: 60 / 120 / 240). Allow the octave ambiguity.
    assert res.bpm > 0
    octave_ok = any(abs(res.bpm - cand) < 8 for cand in (60, 120, 240))
    assert octave_ok, f"bpm {res.bpm} not near a 120 multiple"


def test_chords_are_detected(synth_song):
    from backend.app.pipeline.chords import analyze_chords
    events = analyze_chords(synth_song)
    assert len(events) >= 2, "expected multiple chord segments"
    labels = {getattr(e, "label", "") for e in events}
    # At least one of the progression chords should surface (C/F/G or
    # their minor relatives — triad-only synth is harmonically ambiguous).
    assert any(lbl and lbl != "N" for lbl in labels), \
        f"no real chords detected: {labels}"


def test_sections_are_detected(synth_song):
    from backend.app.pipeline.sections import analyze_sections
    res = analyze_sections(synth_song, "auto", refine=False)
    assert res.beat_grid.bpm > 0
    assert len(res.beat_grid.beats_sec) > 0
    assert len(res.sections) >= 1
    # Every section has a valid time span.
    for s in res.sections:
        assert s.end_sec > s.start_sec


def test_quality_on_identity_split(synth_song, tmp_path):
    """quality.compute_quality on a trivial split (instrumental=song,
    vocals=silence) → near-perfect reconstruction, finite metrics."""
    from backend.app.pipeline.quality import compute_quality
    import soundfile as sf
    # Build a silent "vocals" companion of the same length.
    data, sr = sf.read(str(synth_song), dtype="float32", always_2d=True)
    silent = tmp_path / "silent.wav"
    sf.write(str(silent), np.zeros_like(data), sr, subtype="FLOAT")
    rep = compute_quality(synth_song, synth_song, silent,
                          target_sr=SR, sample_seconds=10.0)
    # inst(=song) + voc(=silence) ≈ song → strong reconstruction.
    assert rep.reconstruction_corr > 0.9
    assert np.isfinite(rep.null_rms_dbfs)
    assert rep.grade() in {"E", "D", "C", "B", "B+", "A", "A+"}


def test_score_from_chords_and_bpm(synth_song, tmp_path):
    """The detected key/bpm/chords feed build_score and produce a
    non-empty leadsheet with chord symbols + key signature."""
    from backend.app.pipeline.analyze import analyze
    from backend.app.pipeline.chords import analyze_chords, write_chords_json
    from backend.app.pipeline.score import build_score
    import pretty_midi
    import json

    an = analyze(synth_song)
    events = analyze_chords(synth_song)
    cj = tmp_path / "chords.json"
    write_chords_json(events, cj)
    chord_payload = json.loads(cj.read_text(encoding="utf-8")).get("events")

    # A simple melody MIDI to engrave (C major scale).
    pm = pretty_midi.PrettyMIDI(initial_tempo=BPM)
    inst = pretty_midi.Instrument(program=0)
    for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72]):
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=p,
                                           start=i * 0.5, end=i * 0.5 + 0.45))
    pm.instruments.append(inst)
    midi = tmp_path / "melody.mid"
    pm.write(str(midi))

    sc = build_score(
        midi, tmp_path, stem_kind="vocals", title="Integration",
        write_svg=True, write_pdf=False,
        chord_events=chord_payload, bpm=an.bpm or BPM,
        notation_style="lead_sheet", key_name=an.key_name,
    )
    assert Path(sc.musicxml_path).exists()
    assert sc.measures >= 1
    # The MusicXML should contain chord symbols (harmony) + a key sig.
    xml = Path(sc.musicxml_path).read_text(encoding="utf-8")
    assert "<harmony" in xml or "<kind" in xml, "no chord symbols in score"
    assert "<key>" in xml or "<fifths>" in xml, "no key signature in score"
