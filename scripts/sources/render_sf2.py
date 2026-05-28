"""Render a SoundFont (.sf2/.sf3) → labelled wav clips via fluidsynth.

For each preset (program × bank) in the soundfont, play a single sustained
chord at ~mp velocity and capture the audio into a 4-second mono 48 kHz wav.
The preset's GM program number drives the category label.

Requires the ``fluidsynth`` CLI in PATH and the ``pretty_midi`` python pkg.

We avoid the python pyfluidsynth bindings because their Windows wheels are
flaky; the CLI is rock-solid and we already invoke ffmpeg/yt-dlp the same way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ._common import ReferenceItem, gm_program_to_category, save_manifest


def _resolve_fluidsynth() -> str:
    """Locate fluidsynth.exe — prefer the project-local bin/, fall back to PATH."""
    env_override = os.environ.get("FLUIDSYNTH_PATH")
    if env_override and Path(env_override).exists():
        return env_override
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "bin" / "fluidsynth.exe",
        project_root / "bin" / "fluidsynth",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    on_path = shutil.which("fluidsynth")
    if on_path:
        return on_path
    raise RuntimeError(
        "fluidsynth not found. Put fluidsynth(.exe) in <project>/bin/ or set FLUIDSYNTH_PATH."
    )


def _make_test_midi(midi_path: Path, program: int, bank: int = 0) -> None:
    """Write a tiny MIDI: bank/program select + 3-note pad chord at C4."""
    import pretty_midi
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=program, is_drum=False)
    # Three-note voicing in the keyboard's sweet spot. Hold 3.5s so even
    # slow-attack pads have time to bloom; tail decays during 4s capture.
    for pitch in (60, 64, 67):                  # C major triad mid-register
        inst.notes.append(
            pretty_midi.Note(velocity=78, pitch=pitch, start=0.0, end=3.5)
        )
    if bank > 0:
        # pretty_midi doesn't support bank-select directly; emit a CC0.
        inst.control_changes.append(
            pretty_midi.ControlChange(number=0, value=bank, time=0.0)
        )
    pm.instruments.append(inst)
    pm.write(str(midi_path))


def _fluidsynth_render(sf2: Path, midi: Path, out_wav: Path) -> bool:
    """Render midi via fluidsynth → 48 kHz mono wav. Returns success bool."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _resolve_fluidsynth(),
        "-ni",                      # non-interactive
        "-F", str(out_wav),         # render to file
        "-r", "48000",              # sample rate
        "-T", "wav",                # output format
        "-g", "0.6",                # gain (avoid clipping; 0.4 is library default)
        str(sf2),
        str(midi),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return False
        return out_wav.exists() and out_wav.stat().st_size > 1000
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _list_presets(sf2: Path) -> list[tuple[int, int, str]]:
    """Return (bank, program, name) for every preset in the soundfont.

    Uses sf2utils if available, else falls back to scanning all 128 GM
    programs on bank 0 — works for any GM-compliant soundfont.
    """
    try:
        from sf2utils.sf2parse import Sf2File  # type: ignore
        with open(sf2, "rb") as f:
            parsed = Sf2File(f)
        out: list[tuple[int, int, str]] = []
        for p in parsed.presets:
            # sf2utils' EOP marker has bank=255; skip it.
            if getattr(p, "bank", 0) == 255:
                continue
            name = getattr(p, "name", "") or f"prog{p.preset}"
            out.append((int(p.bank), int(p.preset), str(name).strip()))
        return out
    except Exception:
        # Fallback: assume GM coverage on bank 0.
        return [(0, p, f"GM_{p:03d}") for p in range(128)]


def render_sf2(
    sf2_path: Path,
    out_dir: Path,
    source_tag: str,
    *,
    skip_existing: bool = True,
) -> list[ReferenceItem]:
    """Render every AUX-eligible preset of ``sf2_path`` into ``out_dir``.

    ``source_tag`` is the value written to ``ReferenceItem.source`` (e.g.
    ``"arachno"`` or ``"polyphone:salamander"``).
    """
    sf2_path = Path(sf2_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    presets = _list_presets(sf2_path)
    items: list[ReferenceItem] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for bank, program, name in presets:
            cat = gm_program_to_category(program)
            if cat is None:
                continue
            safe_name = "".join(
                c if c.isalnum() or c in "-_" else "_" for c in name
            )[:48]
            wav = out_dir / f"b{bank:03d}_p{program:03d}_{safe_name}.wav"
            if skip_existing and wav.exists() and wav.stat().st_size > 1000:
                items.append(ReferenceItem(wav, cat, source_tag, name))
                continue
            midi = tmp_dir / f"q_{bank}_{program}.mid"
            _make_test_midi(midi, program, bank)
            if _fluidsynth_render(sf2_path, midi, wav):
                items.append(ReferenceItem(wav, cat, source_tag, name))

    save_manifest(out_dir, items)
    return items
