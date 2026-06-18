"""Augmented Arachno renders for the starved AUX categories.

The base ``fetch_arachno`` renders ONE clip per GM preset (a C4 triad). For
categories where Arachno is the *only* source — ``synth_lead`` (NSynth's
valid split has zero) and ``fx`` (no NSynth family maps to it) — that left
just 8 and 16 reference vectors, far too few for a reliable top-k vote.

This fetcher re-renders those presets across a small grid of register ×
velocity so CLAP sees each patch at multiple timbres (a saw lead at C3 vs
C5, soft vs hard, genuinely differs in spectral centroid / brightness).
``epiano`` is also supplemented for register diversity, though it now gets
its bulk from NSynth's electronic keyboards.

These variations share a preset, so leave-one-out on them is optimistic vs
real songs — but more coverage of each category's timbre space still helps
a real measure find a nearer neighbour. Honest caveat recorded in the QA.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ._common import ReferenceItem, gm_program_to_category, save_manifest, iter_existing_items
from .render_sf2 import _fluidsynth_render

# Categories that need augmentation (Arachno is their only / primary source).
TARGET_CATEGORIES = {"synth_lead", "fx", "epiano"}

# GM programs whose category is in TARGET_CATEGORIES.
_TARGET_PROGRAMS = [p for p in range(128)
                    if gm_program_to_category(p) in TARGET_CATEGORIES]

# Render grid: root pitch (register) × velocity. A sustained triad at each.
_REGISTERS = (48, 60, 72)        # C3, C4, C5
_VELOCITIES = (55, 90, 120)      # soft / mp / hard


def _make_variation_midi(midi_path: Path, program: int, root: int, vel: int) -> None:
    import pretty_midi
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=program, is_drum=False)
    for semi in (0, 4, 7):                         # major triad on the root
        inst.notes.append(
            pretty_midi.Note(velocity=vel, pitch=root + semi, start=0.0, end=3.5)
        )
    pm.instruments.append(inst)
    pm.write(str(midi_path))


def fetch(out_dir: Path) -> list[ReferenceItem]:
    out_dir = Path(out_dir)
    wavs = out_dir / "wavs"
    if (wavs / "manifest.json").exists():
        cached = list(iter_existing_items(wavs, source="arachno_aug"))
        if cached:
            return cached

    # The base arachno fetcher already downloaded the sf2 here.
    sf2 = Path(__file__).resolve().parents[2] / "data" / "reference_db" / "_raw" / "arachno" / "Arachno_v1.0.sf2"
    if not sf2.exists():
        print(f"[arachno_aug] sf2 not found at {sf2} — run the base arachno source first")
        return []

    wavs.mkdir(parents=True, exist_ok=True)
    items: list[ReferenceItem] = []
    print(f"[arachno_aug] rendering {len(_TARGET_PROGRAMS)} presets "
          f"× {len(_REGISTERS)}×{len(_VELOCITIES)} variations")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for program in _TARGET_PROGRAMS:
            cat = gm_program_to_category(program)
            for root in _REGISTERS:
                for vel in _VELOCITIES:
                    wav = wavs / f"p{program:03d}_r{root}_v{vel}.wav"
                    if wav.exists() and wav.stat().st_size > 1000:
                        items.append(ReferenceItem(wav, cat, "arachno_aug", f"GM_{program:03d}"))
                        continue
                    midi = tmp_dir / f"p{program}_{root}_{vel}.mid"
                    _make_variation_midi(midi, program, root, vel)
                    if _fluidsynth_render(sf2, midi, wav):
                        items.append(ReferenceItem(wav, cat, "arachno_aug", f"GM_{program:03d}"))
    save_manifest(wavs, items)
    print(f"[arachno_aug] {len(items)} augmented clips rendered")
    return items
