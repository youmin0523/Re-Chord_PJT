"""Post-processing forced alignment for Whisper word timestamps.

Whisper's word timestamps are good (~90% IoU on clean speech) but they
slip on:
  * sung vowels longer than a syllable
  * Korean syllables compressed into a single "word"
  * worship long-note holds where the singer's onset/offset doesn't
    match the lyric boundary

Two-stage strategy:

  Primary (when installed): WhisperX (m-bain/whisperX) re-aligns the
  Whisper transcript against a wav2vec2 phoneme model. Reported IoU
  uplift on sung Korean is ~+8-12 pp over Whisper's native timestamps.
  When ``whisperx`` is unavailable, we silently skip this stage.

  Polish (always): nudge each word's start_sec to the nearest onset
  peak in the vocal stem (±120 ms). Catches the residual drift the
  forced alignment can't resolve.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def is_whisperx_available() -> bool:
    try:
        import whisperx  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def forced_align_words(
    words: list,
    vocal_audio: Path,
    *,
    language: str = "ko",
    device: str = "cpu",
) -> dict:
    """Re-align Whisper words against a wav2vec2 phoneme model via WhisperX.

    When ``whisperx`` is installed, this replaces each word's start_sec /
    end_sec with the forced-aligned positions. Otherwise it returns a
    skip stat and leaves ``words`` untouched.

    The wav2vec2 model is auto-downloaded on first use (~1 GB for the
    Korean checkpoint, ~360 MB for English). Falls back to CPU when CUDA
    isn't available.

    Returns: {"aligned": k, "skipped": "<reason>", "model": "..."}.
    Mutates ``words`` in place when aligned > 0.
    """
    if not words or not vocal_audio.exists():
        return {"aligned": 0, "skipped": "no input"}
    if not is_whisperx_available():
        return {"aligned": 0, "skipped": "whisperx not installed"}

    try:
        import whisperx  # type: ignore
        import torch  # type: ignore
    except ImportError as e:
        return {"aligned": 0, "skipped": f"import failed: {e!r}"}

    # Pick device — torch CUDA when available, otherwise CPU.
    use_cuda = False
    try:
        use_cuda = bool(torch.cuda.is_available()) and device != "cpu"
    except Exception:
        use_cuda = False
    actual_device = "cuda" if use_cuda else "cpu"

    # WhisperX expects a "result" dict with "segments" each having "words"
    # with text/start/end. Adapt our LyricWord list to its expected shape.
    def _get(w, k, default=None):
        return (getattr(w, k, None)
                if hasattr(w, k)
                else (w.get(k, default) if isinstance(w, dict) else default))

    segments = [{
        "text": " ".join(str(_get(w, "word", "")) for w in words),
        "start": float(_get(words[0], "start_sec", 0.0) or 0.0),
        "end": float(_get(words[-1], "end_sec", 0.0) or 0.0),
        "words": [
            {"word": str(_get(w, "word", "")),
             "start": float(_get(w, "start_sec", 0.0) or 0.0),
             "end": float(_get(w, "end_sec", 0.0) or 0.0)}
            for w in words
        ],
    }]

    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=language, device=actual_device,
        )
    except Exception as e:
        return {"aligned": 0, "skipped": f"align model load failed: {e!r}"}

    try:
        audio = whisperx.load_audio(str(vocal_audio))
        result = whisperx.align(
            segments, model_a, metadata, audio,
            actual_device, return_char_alignments=False,
        )
    except Exception as e:
        return {"aligned": 0, "skipped": f"align run failed: {e!r}"}

    # Pull the re-aligned per-word timestamps back into our list.
    aligned_words: list[dict] = []
    for seg in result.get("segments", []):
        aligned_words.extend(seg.get("words", []))
    if not aligned_words:
        return {"aligned": 0, "skipped": "align returned no words"}

    # Pair each original word with the aligned counterpart by index.
    # WhisperX preserves word order; when it occasionally drops a word
    # (e.g. unrecognisable token), we skip the original at that slot.
    n_aligned = 0
    j = 0
    for w in words:
        if j >= len(aligned_words):
            break
        aw = aligned_words[j]
        # Skip aligned tokens that have no timing (rare WhisperX quirk).
        s = aw.get("start"); e = aw.get("end")
        if s is None or e is None:
            j += 1
            continue
        # Apply.
        try:
            if hasattr(w, "start_sec"):
                w.start_sec = float(s)
                w.end_sec = float(e)
            elif isinstance(w, dict):
                w["start_sec"] = float(s)
                w["end_sec"] = float(e)
            n_aligned += 1
        except Exception:
            pass
        j += 1

    return {
        "aligned": n_aligned,
        "skipped": "" if n_aligned else "no overlap",
        "model": getattr(metadata, "model_name", "wav2vec2"),
        "device": actual_device,
        "language": language,
    }


def polish_word_timestamps(
    words: list,
    vocal_audio: Path,
    *,
    max_nudge_ms: float = 120.0,
    sample_rate: int = 22050,
) -> dict:
    """Nudge each word's ``start_sec`` toward the nearest onset peak in
    the vocal stem.

    Returns a stats dict ``{"nudged": k, "max_shift_ms": x, "mean_shift_ms": y}``.
    Mutates the input ``words`` list in place (each item must expose
    ``start_sec`` / ``end_sec`` attrs — works on LyricWord dataclass and
    dict-like objects).
    """
    if not words or not vocal_audio.exists():
        return {"nudged": 0, "max_shift_ms": 0.0, "mean_shift_ms": 0.0}

    try:
        import librosa
        y, sr = librosa.load(str(vocal_audio), sr=sample_rate, mono=True)
        # Onset times in seconds for the vocal stem. Tighter parameters
        # than the drum onset detector because vocal onsets are smoother.
        onsets = librosa.onset.onset_detect(
            y=y, sr=sr, units="time", backtrack=True,
            pre_max=15, post_max=15, pre_avg=30, post_avg=30,
            delta=0.05, wait=5,
        )
        if onsets is None or len(onsets) == 0:
            return {"nudged": 0, "max_shift_ms": 0.0, "mean_shift_ms": 0.0}
        onsets = np.asarray(onsets, dtype=np.float64)
    except Exception as e:
        return {"nudged": 0, "max_shift_ms": 0.0, "mean_shift_ms": 0.0,
                "error": f"librosa onset detect failed: {e!r}"}

    max_nudge = max_nudge_ms / 1000.0
    shifts: list[float] = []
    nudged = 0

    def _get_start(w):
        return float(getattr(w, "start_sec", None) or w.get("start_sec", 0.0))

    def _set(w, start, end):
        if hasattr(w, "start_sec"):
            try:
                w.start_sec = start
                w.end_sec = end
                return True
            except Exception:
                return False
        if isinstance(w, dict):
            w["start_sec"] = start
            w["end_sec"] = end
            return True
        return False

    for w in words:
        s = _get_start(w)
        e = float(getattr(w, "end_sec", None) or
                  (w.get("end_sec", s) if isinstance(w, dict) else s))
        if e <= s:
            continue
        idx = int(np.searchsorted(onsets, s))
        candidates = []
        if idx > 0:
            candidates.append(onsets[idx - 1])
        if idx < len(onsets):
            candidates.append(onsets[idx])
        if not candidates:
            continue
        best = min(candidates, key=lambda o: abs(o - s))
        delta = best - s
        if abs(delta) > max_nudge:
            continue
        # Apply the nudge to both start and end so the word's duration
        # is preserved (we're correcting onset, not changing length).
        if _set(w, best, e + delta):
            shifts.append(delta)
            nudged += 1

    if not shifts:
        return {"nudged": 0, "max_shift_ms": 0.0, "mean_shift_ms": 0.0}
    arr = np.asarray(shifts) * 1000.0
    return {
        "nudged": nudged,
        "max_shift_ms": float(np.max(np.abs(arr))),
        "mean_shift_ms": float(np.mean(np.abs(arr))),
    }
