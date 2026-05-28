"""Cross-check slash-chord bass notes against the actual bass stem.

CREMA's 170-class vocabulary reports slash chords like "C/E" or "G/B",
but the recogniser is making that bass call from the *full mix*, where
the bass guitar may be drowned out by the kick drum and rhythm guitar.
When we also have a dedicated bass stem (htdemucs_6s mode or stems-mode
ensemble), we can validate the slash bass against the actual fundamental
pitch coming out of the bass stem at that time.

This module:
  * sniffs the dominant pitch class of the bass stem inside each chord
    span (median pitch over the window, filtered to bass register);
  * confirms slash chords whose written bass agrees with the audio bass
    within ±1 semitone (soft confirmation, raises the chord confidence);
  * downgrades slash chords whose bass disagrees by 2+ semitones (likely
    a CREMA hallucination — strips the slash, keeps the root quality).

Returns a copy of the chord list with bass annotations updated. Safe to
call when no bass stem is available (returns input unchanged).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


# Bass register — A0 ≈ 27.5 Hz to E4 ≈ 330 Hz covers electric bass
# (E1 ≈ 41 Hz) through upright (G2-A4) and synth bass.
_BASS_LO = 35.0
_BASS_HI = 350.0

_PC_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_PC_OF = {n: i for i, n in enumerate(_PC_NAMES)}
_PC_OF.update({"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10})


def _midi_to_pc(midi: float) -> int:
    return int(round(midi)) % 12


def _dominant_pitch_class(audio: np.ndarray, sr: int) -> tuple[int | None, float]:
    """Return (pc, strength) for the bass-band fundamental of a window.

    Uses YIN via librosa for monophonic pitch estimation. Returns
    (None, 0.0) if the window is too quiet or pitch is unstable.
    """
    if audio.size == 0:
        return None, 0.0
    try:
        import librosa
        y = audio.mean(axis=1) if audio.ndim == 2 else audio
        if np.max(np.abs(y)) < 1e-4:
            return None, 0.0
        f0 = librosa.yin(y.astype(np.float32),
                         fmin=_BASS_LO, fmax=_BASS_HI, sr=sr,
                         frame_length=2048, hop_length=512)
        f0 = f0[np.isfinite(f0) & (f0 > 0)]
        if f0.size < 4:
            return None, 0.0
        midi = librosa.hz_to_midi(np.median(f0))
        pc = _midi_to_pc(float(midi))
        # Strength: fraction of frames where f0 lands within ±50 cents of
        # the median pitch. High strength = confidently monophonic bass.
        diffs = np.abs(librosa.hz_to_midi(f0) - midi)
        strength = float(np.mean(diffs < 0.5))
        return pc, strength
    except Exception:
        return None, 0.0


def _parse_bass_from_label(label: str) -> int | None:
    """Extract the bass pitch class from a slash-chord label, or None."""
    if not label or "/" not in label:
        return None
    bass = label.split("/", 1)[1].strip()
    if not bass:
        return None
    root = bass[:2] if len(bass) > 1 and bass[1] in "#b" else bass[:1]
    return _PC_OF.get(root)


def _root_pc(label: str) -> int | None:
    if not label:
        return None
    head = label.split("/", 1)[0].strip()
    if not head:
        return None
    root = head[:2] if len(head) > 1 and head[1] in "#b" else head[:1]
    return _PC_OF.get(root)


def cross_check_slash_bass(
    chord_events: list,
    bass_audio: Path,
    *,
    soft_boost: float = 0.08,
    hard_penalty: float = 0.20,
) -> dict:
    """Mutate ChordEvent list in-place, returning a diagnostic dict.

    For each event whose label contains "/", we look up the bass stem's
    median pitch over that event's window and:
      - if it matches the slash bass (±1 semitone) → confidence += soft_boost
      - if it disagrees by 2+ semitones → strip the slash + confidence -= hard_penalty
      - if the bass stem is silent / unconfident → leave the event alone.

    Returns: {"checked": N, "confirmed": k, "downgraded": m, "ambiguous": p}
    """
    if not chord_events or not bass_audio or not bass_audio.exists():
        return {"checked": 0, "confirmed": 0, "downgraded": 0, "ambiguous": 0}

    try:
        import soundfile as sf
    except Exception:
        return {"checked": 0, "confirmed": 0, "downgraded": 0, "ambiguous": 0,
                "error": "soundfile missing"}

    try:
        audio, sr = sf.read(str(bass_audio), dtype="float32", always_2d=True)
    except Exception as e:
        return {"checked": 0, "confirmed": 0, "downgraded": 0, "ambiguous": 0,
                "error": f"bass read failed: {e!r}"}

    confirmed = downgraded = ambiguous = checked = 0
    for ev in chord_events:
        label = getattr(ev, "label", "") or ""
        if "/" not in label:
            continue
        checked += 1
        slash_pc = _parse_bass_from_label(label)
        if slash_pc is None:
            ambiguous += 1
            continue
        start = float(getattr(ev, "start_sec", 0))
        end = float(getattr(ev, "end_sec", 0))
        if end <= start:
            ambiguous += 1
            continue
        s_idx = max(0, int(start * sr))
        e_idx = min(audio.shape[0], int(end * sr))
        if e_idx - s_idx < sr // 4:           # < 250 ms — too short
            ambiguous += 1
            continue
        window = audio[s_idx:e_idx]
        pc, strength = _dominant_pitch_class(window, sr)
        if pc is None or strength < 0.4:
            ambiguous += 1
            continue
        # Distance in semitones (mod 12, taking the shorter way around).
        diff = abs(pc - slash_pc) % 12
        diff = min(diff, 12 - diff)
        if diff <= 1:
            # Confirmed — boost confidence.
            old = float(getattr(ev, "confidence", 0.5))
            new = max(0.0, min(1.0, old + soft_boost))
            try:
                ev.confidence = new
                ev.bass_audio_pc = pc
                ev.bass_check = "confirmed"
            except Exception:
                pass
            confirmed += 1
        elif diff >= 2:
            # Strip the slash — chord becomes root-only.
            root_pc = _root_pc(label)
            head = label.split("/", 1)[0].strip()
            old = float(getattr(ev, "confidence", 0.5))
            new = max(0.0, min(1.0, old - hard_penalty))
            try:
                ev.label = head
                ev.confidence = new
                ev.bass_audio_pc = pc
                ev.bass_check = "downgraded"
                # If the bass-audio pc matches the root, even better —
                # it's a confident plain-root chord.
                if root_pc is not None and pc == root_pc:
                    ev.confidence = min(1.0, ev.confidence + 0.05)
            except Exception:
                pass
            downgraded += 1
        else:
            ambiguous += 1

    return {
        "checked": checked,
        "confirmed": confirmed,
        "downgraded": downgraded,
        "ambiguous": ambiguous,
    }
