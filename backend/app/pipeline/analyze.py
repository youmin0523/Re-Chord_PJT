"""Audio analysis: key and tempo (BPM) detection.

Hybrid: madmom-based SOTA path when installed (CNNKeyRecognitionProcessor
+ RNNBeatProcessor/TempoEstimationProcessor), librosa fallback otherwise.
Accuracy expectations: madmom ~85-92% major-key / ~90%+ BPM. Librosa
fallback ~70-80% for diatonic pop, lower for jazz/modal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles (normalized).
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass
class AnalyzeResult:
    key_name: str           # e.g. "C major", "F# minor"
    key_root: str           # "C", "F#"
    key_mode: str           # "major" | "minor"
    key_confidence: float   # 0..1 (relative correlation strength)
    bpm: float
    bpm_confidence: float   # 0..1 (pulse clarity)
    duration_sec: float


def _madmom_detect_key(audio_path: Path) -> tuple[str, str, str, float] | None:
    """SOTA key detection via madmom CNNKeyRecognitionProcessor.

    Returns (key_name, root, mode, confidence) or None to fall back. The
    pretrained CNN outputs a 24-dim probability vector over keys; the
    label is the argmax, the confidence is the softmax-style normalised
    top probability.
    """
    try:
        from madmom.features.key import CNNKeyRecognitionProcessor, key_prediction_to_label  # type: ignore
    except Exception:
        return None
    try:
        probs = CNNKeyRecognitionProcessor()(str(audio_path))
        # madmom returns shape (1, 24) — flatten so downstream indexing works
        # regardless of whether a single-row matrix or a 1-D vector is returned.
        flat = np.asarray(probs).ravel()
        if flat.size != 24:
            return None
        idx = int(np.argmax(flat))
        label = key_prediction_to_label(probs).strip()          # e.g. "D major"
        # Don't replace globally — "D major".replace("maj", "major") yields
        # "D majoror". Split first, then normalise the mode token only.
        parts = label.split()
        if len(parts) < 2:
            return None
        root = parts[0]
        mode_raw = parts[1].lower()
        if mode_raw.startswith("min"):
            mode = "minor"
        elif mode_raw.startswith("maj"):
            mode = "major"
        else:
            mode = mode_raw
        top = float(flat[idx])
        sorted_probs = sorted(flat.tolist(), reverse=True)
        second = float(sorted_probs[1]) if len(sorted_probs) > 1 else 0.0
        confidence = float(np.clip((top - second) / max(top, 1e-6) + 0.5, 0.0, 1.0))
        return f"{root} {mode}", root, mode, confidence
    except Exception:
        return None


def _madmom_detect_bpm(audio_path: Path) -> tuple[float, float] | None:
    """SOTA BPM via madmom RNNBeatProcessor + TempoEstimationProcessor.

    The raw top-K tempo list often contains both the perceived musical
    tempo AND its 2x/0.5x metric-modulation peer. We resolve that
    ambiguity by:

      1. Taking the strength-weighted average of all candidates within
         a ``±10%`` window of the strongest peak — this gives a stable
         single point estimate.
      2. Pulling the value into the standard musical band (50-200 BPM)
         by halving/doubling. Real BPM faster than 200 or slower than 50
         is exceedingly rare for the worship / pop / jazz repertoire we
         target.

    Without these guards the analyse stage was reporting halved BPMs
    on tracks where DBN locked on the eighth-note pulse (e.g. "Break
    Every Chain" → 56.6 instead of 113), which then propagated into
    job.meta["bpm"] and into every consumer downstream (UI, score
    tempo mark, click track).
    """
    try:
        from madmom.features.beats import RNNBeatProcessor  # type: ignore
        from madmom.features.tempo import TempoEstimationProcessor  # type: ignore
    except Exception:
        return None
    try:
        act = RNNBeatProcessor()(str(audio_path))
        tempo_proc = TempoEstimationProcessor(fps=100)
        tempos = tempo_proc(act)                # shape (n, 2): (bpm, strength)
        if tempos is None or len(tempos) == 0:
            return None
        top_bpm = float(tempos[0][0])
        top_strength = float(tempos[0][1])

        # Pull obvious halving/doubling into the musical band.
        while top_bpm > 200.0:
            top_bpm /= 2.0
        while 0 < top_bpm < 50.0:
            top_bpm *= 2.0

        # Refine: strength-weighted mean of candidates within ±10% of the
        # corrected peak (averages the cluster around the true tempo).
        cluster = [
            (float(b), float(s)) for b, s in tempos
            if 0.9 * top_bpm <= float(b) <= 1.1 * top_bpm
        ]
        if cluster:
            wsum = sum(s for _, s in cluster)
            if wsum > 0:
                top_bpm = sum(b * s for b, s in cluster) / wsum

        # Confidence: top strength normalised against the candidate-list mean.
        strengths = [float(s) for _, s in tempos]
        mean_s = float(np.mean(strengths)) if strengths else 0.0
        confidence = float(np.clip(top_strength / (mean_s + 1e-6) - 1.0, 0.0, 1.0))
        return top_bpm, confidence
    except Exception:
        return None


def detect_key(y_mono: np.ndarray, sr: int) -> tuple[str, str, str, float]:
    """Return (key_name, root, mode, confidence) from a mono signal."""
    import librosa

    # chroma_cens is robust to timbre/volume changes; use the harmonic part
    # to reduce drum/percussion bias.
    y_h = librosa.effects.harmonic(y_mono, margin=4.0)
    chroma = librosa.feature.chroma_cens(y=y_h, sr=sr, hop_length=2048)
    avg = chroma.mean(axis=1)  # (12,)
    if avg.sum() <= 0:
        return "unknown", "?", "?", 0.0
    avg = avg / avg.sum()

    scores: list[tuple[float, str, str]] = []
    for shift in range(12):
        major_corr = float(np.corrcoef(np.roll(_KS_MAJOR, shift), avg)[0, 1])
        minor_corr = float(np.corrcoef(np.roll(_KS_MINOR, shift), avg)[0, 1])
        scores.append((major_corr, PITCH_CLASSES[shift], "major"))
        scores.append((minor_corr, PITCH_CLASSES[shift], "minor"))

    scores.sort(reverse=True)
    best_score, best_root, best_mode = scores[0]
    second_score = scores[1][0]

    # Confidence: how dominant the best key is over the next best.
    if best_score <= 0:
        confidence = 0.0
    else:
        confidence = float(np.clip((best_score - second_score) / max(best_score, 1e-6) + 0.5, 0.0, 1.0))

    return f"{best_root} {best_mode}", best_root, best_mode, confidence


def detect_bpm(y_mono: np.ndarray, sr: int) -> tuple[float, float]:
    """Return (bpm, confidence) from a mono signal."""
    import librosa

    # Use the percussive component to focus on rhythmic content.
    y_p = librosa.effects.percussive(y_mono, margin=4.0)
    onset_env = librosa.onset.onset_strength(y=y_p, sr=sr, aggregate=np.median)
    tempo_arr = librosa.feature.tempo(onset_envelope=onset_env, sr=sr,
                                      aggregate=None)
    if tempo_arr.size == 0:
        return 0.0, 0.0
    bpm = float(np.median(tempo_arr))
    # Confidence: pulse clarity from the autocorrelation peak.
    ac = librosa.autocorrelate(onset_env, max_size=sr // 32)
    if ac.size > 1:
        confidence = float(np.clip(ac[1:].max() / (ac.max() + 1e-9), 0.0, 1.0))
    else:
        confidence = 0.0
    return bpm, confidence


def analyze(path) -> AnalyzeResult:
    """Run key + BPM detection on an audio file.

    SOTA path first (madmom CNN key + RNN tempo) — each falls back to
    librosa independently so we still benefit when one madmom call works
    and the other fails (e.g. on unusual sample rates).
    """
    import librosa

    src = Path(path)
    y, sr = librosa.load(str(src), sr=22050, mono=True)
    duration = float(len(y) / sr) if sr else 0.0

    madmom_key = _madmom_detect_key(src)
    if madmom_key is not None:
        key_name, key_root, key_mode, key_conf = madmom_key
    else:
        key_name, key_root, key_mode, key_conf = detect_key(y, sr)

    madmom_bpm = _madmom_detect_bpm(src)
    if madmom_bpm is not None:
        bpm, bpm_conf = madmom_bpm
    else:
        bpm, bpm_conf = detect_bpm(y, sr)

    return AnalyzeResult(
        key_name=key_name,
        key_root=key_root,
        key_mode=key_mode,
        key_confidence=key_conf,
        bpm=bpm,
        bpm_confidence=bpm_conf,
        duration_sec=duration,
    )


def semitones_between(from_key: str, to_key: str) -> int:
    """Compute shortest semitone shift between two pitch classes (both 'C', 'F#', etc)."""
    a = PITCH_CLASSES.index(from_key)
    b = PITCH_CLASSES.index(to_key)
    diff = (b - a) % 12
    if diff > 6:
        diff -= 12  # prefer shorter shift (down) when symmetric
    return diff


def _ev_get(ev, key, default=None):
    """Read a field from either a dataclass-like object or a plain dict."""
    if hasattr(ev, key):
        return getattr(ev, key)
    if isinstance(ev, dict):
        return ev.get(key, default)
    return default


def _windowed_root_from_chords(chord_events: list, t_start: float, t_end: float) -> str | None:
    """Most-common chord root in [t_start, t_end). None on empty/no-chord."""
    counts: dict[str, float] = {}
    for ev in chord_events:
        s = float(_ev_get(ev, "start_sec", 0) or 0)
        e = float(_ev_get(ev, "end_sec", 0) or 0)
        if e <= t_start or s >= t_end:
            continue
        root = _ev_get(ev, "root", "") or ""
        if not root or root in ("?", "N"):
            continue
        overlap = max(0.0, min(e, t_end) - max(s, t_start))
        counts[root] = counts.get(root, 0.0) + overlap
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def detect_modulations(
    chord_events: list, *, window_sec: float = 16.0, hop_sec: float = 8.0,
) -> list[dict]:
    """Detect key changes ("modulations") inside a song from chord events.

    Slides a ``window_sec`` window over the chord sequence, takes the
    most-common root in each window, and emits a modulation event whenever
    the root changes vs the previous window. We don't try to distinguish
    major / minor — chord-based mode detection is too noisy without the
    audio. The result is good enough to flag worship's classic "up a
    semitone for the last chorus" pattern + most pop pre-chorus lifts.

    Returns: [{at_sec, from_root, to_root, semitones}, …]
    """
    if not chord_events:
        return []
    # End time = last chord's end.
    end_t = float(_ev_get(chord_events[-1], "end_sec", 0) or 0)
    if end_t <= window_sec:
        return []

    segments: list[tuple[float, str]] = []
    t = 0.0
    while t < end_t:
        root = _windowed_root_from_chords(chord_events, t, t + window_sec)
        if root:
            segments.append((t + window_sec / 2.0, root))
        t += hop_sec
    if len(segments) < 2:
        return []

    # Detect changes; require 2 consecutive segments to confirm (anti-flicker).
    out: list[dict] = []
    last_root = segments[0][1]
    pending: tuple[float, str] | None = None
    for at, root in segments[1:]:
        if root == last_root:
            pending = None
            continue
        if pending is None or pending[1] != root:
            pending = (at, root)
            continue
        # Two windows in a row agreed → record modulation at the first one.
        try:
            shift = semitones_between(last_root, root)
        except ValueError:
            pending = None
            continue
        if shift != 0:
            out.append({
                "at_sec": round(pending[0], 2),
                "from_root": last_root,
                "to_root": root,
                "semitones": int(shift),
            })
        last_root = root
        pending = None
    return out


@dataclass
class TempoSegment:
    start_sec: float
    end_sec: float
    bpm: float


def tempo_map(
    y_mono: np.ndarray, sr: int, window_sec: float = 5.0, hop_sec: float = 2.5,
) -> list[TempoSegment]:
    """Piecewise BPM estimation — one tempo per ``window_sec`` sliding window.

    Variable-tempo tracks (rubato ballads, gradual tempo ramps in EDM,
    K-pop bridges that double-time) break a single-BPM model. We slide a
    5-second window across the track and estimate the local tempo, then
    return the segment list. The UI can show this as a tempo curve, and
    practice-mode loops can use the local BPM for accurate click tracks.
    """
    import librosa

    n = y_mono.shape[0]
    if n <= sr * 2:
        # Track too short for a meaningful map — single global tempo.
        bpm, _ = detect_bpm(y_mono, sr)
        return [TempoSegment(0.0, n / sr, float(bpm))]

    win = int(window_sec * sr)
    hop = int(hop_sec * sr)
    segments: list[TempoSegment] = []
    y_p = librosa.effects.percussive(y_mono, margin=4.0)
    for start in range(0, n - win + 1, hop):
        end = start + win
        chunk = y_p[start:end]
        onset_env = librosa.onset.onset_strength(y=chunk, sr=sr, aggregate=np.median)
        if onset_env.sum() < 1e-3:
            continue
        tempo_arr = librosa.feature.tempo(onset_envelope=onset_env, sr=sr, aggregate=None)
        if tempo_arr.size == 0:
            continue
        local = float(np.median(tempo_arr))
        # Reject impossible values.
        if local < 30 or local > 250:
            continue
        segments.append(TempoSegment(start / sr, end / sr, local))

    # Merge adjacent identical-bpm segments.
    return _merge_adjacent_segments(segments, eps_bpm=1.5)


def _merge_adjacent_segments(
    segments: list[TempoSegment], eps_bpm: float = 1.5,
) -> list[TempoSegment]:
    if not segments:
        return []
    out = [segments[0]]
    for s in segments[1:]:
        last = out[-1]
        if abs(s.bpm - last.bpm) <= eps_bpm and abs(s.start_sec - last.end_sec) < 0.05:
            out[-1] = TempoSegment(last.start_sec, s.end_sec,
                                    (last.bpm + s.bpm) * 0.5)
        else:
            out.append(s)
    return out
