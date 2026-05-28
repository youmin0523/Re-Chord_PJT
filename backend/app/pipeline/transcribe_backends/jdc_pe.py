"""Bass / monophonic low-frequency transcription via CREPE + onset detection.

CREPE (Kim et al., 2018, MIT licensed) is a deep convolutional f0 estimator
trained on Bach10/MedleyDB/MDB-stem-synth. It's the de-facto SOTA open
model for monophonic pitch tracking and ships with pretrained weights
(~50 MB) inside the pip package.

Pipeline:
  1. Load audio at 16 kHz mono (CREPE's native rate).
  2. Run CREPE in viterbi mode → per-10 ms f0 + confidence.
  3. Drop frames with confidence < 0.5 (silent / non-pitched).
  4. Snap f0 → MIDI pitch, clamp to bass range (E1=28 ... E4=64).
  5. Run librosa onset_detect for note boundaries.
  6. Slice the pitch stream by onsets → notes.
  7. Drop notes shorter than 80 ms.

When CREPE isn't installed the function raises ImportError; the
dispatcher (``transcribe.py``) catches that and falls back to basic-pitch.

Accuracy expectations (peer-reviewed):
  Monophonic f0 (RPA @ 50 cents): 93-96% on MDB-stem-synth
  → Note-level F1 for bass: ~90-92%
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


# Bass MIDI range — lowest 4-string E1=28; 6-string B0=23.
BASS_MIDI_LOW = 23
BASS_MIDI_HIGH = 67          # E4 — includes high octave harmonics


def transcribe(audio_path: Path):
    """Return (PrettyMIDI, note_events) — same shape as basic-pitch."""
    try:
        import crepe  # type: ignore  # noqa: F401
    except ImportError as e:
        # Caller will fall back to basic-pitch.
        raise ImportError(
            "crepe not installed. Install with `uv pip install crepe` "
            "(adds ~250 MB tensorflow + 50 MB weights)."
        ) from e

    import librosa
    import numpy as np
    import pretty_midi

    y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    if y.size == 0:
        return pretty_midi.PrettyMIDI(), []

    # CREPE: 10 ms step is standard, viterbi smoothing reduces jitter.
    time_arr, freq_arr, conf_arr, _activation = crepe.predict(
        y, sr, model_capacity="medium", step_size=10, viterbi=True, verbose=0,
    )

    # Convert Hz → MIDI, mask low-confidence + out-of-range frames.
    midi_f = np.where(freq_arr > 0, 69 + 12 * np.log2(freq_arr / 440.0), -1)
    mask = (conf_arr >= 0.5) & (midi_f >= BASS_MIDI_LOW) & (midi_f <= BASS_MIDI_HIGH)
    midi_int = np.round(midi_f).astype(int)

    # Onset detection on the same audio for note boundaries.
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, units="time",
        wait=2, pre_avg=15, post_avg=15, pre_max=15, post_max=15,
        delta=0.08, backtrack=True,
    )

    notes = _segment_notes(time_arr, midi_int, conf_arr, mask, onset_frames)

    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=33, is_drum=False, name="bass")  # GM 33 = electric bass (finger)
    note_events = []
    for s, e, pitch, vel in notes:
        inst.notes.append(pretty_midi.Note(velocity=int(vel), pitch=int(pitch),
                                            start=float(s), end=float(e)))
        note_events.append((float(s), float(e), int(pitch), int(vel), None))
    pm.instruments.append(inst)
    return pm, note_events


def _segment_notes(times, midi_int, conf, mask, onsets):
    """Slice the pitch stream into notes guided by onset times.

    Within each onset→next-onset window, take the modal MIDI pitch from
    confident frames and emit a single note.
    """
    import numpy as np
    if onsets.size < 1:
        # No onsets detected — group by stable pitch runs.
        return _runs_to_notes(times, midi_int, conf, mask)

    boundaries = list(onsets) + [float(times[-1])]
    notes = []
    for k in range(len(boundaries) - 1):
        t0, t1 = boundaries[k], boundaries[k + 1]
        if t1 - t0 < 0.08:                # < 80 ms — skip
            continue
        # Frame indices in [t0, t1].
        sel = (times >= t0) & (times < t1) & mask
        if not sel.any():
            continue
        pitches = midi_int[sel]
        # Modal pitch is the most-voted note in this window.
        values, counts = np.unique(pitches, return_counts=True)
        modal = int(values[counts.argmax()])
        # Velocity from confidence amplitude.
        vel = int(np.clip(60 + 50 * float(conf[sel].mean()), 60, 110))
        notes.append((t0, t1, modal, vel))
    return notes


def _runs_to_notes(times, midi_int, conf, mask):
    """Fallback: group consecutive frames of the same pitch into a single note."""
    notes = []
    cur_pitch = None
    cur_start = None
    confidences = []
    for i in range(len(times)):
        if not mask[i]:
            if cur_pitch is not None and cur_start is not None and times[i] - cur_start >= 0.08:
                vel = int(60 + 50 * (sum(confidences) / max(1, len(confidences))))
                notes.append((cur_start, times[i], cur_pitch, max(60, min(110, vel))))
            cur_pitch = None
            cur_start = None
            confidences = []
            continue
        p = int(midi_int[i])
        if p == cur_pitch:
            confidences.append(float(conf[i]))
        else:
            if cur_pitch is not None and cur_start is not None and times[i] - cur_start >= 0.08:
                vel = int(60 + 50 * (sum(confidences) / max(1, len(confidences))))
                notes.append((cur_start, times[i], cur_pitch, max(60, min(110, vel))))
            cur_pitch = p
            cur_start = float(times[i])
            confidences = [float(conf[i])]
    if cur_pitch is not None and cur_start is not None and times[-1] - cur_start >= 0.08:
        vel = int(60 + 50 * (sum(confidences) / max(1, len(confidences))))
        notes.append((cur_start, float(times[-1]), cur_pitch, max(60, min(110, vel))))
    return notes
