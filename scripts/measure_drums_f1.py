"""Measure drum-transcription F1 on the deterministic synthetic kit corpus.

Generates a synth drums track with *known* kick/snare/hh ground-truth
onsets, runs the heuristic transcribe() backend (Tier 2, the active path
on Python 3.11), and computes per-instrument F1 within a ±50 ms window.

This is a *self-test*: we control the ground truth so we can pin the
heuristic's accuracy without needing EGMD or any licensed dataset.

Output: data/qa/drums_f1_<date>.json
Updates: tests/fixtures/accuracy_thresholds.json:transcribe.drum_f1 is
the gate the CI checks against.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import tempfile
import wave
from pathlib import Path

import numpy as np


SR = 44100
DUR = 8.0
SEED = 20260527
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "qa" / f"drums_f1_{dt.date.today().isoformat()}.json"
ONSET_TOL_SEC = 0.050    # ±50 ms is the standard MIREX drum tolerance


def _sine(freq, dur, sr=SR, phase=0):
    t = np.arange(int(dur * sr)) / sr
    return np.sin(2 * math.pi * freq * t + phase).astype(np.float32)


def _adsr(n, a, d, s, r, sr=SR):
    env = np.zeros(n, dtype=np.float32)
    a_n, d_n, r_n = int(sr * a), int(sr * d), int(sr * r)
    sus_n = max(0, n - a_n - d_n - r_n)
    i = 0
    if a_n:
        env[i:i + a_n] = np.linspace(0, 1, a_n); i += a_n
    if d_n:
        env[i:i + d_n] = np.linspace(1, s, d_n); i += d_n
    if sus_n:
        env[i:i + sus_n] = s; i += sus_n
    if r_n:
        env[i:i + r_n] = np.linspace(env[i - 1] if i else s, 0, r_n)
    return env


def _kick(rng):
    n = int(0.15 * SR)
    sweep = np.linspace(120.0, 50.0, n)
    t = np.arange(n) / SR
    phase = 2 * math.pi * np.cumsum(sweep) / SR
    body = np.sin(phase).astype(np.float32)
    body *= _adsr(n, 0.001, 0.05, 0.0, 0.08)
    click = 0.15 * rng.standard_normal(int(0.005 * SR)).astype(np.float32)
    body[:len(click)] += click
    return body * 0.85


def _snare(rng):
    n = int(0.18 * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    body = 0.5 * _sine(180.0, 0.18) + 0.7 * noise
    body *= _adsr(n, 0.001, 0.03, 0.0, 0.13)
    return body * 0.65


def _hihat_closed(rng):
    n = int(0.05 * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    # crude high-pass
    noise = np.diff(noise, prepend=0).astype(np.float32)
    return noise * _adsr(n, 0.001, 0.015, 0.0, 0.025) * 0.45


def synth_kit_track(bpm: float = 100.0, seed: int = SEED) -> tuple[np.ndarray, dict]:
    """Generate a kick/snare/hh pattern + ground-truth onset times."""
    rng = np.random.default_rng(seed)
    n_total = int(DUR * SR)
    out = np.zeros(n_total, dtype=np.float32)
    beat = 60.0 / bpm
    n_beats = int(DUR / (beat / 2))           # 8th-note grid
    gt = {"kick": [], "snare": [], "hihat": []}
    for i in range(n_beats):
        t = i * beat / 2
        s = int(t * SR)

        # Kick on beats 1 & 3 (every 4 eighths).
        if i % 4 == 0:
            k = _kick(rng)
            e = min(n_total, s + len(k))
            out[s:e] += k[:e - s]
            gt["kick"].append(t)

        # Snare on beats 2 & 4.
        if i % 4 == 2:
            sn = _snare(rng)
            e = min(n_total, s + len(sn))
            out[s:e] += sn[:e - s]
            gt["snare"].append(t)

        # Hi-hat every 8th.
        hh = _hihat_closed(rng)
        e = min(n_total, s + len(hh))
        out[s:e] += hh[:e - s] * (0.8 if i % 2 == 0 else 0.55)
        gt["hihat"].append(t)

    # Normalise.
    peak = float(np.max(np.abs(out)) + 1e-9)
    out *= min(0.95, 0.95 / peak)
    return out, gt


def _write_wav(path: Path, mono: np.ndarray, sr: int = SR) -> None:
    stereo = np.stack([mono, mono], axis=1)
    stereo = np.clip(stereo, -1.0, 1.0)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def _onset_f1(gt_times: list[float], pred_times: list[float],
              tol: float = ONSET_TOL_SEC) -> tuple[float, float, float]:
    """Bipartite onset matching, returns (precision, recall, f1)."""
    if not gt_times and not pred_times:
        return 1.0, 1.0, 1.0
    if not gt_times:
        return 0.0, 1.0, 0.0
    if not pred_times:
        return 1.0, 0.0, 0.0
    matched = [False] * len(pred_times)
    tp = 0
    pred_arr = np.asarray(pred_times)
    for gt in gt_times:
        diffs = np.abs(pred_arr - gt)
        # Pick the nearest unmatched prediction within tolerance.
        order = np.argsort(diffs)
        for idx in order:
            if matched[idx]:
                continue
            if diffs[idx] <= tol:
                matched[idx] = True
                tp += 1
                break
            else:
                break
    fp = sum(1 for m in matched if not m)
    fn = len(gt_times) - tp
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def main() -> int:
    print(f"[info] synth drums F1 @ SR={SR}, dur={DUR}s, seed={SEED}")
    audio, gt = synth_kit_track()
    n_kick = len(gt["kick"])
    n_snare = len(gt["snare"])
    n_hihat = len(gt["hihat"])
    print(f"[info] GT -kick={n_kick}, snare={n_snare}, hihat={n_hihat}")

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "drums.wav"
        _write_wav(wav, audio)

        from backend.app.pipeline.transcribe_backends.a2d2 import (
            transcribe,
            GM_KICK, GM_SNARE, GM_HH_CLOSED, GM_HH_OPEN,
        )
        pm, _events = transcribe(wav)
        pred = {"kick": [], "snare": [], "hihat": []}
        for inst in pm.instruments:
            for n in inst.notes:
                p = int(n.pitch)
                if p == GM_KICK:
                    pred["kick"].append(float(n.start))
                elif p == GM_SNARE:
                    pred["snare"].append(float(n.start))
                elif p in (GM_HH_CLOSED, GM_HH_OPEN):
                    pred["hihat"].append(float(n.start))

    report = {
        "date": dt.date.today().isoformat(),
        "seed": SEED,
        "sample_rate": SR,
        "duration_sec": DUR,
        "onset_tolerance_ms": ONSET_TOL_SEC * 1000,
        "per_instrument": {},
        "overall": {},
    }
    for inst in ("kick", "snare", "hihat"):
        p, r, f = _onset_f1(gt[inst], pred[inst])
        report["per_instrument"][inst] = {
            "precision": round(p, 3), "recall": round(r, 3),
            "f1": round(f, 3),
            "gt_count": len(gt[inst]),
            "predicted_count": len(pred[inst]),
        }
        print(f"  {inst:6s}: P={p:.3f} R={r:.3f} F1={f:.3f}  "
              f"(gt={len(gt[inst])}, pred={len(pred[inst])})")

    # Aggregate (micro-F1).
    tp_sum = fp_sum = fn_sum = 0
    for inst, row in report["per_instrument"].items():
        tp_eq = row["recall"] * row["gt_count"]
        fp_eq = row["predicted_count"] - tp_eq
        fn_eq = row["gt_count"] - tp_eq
        tp_sum += tp_eq; fp_sum += fp_eq; fn_sum += fn_eq
    P = tp_sum / (tp_sum + fp_sum) if (tp_sum + fp_sum) else 0.0
    R = tp_sum / (tp_sum + fn_sum) if (tp_sum + fn_sum) else 0.0
    F = 2 * P * R / (P + R) if (P + R) else 0.0
    report["overall"] = {"precision": round(P, 3), "recall": round(R, 3),
                          "f1": round(F, 3)}
    print(f"  overall: P={P:.3f} R={R:.3f} F1={F:.3f}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[ok] wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
