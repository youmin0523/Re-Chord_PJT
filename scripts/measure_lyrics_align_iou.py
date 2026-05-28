"""Measure lyrics alignment IoU (Whisper-stamp → onset-nudge polish).

We don't run faster-whisper here (large model, slow). Instead we
synthesize a vocal-onset track with known onset times, write a
mock "word list" where every word's start_sec is intentionally offset
from the ground-truth onset, then run polish_word_timestamps and
measure how much IoU improves.

The point: pin the *floor* on what the onset-based polish can recover
from a Whisper-grade stamp. Real Whisper has its own ±150 ms scatter;
the polish should reduce that scatter to ±30 ms on isolated vocal stems.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


SR = 22050
WORD_GAP_SEC = 0.7              # word-spaced like a verse melody
N_WORDS = 12
SCATTER_MS = 90                  # simulate Whisper word-stamp drift
SCATTER_SEED = 20260527
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "qa" / f"lyrics_align_iou_{dt.date.today().isoformat()}.json"


@dataclass
class FakeWord:
    word: str
    start_sec: float
    end_sec: float
    confidence: float = 0.8


def _synth_vocal_onsets(n_words: int = N_WORDS) -> tuple[np.ndarray, list[float]]:
    """Generate ``n_words`` short vowel-like tone bursts at fixed intervals.

    Returns (audio, onset_times_sec).
    """
    onsets = [0.4 + i * WORD_GAP_SEC for i in range(n_words)]
    total_dur = onsets[-1] + 0.5
    n_total = int(total_dur * SR)
    audio = np.zeros(n_total, dtype=np.float32)
    rng = np.random.default_rng(SCATTER_SEED)
    for t in onsets:
        # Each "syllable": short vowel chord (220+330 Hz) with envelope.
        dur = 0.28
        n = int(dur * SR)
        t_arr = np.arange(n) / SR
        wave_ = 0.4 * (np.sin(2 * math.pi * 220 * t_arr)
                       + 0.3 * np.sin(2 * math.pi * 330 * t_arr))
        # Sharp attack, gentle decay so onset_detect picks the start.
        env = np.exp(-t_arr / 0.12).astype(np.float32)
        wave_ = (wave_.astype(np.float32) * env)
        s = int(t * SR)
        e = min(n_total, s + n)
        audio[s:e] += wave_[:e - s]
    # Mild noise so onset_detect doesn't lock onto numerical zero floor.
    audio += 0.002 * rng.standard_normal(n_total).astype(np.float32)
    return np.clip(audio, -1.0, 1.0), onsets


def _write_wav(path: Path, mono: np.ndarray) -> None:
    stereo = np.stack([mono, mono], axis=1)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def _iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    s = max(a_start, b_start)
    e = min(a_end, b_end)
    inter = max(0.0, e - s)
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter / union if union > 0 else 0.0


def main() -> int:
    print(f"[info] lyrics align IoU @ SR={SR}, words={N_WORDS}, "
          f"scatter±{SCATTER_MS}ms, seed={SCATTER_SEED}")
    audio, gt_onsets = _synth_vocal_onsets()

    # GT word durations: 0.5 s each (matches our synth syllable length).
    gt_words = [(t, t + 0.5) for t in gt_onsets]

    # Whisper-like noisy word list: each start offset by ±SCATTER_MS.
    rng = np.random.default_rng(SCATTER_SEED)
    noisy: list[FakeWord] = []
    for i, (gs, ge) in enumerate(gt_words):
        drift = rng.uniform(-SCATTER_MS, SCATTER_MS) / 1000.0
        noisy.append(FakeWord(f"w{i}", gs + drift, ge + drift))

    iou_before = float(np.mean(
        [_iou(w.start_sec, w.end_sec, gs, ge)
         for w, (gs, ge) in zip(noisy, gt_words)]
    ))

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "vocals.wav"
        _write_wav(wav, audio)
        from backend.app.pipeline.lyrics_align import polish_word_timestamps
        stats = polish_word_timestamps(
            noisy, wav, max_nudge_ms=180.0, sample_rate=SR,
        )

    iou_after = float(np.mean(
        [_iou(w.start_sec, w.end_sec, gs, ge)
         for w, (gs, ge) in zip(noisy, gt_words)]
    ))

    report = {
        "date": dt.date.today().isoformat(),
        "scatter_ms": SCATTER_MS,
        "seed": SCATTER_SEED,
        "n_words": N_WORDS,
        "polish_stats": stats,
        "iou_before": round(iou_before, 3),
        "iou_after": round(iou_after, 3),
        "iou_delta": round(iou_after - iou_before, 3),
    }
    print(f"  IoU before polish: {iou_before:.3f}")
    print(f"  IoU after polish:  {iou_after:.3f}  "
          f"(Δ {iou_after - iou_before:+.3f})")
    print(f"  polish stats: {stats}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[ok] wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
