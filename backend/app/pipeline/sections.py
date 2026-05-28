"""Beat tracking + section boundary detection.

When madmom is installed (MSVC build) we use its RNNDownBeatProcessor +
DBNDownBeatTrackingProcessor — currently SOTA for beat & downbeat tracking
(beat F1 ~95%, downbeat F1 ~85%). Otherwise we fall back to the librosa
pipeline (beats ~85%, downbeats ~60% by onset-pattern heuristic) which
keeps cue/click generation working in any environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class BeatGrid:
    bpm: float
    beats_sec: list[float]            # per-beat times (eighth notes in compound meters)
    downbeats_sec: list[float]        # estimated downbeat times (every `meter` beats)
    meter: int                         # 4 for 4/4 / 12/8, 3 for 3/4 / 6/8
    time_signature: str = "4/4"        # display label: "4/4", "3/4", "6/8", "12/8"
    is_compound: bool = False          # True for 6/8, 9/8, 12/8 (beats are dotted-quarter)


@dataclass
class SectionMarker:
    start_sec: float
    end_sec: float
    label: str                        # intro|verse|pre-chorus|chorus|bridge|outro|instrumental


@dataclass
class SectionsResult:
    beat_grid: BeatGrid
    sections: list[SectionMarker] = field(default_factory=list)


# Korean labels for voice cue (default). The TTS handler can override.
KO_LABELS = {
    "intro": "인트로",
    "verse": "벌스",
    "pre-chorus": "프리코러스",
    "chorus": "코러스",
    "post-chorus": "포스트코러스",
    "bridge": "브릿지",
    "instrumental": "인스트루멘탈",
    "solo": "솔로",
    "outro": "아웃트로",
    "silence": "무음",
}

EN_LABELS = {
    "intro": "Intro",
    "verse": "Verse",
    "pre-chorus": "Pre Chorus",
    "chorus": "Chorus",
    "post-chorus": "Post Chorus",
    "bridge": "Bridge",
    "instrumental": "Instrumental",
    "solo": "Solo",
    "outro": "Outro",
    "silence": "Silence",
}


# Candidate meters we'll evaluate when meter='auto' is requested.
# Each entry is (beats_per_bar, time_signature_label, is_compound_flag).
# Compound meters (6/8, 9/8, 12/8) are flagged because the user-facing
# display ("6/8") differs from the internal grouping (we still snap on
# the dotted-quarter pulse but show "6/8" because that's the conventional
# notation). The candidate set covers everything from a Viennese waltz
# (3/4) to a prog-rock 7/8 to a gospel 12/8.
_METER_CANDIDATES: list[tuple[int, str, bool]] = [
    (2, "2/4",  False),
    (3, "3/4",  False),
    (4, "4/4",  False),
    (5, "5/4",  False),
    (6, "6/8",  True),
    (7, "7/8",  False),
    (8, "8/8",  False),
    (9, "9/8",  True),
    (10, "10/8", False),
    (11, "11/8", False),
    (12, "12/8", True),
]


def _score_meter(
    onset_at_beats: np.ndarray, meter: int,
) -> tuple[int, float]:
    """Return (best_offset, score) — how strongly the onset pattern repeats
    on a ``meter``-beat cycle. We pick the offset that maximises the *ratio*
    of onset energy on the downbeat vs the other beats, then return the
    *log ratio* so multi-beat patterns are penalised proportionally.
    """
    if meter <= 0 or onset_at_beats.size < meter * 2:
        return (0, -np.inf)
    best_offset = 0
    best_ratio = -np.inf
    for off in range(meter):
        downbeats = onset_at_beats[off::meter]
        others = np.concatenate([
            onset_at_beats[i::meter]
            for i in range(meter) if i != off
        ]) if meter > 1 else np.array([1e-9])
        down_avg = float(downbeats.mean()) if downbeats.size else 0.0
        other_avg = float(others.mean()) if others.size else 1e-9
        if other_avg <= 1e-9:
            continue
        ratio = down_avg / other_avg
        if ratio > best_ratio:
            best_ratio = ratio
            best_offset = off
    # Convert ratio to a log-domain score and penalise larger meters a hair
    # so 4/4 wins ties (it's the population prior).
    if best_ratio <= 0:
        return (best_offset, -np.inf)
    score = float(np.log(best_ratio)) - 0.04 * (meter - 4)
    return (best_offset, score)


def _madmom_detect_beat_grid(audio_path: Path, meter: int | str) -> BeatGrid | None:
    """SOTA path via madmom. Returns BeatGrid on success, None to fall back.

    madmom's pretrained RNNDownBeatProcessor + DBNDownBeatTrackingProcessor
    return per-beat (time, beat-index) tuples where beat-index 1 marks a
    downbeat. We feed the tracker the candidate meters so it picks the
    grouping that maximises model likelihood — far more reliable than the
    onset-energy heuristic that our librosa path uses for downbeat picking.
    """
    try:
        # ``_numpy_compat`` is auto-imported by ``backend.app.pipeline.__init__``
        # so the deprecated ``np.float`` / ``np.int`` aliases madmom 0.16
        # still references will resolve correctly.
        from madmom.features.downbeats import (  # type: ignore
            RNNDownBeatProcessor, DBNDownBeatTrackingProcessor,
        )
    except Exception:
        return None
    try:
        if meter == "auto":
            beats_per_bar = [m for m, _, _ in _METER_CANDIDATES if m in (3, 4, 6)]
        else:
            m_int = int(meter)
            beats_per_bar = [m_int]

        act = RNNDownBeatProcessor()(str(audio_path))
        proc = DBNDownBeatTrackingProcessor(beats_per_bar=beats_per_bar, fps=100)
        beats_with_pos = proc(act)        # shape (n, 2): (time, beat-in-bar)
        if beats_with_pos is None or len(beats_with_pos) < 2:
            return None

        beats_sec = [float(t) for t, _ in beats_with_pos]
        downbeats_sec = [float(t) for t, p in beats_with_pos if int(p) == 1]

        # Derive meter from the modal beat-count between consecutive downbeats.
        if len(downbeats_sec) >= 2:
            gaps = []
            for i in range(len(downbeats_sec) - 1):
                lo, hi = downbeats_sec[i], downbeats_sec[i + 1]
                gaps.append(sum(1 for b in beats_sec if lo <= b < hi))
            best_m = int(round(float(np.median(gaps)))) if gaps else 4
        else:
            best_m = int(beats_per_bar[0])
        best_m = max(2, best_m)

        # Look up the time-signature label and compound flag for the chosen meter.
        label, compound = "4/4", False
        for m, lab, comp in _METER_CANDIDATES:
            if m == best_m:
                label, compound = lab, comp
                break

        # Average inter-beat interval → BPM. Compound meters (6/8 etc.) report
        # the eighth-note pulse internally; the displayed BPM is the
        # dotted-quarter (÷ 3) to match musician convention.
        intervals = np.diff(beats_sec)
        bpm = float(60.0 / np.median(intervals)) if intervals.size else 0.0

        # DBN downbeat tracker often locks on the eighth-note pulse, so its
        # raw inter-beat BPM lands at exactly ~2x the perceived musical tempo
        # (e.g. 181.8 instead of 89.6). Cross-check against madmom's RNN-based
        # tempo estimator which doesn't have this failure mode, then snap to
        # whichever multiple lies closest. 14 s extra runtime is worth the
        # ~10-15% accuracy bump on tempo display.
        try:
            from .analyze import _madmom_detect_bpm
            ref = _madmom_detect_bpm(audio_path)
            if ref and ref[0] > 0:
                ref_bpm = float(ref[0])
                candidates = [bpm, bpm * 2.0, bpm / 2.0]
                bpm = min(candidates, key=lambda v: abs(v - ref_bpm))
        except Exception:
            # Cross-check is a best-effort polish — failures don't block.
            pass

        # Final guard band (50-200 BPM covers slow ballad → drum'n'bass).
        while bpm > 200:
            bpm /= 2.0
        while 0 < bpm < 50:
            bpm *= 2.0
        musical_bpm = bpm / 3.0 if compound else bpm

        return BeatGrid(
            bpm=musical_bpm,
            beats_sec=beats_sec,
            downbeats_sec=downbeats_sec,
            meter=best_m,
            time_signature=label,
            is_compound=compound,
        )
    except Exception:
        # Any runtime failure inside madmom (model load, signal quirks, …)
        # → silently fall back. User still gets a result via librosa.
        return None


def detect_beat_grid(audio_path: Path, meter: int | str = "auto") -> BeatGrid:
    """Estimate BPM + per-beat times + downbeats + meter.

    ``meter='auto'`` (default) probes candidate meters in
    ``_METER_CANDIDATES`` and picks the one whose onset-pattern repeats
    most strongly. Pass an integer (2, 3, 4, 5, …) to override.

    SOTA path: madmom DBNDownBeatTrackingProcessor (when installed).
    Fallback: librosa beat_track + onset-energy meter scoring.
    """
    madmom_grid = _madmom_detect_beat_grid(audio_path, meter)
    if madmom_grid is not None:
        return madmom_grid

    import librosa

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    y_p = librosa.effects.percussive(y, margin=4.0)
    onset_env = librosa.onset.onset_strength(y=y_p, sr=sr, aggregate=np.median)
    bpm_arr, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, units="frames",
    )
    bpm = float(np.atleast_1d(bpm_arr)[0]) if bpm_arr is not None else 0.0
    beats_sec = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    if not beats_sec:
        return BeatGrid(
            bpm=bpm, beats_sec=[], downbeats_sec=[], meter=4,
            time_signature="4/4", is_compound=False,
        )

    onset_at_beats = onset_env[np.clip(beat_frames, 0, len(onset_env) - 1)]

    if meter == "auto":
        candidates = _METER_CANDIDATES
    else:
        m_int = int(meter)
        # User-forced meter — keep the override but still score it for the offset.
        matching = next(((m, lab, comp) for m, lab, comp in _METER_CANDIDATES if m == m_int), None)
        candidates = [matching] if matching else [(m_int, f"{m_int}/4", False)]

    best = None
    for m, label, compound in candidates:
        off, score = _score_meter(onset_at_beats, m)
        if best is None or score > best[1]:
            best = ((m, label, compound, off), score)

    (best_m, best_label, best_compound, best_offset), _ = best
    downbeats_sec = beats_sec[best_offset::best_m]

    # For compound meters, librosa's beat_track often locks on the eighth-
    # note pulse, so the effective tempo is the dotted-quarter — half (6/8)
    # or a third (12/8) of the raw BPM. Report the *musical* tempo for
    # display purposes; the per-beat grid stays at the eighth-note pulse.
    musical_bpm = bpm
    if best_compound:
        # Compound feel: musical tempo = beats / 3 (6/8 / 12/8) or beats / 3 (9/8).
        musical_bpm = bpm / 3.0

    return BeatGrid(
        bpm=musical_bpm,
        beats_sec=beats_sec,
        downbeats_sec=downbeats_sec,
        meter=best_m,
        time_signature=best_label,
        is_compound=best_compound,
    )


def detect_sections(audio_path: Path, beat_grid: BeatGrid) -> list[SectionMarker]:
    """librosa-based novelty curve + chroma recurrence -> section boundaries.

    Labels are heuristic: we infer chorus by repetition+energy, intro/outro by
    position, bridge by mid-song novelty drop. Always editable by the user.
    """
    import librosa

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    duration = float(len(y) / sr) if sr else 0.0
    if duration <= 6.0:
        return [SectionMarker(0.0, duration, "intro")]

    hop = 512
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    # Recurrence-based boundaries via spectral clustering proxy.
    bounds_idx = librosa.segment.agglomerative(chroma, k=max(4, min(10, int(duration // 25))))
    bounds_sec = librosa.frames_to_time(bounds_idx, sr=sr, hop_length=hop).tolist()
    if not bounds_sec or bounds_sec[0] > 0.5:
        bounds_sec = [0.0] + bounds_sec
    if bounds_sec[-1] < duration - 0.5:
        bounds_sec.append(duration)

    # Build (start, end) intervals from boundaries; merge tiny segments (<6s)
    # into neighbors.
    intervals: list[tuple[float, float]] = []
    for s, e in zip(bounds_sec[:-1], bounds_sec[1:]):
        if intervals and (e - s) < 6.0:
            ps, _ = intervals.pop()
            intervals.append((ps, e))
        else:
            intervals.append((s, e))

    # Snap intervals to nearest downbeat (or beat) so the cue lines up.
    snap_targets = beat_grid.downbeats_sec or beat_grid.beats_sec
    if snap_targets:
        def snap(t: float) -> float:
            arr = np.asarray(snap_targets)
            idx = int(np.argmin(np.abs(arr - t)))
            return float(arr[idx])
        intervals = [(snap(s), snap(e)) for s, e in intervals]
        # Drop zero-length intervals after snapping.
        intervals = [iv for iv in intervals if iv[1] - iv[0] > 1.5]

    # Energy per segment for chorus inference.
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    seg_energies: list[float] = []
    for s, e in intervals:
        f1 = int(s * sr / hop)
        f2 = int(e * sr / hop)
        if f2 > f1:
            seg_energies.append(float(rms[f1:f2].mean()))
        else:
            seg_energies.append(0.0)

    median_energy = float(np.median(seg_energies)) if seg_energies else 0.0
    high_energy = median_energy * 1.10
    n = len(intervals)

    labels: list[str] = []
    for i, ((s, e), energy) in enumerate(zip(intervals, seg_energies)):
        if i == 0:
            labels.append("intro")
        elif i == n - 1:
            labels.append("outro")
        elif energy > high_energy:
            labels.append("chorus")
        elif i == n // 2 and energy < median_energy:
            labels.append("bridge")
        else:
            labels.append("verse")

    # Promote final "verse" to "outro" if energy fades.
    if len(labels) >= 2 and labels[-2] == "verse" and seg_energies[-2] < median_energy * 0.7:
        labels[-2] = "outro"

    return [SectionMarker(s, e, lbl) for (s, e), lbl in zip(intervals, labels)]


def analyze_sections(
    audio_path: Path,
    meter: int | str = "auto",
    *,
    lyrics_words: list[dict] | None = None,
    chord_events: list[dict] | None = None,
    refine: bool = True,
) -> SectionsResult:
    """Full section-analysis bundle: beat grid + section markers.

    ``refine=True`` (default) layers the K-Pop-friendly refiner
    (SSM repeat + lyric repetition + optional local LLM) on top of the
    base librosa output. Pass ``lyrics_words`` and ``chord_events`` for
    the strongest signal; either is enough on its own.
    """
    grid = detect_beat_grid(audio_path, meter=meter)
    sections = detect_sections(audio_path, grid)
    if refine and sections:
        try:
            from .sections_advanced import refine_sections
            sections = refine_sections(
                sections, audio_path,
                lyrics_words=lyrics_words, chord_events=chord_events,
            )
        except Exception:
            # Never break the pipeline because of refinement; keep the
            # base sections.
            pass
    return SectionsResult(beat_grid=grid, sections=sections)


def label_text(label: str, language: str = "ko") -> str:
    tbl = KO_LABELS if language == "ko" else EN_LABELS
    return tbl.get(label, label)
