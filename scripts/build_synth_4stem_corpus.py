"""Build a deterministic synthetic 4-stem corpus for CI accuracy tests.

The corpus is generated in pure Python from a fixed RNG seed so every
CI run produces bit-identical audio. Each "song" gives us four ground-
truth stems (vocals + drums + bass + other) plus a mixture, in the exact
MUSDB18 layout the existing test_separation_*_regression.py tests expect:

    <out>/<song-N>/
        mixture.wav
        vocals.wav
        drums.wav
        bass.wav
        other.wav

Why synth instead of real MUSDB18?
  * MUSDB18 is 30 GB, licensed, requires manual download — impossible
    in CI.
  * For *regression* purposes (catch a separator behavioural drift) we
    don't need real timbres — any deterministic multi-source mix where
    the separator's job is to disentangle them works fine.
  * SDR on these synth tracks won't match real-world SDR but the
    *relative* movement track-to-track is what catches regressions.

Each generated stem has:
  * vocals  — formant-modulated sawtooth, vibrato, intermittent gaps
  * drums   — kick + snare + hi-hat patterns
  * bass    — single-note electric-bass-esque saw with envelope
  * other   — chord pad (square-wave additive synth)

Run:  python scripts/build_synth_4stem_corpus.py --out data/synth_musdb
"""

from __future__ import annotations

import argparse
import math
import os
import struct
import wave
from pathlib import Path

import numpy as np


SR = 22050  # Mono; tests resample as needed. Lower SR = faster CI.
DUR_SEC = 6.0
SEED = 20260527


# ── Tiny synthesis primitives ────────────────────────────────────────

def _sine(freq: float, dur: float, sr: int = SR, phase: float = 0.0) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return np.sin(2 * math.pi * freq * t + phase).astype(np.float32)


def _saw(freq: float, dur: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return (2.0 * (t * freq - np.floor(t * freq + 0.5))).astype(np.float32)


def _adsr(n: int, a: float, d: float, s: float, r: float, *, sr: int = SR) -> np.ndarray:
    env = np.zeros(n, dtype=np.float32)
    a_n = int(sr * a); d_n = int(sr * d); r_n = int(sr * r)
    sus_n = max(0, n - a_n - d_n - r_n)
    i = 0
    if a_n:
        env[i:i + a_n] = np.linspace(0.0, 1.0, a_n, dtype=np.float32); i += a_n
    if d_n:
        env[i:i + d_n] = np.linspace(1.0, s, d_n, dtype=np.float32); i += d_n
    if sus_n:
        env[i:i + sus_n] = s; i += sus_n
    if r_n:
        end_amp = env[i - 1] if i > 0 else s
        env[i:i + r_n] = np.linspace(end_amp, 0.0, r_n, dtype=np.float32)
    return env


def _make_vocals(rng: np.random.Generator) -> np.ndarray:
    """Vibrato saw at A3..C4 with random gaps."""
    n_total = int(DUR_SEC * SR)
    out = np.zeros(n_total, dtype=np.float32)
    notes = [220.0, 247.0, 262.0, 294.0, 330.0, 262.0, 247.0, 220.0]
    note_len = DUR_SEC / len(notes)
    for i, f in enumerate(notes):
        if rng.random() < 0.1:                           # 10% rest
            continue
        vib = 1.0 + 0.005 * np.sin(2 * math.pi * 5.5
                                    * np.arange(int(note_len * SR)) / SR)
        seg = _saw(f, note_len) * vib.astype(np.float32)
        env = _adsr(len(seg), 0.04, 0.06, 0.7, 0.15)
        seg = seg * env * 0.30
        start = int(i * note_len * SR)
        out[start:start + len(seg)] += seg
    return out


def _make_drums(rng: np.random.Generator) -> np.ndarray:
    """Kick on 1+3, snare on 2+4, closed hi-hat on every 8th."""
    n_total = int(DUR_SEC * SR)
    out = np.zeros(n_total, dtype=np.float32)
    bpm = 100.0
    beat_sec = 60.0 / bpm
    # 8th-note grid for 6 seconds → 6/beat_sec*2 ≈ 20 hits.
    n_eighths = int(DUR_SEC / (beat_sec / 2))
    for i in range(n_eighths):
        t = i * beat_sec / 2
        s = int(t * SR)
        # Kick on every downbeat (beat 1 & 3 in a 4/4 grid).
        if i % 4 == 0:
            kick = _sine(60.0, 0.12) * _adsr(int(0.12 * SR), 0.001, 0.04, 0.0, 0.06)
            e = min(n_total, s + len(kick))
            out[s:e] += kick[:e - s] * 0.6
        # Snare on beat 2 & 4.
        if i % 4 == 2:
            noise = rng.standard_normal(int(0.08 * SR)).astype(np.float32)
            snare = noise * _adsr(len(noise), 0.001, 0.03, 0.0, 0.04) * 0.5
            e = min(n_total, s + len(snare))
            out[s:e] += snare[:e - s]
        # Hi-hat every 8th, half-amp on off-beats.
        noise = rng.standard_normal(int(0.03 * SR)).astype(np.float32)
        # Crude high-pass via differentiation.
        noise = np.diff(noise, prepend=0).astype(np.float32)
        hh = noise * _adsr(len(noise), 0.001, 0.015, 0.0, 0.01) * 0.18
        if i % 2 == 1:
            hh *= 0.7
        e = min(n_total, s + len(hh))
        out[s:e] += hh[:e - s]
    return out


def _make_bass(rng: np.random.Generator) -> np.ndarray:
    """Walking bass: root on the downbeat, fifth halfway, root."""
    n_total = int(DUR_SEC * SR)
    out = np.zeros(n_total, dtype=np.float32)
    roots = [55.0, 73.42, 82.41, 55.0]              # A1, D2, E2, A1
    bar_sec = DUR_SEC / len(roots)
    for i, f in enumerate(roots):
        for off, ratio in ((0.0, 1.0), (bar_sec * 0.5, 1.5)):
            seg = _saw(f * ratio, 0.25) * _adsr(int(0.25 * SR),
                                                 0.005, 0.05, 0.4, 0.12) * 0.35
            s = int((i * bar_sec + off) * SR)
            e = min(n_total, s + len(seg))
            out[s:e] += seg[:e - s]
    # Light noise floor for realism.
    out += 0.005 * rng.standard_normal(n_total).astype(np.float32)
    return out


def _make_other(rng: np.random.Generator) -> np.ndarray:
    """Square-wave chord pad — A minor / D minor / E major / A minor."""
    n_total = int(DUR_SEC * SR)
    out = np.zeros(n_total, dtype=np.float32)
    chords = [
        [220.0, 261.6, 329.6],     # A minor
        [294.0, 349.2, 440.0],     # D minor
        [330.0, 415.3, 494.0],     # E major
        [220.0, 261.6, 329.6],     # A minor
    ]
    bar_sec = DUR_SEC / len(chords)
    for i, chord in enumerate(chords):
        seg = np.zeros(int(bar_sec * SR), dtype=np.float32)
        for f in chord:
            seg += _saw(f, bar_sec) * 0.08
        # Soft attack/decay on each bar so it doesn't sound like a buzz.
        env = _adsr(len(seg), 0.1, 0.1, 0.7, 0.2)
        seg *= env
        s = int(i * bar_sec * SR)
        e = min(n_total, s + len(seg))
        out[s:e] += seg[:e - s]
    out += 0.003 * rng.standard_normal(n_total).astype(np.float32)
    return out


def _write_wav(path: Path, mono: np.ndarray, sr: int = SR) -> None:
    # Always stereo so the existing tests' `always_2d=True` reads work.
    stereo = np.stack([mono, mono], axis=1)
    stereo = np.clip(stereo, -1.0, 1.0)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def build_corpus(out_dir: Path, n_songs: int = 4) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i in range(n_songs):
        song_dir = out_dir / f"synth-song-{i + 1:02d}"
        song_dir.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(SEED + i)
        vocals = _make_vocals(rng)
        drums = _make_drums(rng)
        bass = _make_bass(rng)
        other = _make_other(rng)
        mix = vocals + drums + bass + other
        peak = max(1e-6, float(np.max(np.abs(mix))))
        if peak > 1.0:                                # normalise headroom
            scale = 0.95 / peak
            vocals *= scale; drums *= scale; bass *= scale
            other *= scale; mix *= scale
        _write_wav(song_dir / "vocals.wav", vocals)
        _write_wav(song_dir / "drums.wav", drums)
        _write_wav(song_dir / "bass.wav", bass)
        _write_wav(song_dir / "other.wav", other)
        _write_wav(song_dir / "mixture.wav", mix)
        written.append(song_dir)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/synth_musdb",
                    help="output directory (default: data/synth_musdb)")
    ap.add_argument("--songs", type=int, default=4,
                    help="number of synthetic songs to generate")
    args = ap.parse_args()
    root = Path(args.out).resolve()
    paths = build_corpus(root, args.songs)
    print(f"[ok] wrote {len(paths)} songs under {root}")
    for p in paths:
        print(f"  · {p.relative_to(root.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
