"""Polyphonic piano transcription — SOTA-tier when available.

Backend priority (first available wins):

    1. **piano_transcription_inference** (Qiuqiang Kong, Apache-2.0,
       py3.11-compatible). ICASSP 2021 Onsets-and-Frames piano model
       trained on MAESTRO. Note F1 ≈ 96% (frame-level) / 83% (onset).
       Weights ~150 MB downloaded on first call. **Default tier.**

    2. omnizart.music (Yating Music Lab, Apache-2.0, py≤3.10 only).
       Comparable accuracy, broader vocab. Auto-skipped on py3.11.

    3. transkun (HF weights, py3.11-compatible but needs MSVC build tools
       on Windows). Comparable accuracy.

    4. (caller fallback) basic-pitch with piano-tuned thresholds — 65-75% F1.
       ``transcribe.py`` reroutes when this module raises ImportError.

The file name "mt3.py" is kept purely for dispatch-table compatibility.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def transcribe(audio_path: Path):
    """Return (PrettyMIDI, note_events). Tries PTI → omnizart → transkun."""
    # Tier 1: piano_transcription_inference (py3.11-compatible, default).
    try:
        return _transcribe_pti(audio_path)
    except ImportError:
        pass

    # Tier 2: omnizart.music (best when available; Python ≤3.10 only).
    try:
        from omnizart.music import app as music_app  # type: ignore
        import pretty_midi
        with tempfile.TemporaryDirectory() as tmp:
            midi_path = music_app.transcribe(str(audio_path), output=tmp)
            pm = pretty_midi.PrettyMIDI(str(midi_path))
        note_events: list[tuple] = []
        for inst in pm.instruments:
            for n in inst.notes:
                note_events.append((float(n.start), float(n.end),
                                    int(n.pitch), int(n.velocity), None))
        return pm, note_events
    except ImportError:
        pass

    # Tier 3: transkun (Onsets-and-Frames piano, py3.11 + MSVC).
    try:
        return _transcribe_transkun(audio_path)
    except ImportError:
        pass

    raise ImportError(
        "No polyphonic piano backend installed. Options: "
        "piano_transcription_inference (default, py3.11) / "
        "omnizart (py≤3.10) / transkun (py3.11 + MSVC)."
    )


def _transcribe_pti(audio_path: Path):
    """Kong's piano-transcription-inference (Onsets-and-Frames, MAESTRO).

    Loads the pretrained checkpoint lazily on first call (downloaded to
    ``~/piano_transcription_inference_data/``, ~150 MB). Outputs a
    PrettyMIDI with a single GM-grand-piano instrument.
    """
    try:
        from piano_transcription_inference import (
            PianoTranscription, sample_rate as PTI_SR,
        )  # type: ignore
        import librosa
    except ImportError as e:
        raise ImportError(
            "piano_transcription_inference not installed. "
            "Run: uv pip install piano_transcription_inference"
        ) from e
    import pretty_midi

    # PTI wants 16 kHz mono float32.
    audio, sr = librosa.load(str(audio_path), sr=PTI_SR, mono=True)
    if audio.size == 0:
        return pretty_midi.PrettyMIDI(), []

    with tempfile.TemporaryDirectory() as tmp:
        out_midi = str(Path(tmp) / "piano.mid")
        # device='cuda' if available, else 'cpu'. PTI picks automatically.
        transcriber = PianoTranscription(device="cuda")
        try:
            transcriber.transcribe(audio, out_midi)
        except RuntimeError:
            # Fall back to CPU if CUDA path fails (e.g. mismatched cudnn).
            transcriber = PianoTranscription(device="cpu")
            transcriber.transcribe(audio, out_midi)
        pm = pretty_midi.PrettyMIDI(out_midi)

    note_events: list[tuple] = []
    for inst in pm.instruments:
        for n in inst.notes:
            note_events.append((float(n.start), float(n.end),
                                int(n.pitch), int(n.velocity), None))
    return pm, note_events


def _transcribe_transkun(audio_path: Path):
    """Transkun (HF-hosted Onsets+Frames piano model). Returns same shape."""
    try:
        from transkun.transcribe import transcribe_from_file  # type: ignore
    except ImportError as e:
        raise ImportError(
            "transkun not installed. Run `uv pip install transkun`."
        ) from e
    import pretty_midi
    with tempfile.TemporaryDirectory() as tmp:
        out_midi = Path(tmp) / "piano.mid"
        transcribe_from_file(str(audio_path), str(out_midi))
        pm = pretty_midi.PrettyMIDI(str(out_midi))
    note_events: list[tuple] = []
    for inst in pm.instruments:
        for n in inst.notes:
            note_events.append((float(n.start), float(n.end),
                                int(n.pitch), int(n.velocity), None))
    return pm, note_events
