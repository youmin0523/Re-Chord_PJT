"""Beat-synchronous chord recognition (24 major+minor + N/C).

Pure librosa pipeline — no madmom/autochord builds required. Approach:
  1. Harmonic stem of the audio (drum-suppression for cleaner chroma).
  2. Beat-synchronous chroma_cqt aggregated to one chroma vector per beat.
  3. Median-pool beats by downbeat groups (typically one chord per bar).
  4. Correlate each chord chroma against 24 rotated major/minor templates
     and pick the highest-scoring one (Krumhansl-style template matching).
  5. Smooth: drop chords below a confidence floor → "N" (no chord).

Accuracy: simple diatonic pop ≈ 75-85%, jazz/modal ≈ 50-65%.
Users can hand-edit the json downstream.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Binary chord templates (1 = chord tone, 0 = not).
_C_MAJ_TPL = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], dtype=np.float32)
_C_MIN_TPL = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=np.float32)


@dataclass
class ChordEvent:
    start_sec: float
    end_sec: float
    root: str
    quality: str            # "maj" | "min" | "N"
    label: str              # "C", "Am", "N"
    confidence: float       # 0..1 normalized correlation
    # Which refinement stage produced the *final* label for this event.
    # "template" | "crema" | "theory" | "llm" | "bass_check". Lets the UI
    # show provenance ("this chord came from CREMA's 170-class model")
    # so users understand why a given label was chosen.
    source: str = "template"


def _build_templates() -> tuple[np.ndarray, list[tuple[str, str]]]:
    """Returns (24x12 templates, [(root, quality)] in same order)."""
    rows = []
    keys: list[tuple[str, str]] = []
    for shift in range(12):
        rows.append(np.roll(_C_MAJ_TPL, shift))
        keys.append((PITCH_CLASSES[shift], "maj"))
    for shift in range(12):
        rows.append(np.roll(_C_MIN_TPL, shift))
        keys.append((PITCH_CLASSES[shift], "min"))
    M = np.stack(rows, axis=0).astype(np.float32)
    # Normalize each template to unit L2 so the correlation is bounded [0, 1].
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    return M, keys


_TEMPLATES, _TEMPLATE_KEYS = _build_templates()


def _label_for(root: str, quality: str) -> str:
    if quality == "N":
        return "N"
    return f"{root}{'m' if quality == 'min' else ''}"


def analyze_chords(
    audio_path: Path,
    confidence_floor: float = 0.55,
) -> list[ChordEvent]:
    import librosa

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    duration = float(len(y) / sr) if sr else 0.0
    if duration < 1.0:
        return []

    y_h = librosa.effects.harmonic(y, margin=4.0)
    hop = 512

    # Beat tracking for synchronization.
    _, beat_frames = librosa.beat.beat_track(
        y=y_h, sr=sr, hop_length=hop, units="frames",
    )
    if len(beat_frames) < 2:
        beat_frames = np.arange(0, len(y_h) // hop, max(1, sr // hop // 2))
    chroma = librosa.feature.chroma_cqt(
        y=y_h, sr=sr, hop_length=hop, n_chroma=12,
    )
    # Median-pool chroma into per-beat columns.
    chroma_sync = librosa.util.sync(
        chroma, beat_frames, aggregate=np.median,
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)

    # Aggregate beats into 4-beat bars for chord stability.
    BAR = 4
    n_beats = chroma_sync.shape[1]
    chunks: list[tuple[float, float, np.ndarray]] = []
    for i in range(0, n_beats, BAR):
        chunk = chroma_sync[:, i:i + BAR]
        if chunk.size == 0:
            continue
        chroma_vec = chunk.mean(axis=1)
        s = float(beat_times[i]) if i < len(beat_times) else duration
        end_idx = i + chunk.shape[1]
        if end_idx < len(beat_times):
            e = float(beat_times[end_idx])
        else:
            e = duration
        chunks.append((s, e, chroma_vec))

    events: list[ChordEvent] = []
    for s, e, vec in chunks:
        v = vec / (np.linalg.norm(vec) + 1e-9)
        scores = _TEMPLATES @ v       # cosine sim (24,)
        idx = int(np.argmax(scores))
        conf = float(scores[idx])
        if conf < confidence_floor:
            root, quality = "?", "N"
        else:
            root, quality = _TEMPLATE_KEYS[idx]
        ev = ChordEvent(
            start_sec=s,
            end_sec=e,
            root=root,
            quality=quality,
            label=_label_for(root, quality),
            confidence=conf,
        )
        # Stash the chroma the chord spanned so the tension post-processor
        # (chord_tension) can detect add9/6/sus/7 extensions CREMA can't.
        try:
            ev._chroma = vec.astype(float).tolist()
        except Exception:
            pass
        events.append(ev)

    # Merge consecutive identical chords.
    merged: list[ChordEvent] = []
    for ev in events:
        if merged and merged[-1].label == ev.label:
            prev_chroma = getattr(merged[-1], "_chroma", None)
            new = ChordEvent(
                start_sec=merged[-1].start_sec,
                end_sec=ev.end_sec,
                root=ev.root,
                quality=ev.quality,
                label=ev.label,
                confidence=max(merged[-1].confidence, ev.confidence),
            )
            # Preserve chroma for the tension post-processor (average the
            # two spans' chroma so the merged label sees the full window).
            try:
                cur = getattr(ev, "_chroma", None)
                if prev_chroma is not None and cur is not None:
                    new._chroma = [(a + b) / 2 for a, b in zip(prev_chroma, cur)]
                elif cur is not None:
                    new._chroma = cur
                elif prev_chroma is not None:
                    new._chroma = prev_chroma
            except Exception:
                pass
            merged[-1] = new
        else:
            merged.append(ev)
    return merged


def stabilize_chords(
    events: list[ChordEvent],
    downbeats_sec: list[float] | None = None,
    *,
    blip_max_sec: float = 1.6,
    low_confidence_floor: float = 0.60,
) -> list[ChordEvent]:
    """Post-process to remove false positives + snap to downbeat grid.

    Three passes:

    1. **Blip suppression** — single short chord (≤ blip_max_sec) flanked by
       the same chord on both sides is almost always a transient
       misdetection (e.g. a passing tone, drum hit recolouring chroma).
       Merge it into its neighbours.

    2. **Low-confidence inheritance** — chords with confidence below the
       floor inherit the label of their higher-confidence predecessor,
       provided the predecessor's label is not "N".

    3. **Downbeat snap** — if a downbeat grid is provided, snap each chord
       boundary to the nearest downbeat (max ±0.6 s). Keeps the chord chart
       reading on bar lines rather than mid-measure.

    All three are conservative and only fire when they materially improve
    the result. Returns a NEW list; input is not mutated.
    """
    if not events:
        return []

    # 1) Blip suppression.
    cleaned: list[ChordEvent] = []
    i = 0
    while i < len(events):
        ev = events[i]
        dur = ev.end_sec - ev.start_sec
        prev = cleaned[-1] if cleaned else None
        nxt = events[i + 1] if i + 1 < len(events) else None
        is_blip = (
            dur <= blip_max_sec
            and prev is not None
            and nxt is not None
            and prev.label == nxt.label
            and prev.label != ev.label
            and prev.label != "N"
        )
        if is_blip:
            # Absorb ev + nxt into prev.
            merged = ChordEvent(
                start_sec=prev.start_sec,
                end_sec=nxt.end_sec,
                root=prev.root,
                quality=prev.quality,
                label=prev.label,
                confidence=max(prev.confidence, ev.confidence, nxt.confidence),
            )
            cleaned[-1] = merged
            i += 2
        else:
            cleaned.append(ev)
            i += 1

    # 2) Low-confidence inheritance.
    out: list[ChordEvent] = []
    for ev in cleaned:
        if ev.confidence < low_confidence_floor and out and out[-1].label != "N":
            out.append(ChordEvent(
                start_sec=ev.start_sec,
                end_sec=ev.end_sec,
                root=out[-1].root,
                quality=out[-1].quality,
                label=out[-1].label,
                confidence=ev.confidence,        # keep the original conf for honesty
            ))
        else:
            out.append(ev)

    # 3) Downbeat snap.
    if downbeats_sec:
        db = sorted(set(float(t) for t in downbeats_sec))
        snapped: list[ChordEvent] = []
        for ev in out:
            new_start = _snap(ev.start_sec, db, 0.6)
            new_end = _snap(ev.end_sec, db, 0.6)
            if new_end <= new_start:
                new_end = new_start + max(ev.end_sec - ev.start_sec, 0.5)
            snapped.append(ChordEvent(
                start_sec=new_start, end_sec=new_end,
                root=ev.root, quality=ev.quality,
                label=ev.label, confidence=ev.confidence,
            ))
        out = snapped

    # 4) Final merge of consecutive identical labels (snap may have made
    #    boundaries align exactly).
    final: list[ChordEvent] = []
    for ev in out:
        if final and final[-1].label == ev.label and abs(final[-1].end_sec - ev.start_sec) < 0.05:
            final[-1] = ChordEvent(
                start_sec=final[-1].start_sec,
                end_sec=ev.end_sec,
                root=ev.root, quality=ev.quality, label=ev.label,
                confidence=max(final[-1].confidence, ev.confidence),
            )
        else:
            final.append(ev)
    return final


def _snap(t: float, grid: list[float], max_distance: float) -> float:
    """Snap ``t`` to the nearest value in ``grid`` if within ``max_distance``."""
    if not grid:
        return t
    # Binary search would be faster on huge grids; linear is fine for typical
    # song lengths (~ 100-200 downbeats).
    nearest = min(grid, key=lambda g: abs(g - t))
    return nearest if abs(nearest - t) <= max_distance else t


def write_chords_json(events: list[ChordEvent], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "events": [asdict(e) for e in events],
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return out_path


def refine_chords(
    events: list[ChordEvent],
    *,
    key_root: str | None = None,
    key_mode: str | None = None,
    audio_path: Path | None = None,
    downbeats_sec: list[float] | None = None,
    use_crema: bool = True,
    use_theory: bool = True,
    use_llm: bool = True,
    use_tension: bool = True,
    report: dict | None = None,
) -> list[ChordEvent]:
    """Apply the 3-stage SOTA refinement chain on top of the template-match output.

    Stage 0 (always):       beat-aligned stabilizer (``stabilize_chords``).
    Stage 1 (CREMA):        merge with CREMA's 170-class output if installed.
    Stage 2 (theory):       functional-harmony re-ranker (key required).
    Stage 3 (local LLM):    Ollama re-rank low-confidence chords (Ollama
                            running + model pulled).

    ``report``: optional dict the caller can pass in to learn which stages
    actually fired and which fell back. Keys populated: ``stages_run``,
    ``stages_skipped``. Useful for surfacing the backend matrix to the UI.
    """
    if not events:
        return events
    rep_run: list[str] = []
    rep_skip: list[dict[str, str]] = []

    def _label_map(evs):
        """Snapshot {round(start,2): label} so we can detect which events
        a stage changed and tag their ``source`` accordingly."""
        return {round(float(getattr(e, "start_sec", 0)), 2):
                getattr(e, "label", "") for e in evs}

    def _tag_changes(evs, before: dict, stage: str):
        for e in evs:
            k = round(float(getattr(e, "start_sec", 0)), 2)
            if before.get(k) != getattr(e, "label", "") and before.get(k) is not None:
                try:
                    e.source = stage
                except Exception:
                    pass

    # Stage 0a: chroma tension enrichment — runs on the freshly analyzed
    # events (while their _chroma is still attached) to add the add9/6/
    # sus/7 extensions CREMA can't output. We do this BEFORE CREMA so a
    # later CREMA call can still override with its own (often more
    # confident) 7th/sus reading; enrich_label only touches chords that
    # are still plain triads, so nothing double-applies.
    if use_tension:
        try:
            import numpy as _np
            from .chord_tension import apply_tension_enrichment
            chroma_by_event = [
                _np.asarray(getattr(e, "_chroma", None))
                if getattr(e, "_chroma", None) is not None else None
                for e in events
            ]
            if any(c is not None for c in chroma_by_event):
                t_stats = apply_tension_enrichment(events, chroma_by_event)
                if t_stats.get("enriched"):
                    rep_run.append("tension")
            else:
                rep_skip.append({"stage": "tension", "reason": "no chroma on events"})
        except Exception as e:
            rep_skip.append({"stage": "tension", "reason": f"runtime: {type(e).__name__}"})

    # Stage 0b: stabilize (blip suppression + downbeat snap).
    refined = stabilize_chords(events, downbeats_sec=downbeats_sec)
    rep_run.append("stabilize")

    # Stage 1: CREMA fusion (if installed AND we have the audio).
    if use_crema and audio_path is not None:
        try:
            from .chord_crema import is_available as crema_available
            from .chord_crema import transcribe_chords as crema_transcribe
            from .chord_crema import merge_with_template
            if crema_available():
                before = _label_map(refined)
                crema_events = crema_transcribe(audio_path)
                refined = merge_with_template(refined, crema_events)
                _tag_changes(refined, before, "crema")
                rep_run.append("crema")
            else:
                rep_skip.append({"stage": "crema", "reason": "not installed"})
        except Exception as e:
            rep_skip.append({"stage": "crema", "reason": f"runtime: {type(e).__name__}"})
    elif use_crema:
        rep_skip.append({"stage": "crema", "reason": "no audio path"})

    # Stage 2: functional-harmony re-rank (needs detected key).
    if use_theory and key_root:
        try:
            from .chord_theory import rerank as theory_rerank
            before = _label_map(refined)
            refined = theory_rerank(refined, key_root, key_mode or "major")
            _tag_changes(refined, before, "theory")
            rep_run.append("theory")
        except Exception as e:
            rep_skip.append({"stage": "theory", "reason": f"runtime: {type(e).__name__}"})
    elif use_theory:
        rep_skip.append({"stage": "theory", "reason": "no key detected"})

    # Stage 3: LLM re-rank (only fires when Ollama is reachable).
    if use_llm and key_root:
        try:
            from .chord_llm import rerank as llm_rerank
            key_name = f"{key_root} {key_mode or 'major'}"
            before = _label_map(refined)
            refined = llm_rerank(refined, key_name)
            _tag_changes(refined, before, "llm")
            rep_run.append("llm")
        except Exception as e:
            rep_skip.append({"stage": "llm", "reason": f"runtime: {type(e).__name__}"})
    elif use_llm:
        rep_skip.append({"stage": "llm", "reason": "no key detected"})

    if report is not None:
        report["stages_run"] = rep_run
        report["stages_skipped"] = rep_skip
        # Provenance histogram — how many chords each stage decided.
        hist: dict[str, int] = {}
        for e in refined:
            src = getattr(e, "source", "template")
            hist[src] = hist.get(src, 0) + 1
        report["source_histogram"] = hist
    return refined
