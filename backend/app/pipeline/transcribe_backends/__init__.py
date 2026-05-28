"""Optional specialised transcription backends.

Each module exposes a single function::

    transcribe(audio_path: Path) -> tuple[PrettyMIDI, list[NoteEvent]]

where ``NoteEvent`` is the same 4-tuple shape basic-pitch returns:
``(start_sec, end_sec, midi_pitch, velocity)``.

Backends are loaded lazily by ``transcribe._try_specialised_backend``;
missing imports silently fall through to basic-pitch so the platform
keeps working before/without the optional deps.

Planned modules:
    mt3.py      — google-research/mt3 (polyphonic piano)
    a2d2.py     — drum-specific transcription
    jdc_pe.py   — bass / low-frequency monophonic SOTA
    crepe_vocals.py — vocals fundamental-frequency tracker
"""
