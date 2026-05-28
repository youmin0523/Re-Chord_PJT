"""Voice cues for section markers + count-in.

Workflow (matches MultiTracks Playback behaviour):
    section starts at downbeat D.
    We pick downbeat D-prev (one bar earlier, i.e. 4 beats earlier in 4/4).
    Inside that 1-bar pre-roll we lay down:
        beat 1: voice cue ("Verse 1!")
        beat 2..meter: count-in ticks (2, 3, 4 …)
    so the listener naturally lands on D in tempo.

If no prior downbeat exists (e.g. song starts immediately with a section),
the cue is placed in a synthesized pre-roll prepended at time 0 (which
shifts nothing in the original audio — we just mix the cue *into* the same
timeline by clipping anything outside [0, duration]).
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir
from .click import _make_tick
from .sections import BeatGrid, SectionMarker, label_text


# Locale -> default Microsoft Neural voice. Picked for naturalness + clarity
# of short utterances (cue names are 1-2 words).
DEFAULT_VOICE = {
    "ko": "ko-KR-SunHiNeural",
    "en": "en-US-AvaNeural",
}


@dataclass
class CueOverlay:
    """In-memory cue bed ready to be mixed into the master track."""
    sample_rate: int
    audio: np.ndarray                  # (samples, 2) float32
    duration_sec: float
    cues_placed: int


async def _synth_text(text: str, voice: str, out_path: Path) -> None:
    """edge-tts -> mp3 written to out_path."""
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate="+12%")
    await com.save(str(out_path))


def _load_mono_at_sr(path: Path, target_sr: int) -> np.ndarray:
    import soundfile as sf_
    data, sr = sf_.read(str(path), dtype="float32", always_2d=True)
    if data.shape[1] > 1:
        data = data.mean(axis=1, keepdims=True)
    if sr != target_sr:
        import librosa
        data = librosa.resample(
            data[:, 0], orig_sr=sr, target_sr=target_sr, res_type="soxr_hq",
        )[:, None]
    return data.astype(np.float32)[:, 0]


def _section_text(section: SectionMarker, language: str, verse_idx_map: dict) -> str:
    """Return cue text. Numbers repeated sections (Verse 1, Verse 2, Chorus 2)."""
    base = label_text(section.label, language)
    idx = verse_idx_map.get(section.label, 0) + 1
    verse_idx_map[section.label] = idx
    # Only number repeating labels.
    if section.label in ("verse", "chorus", "pre-chorus", "post-chorus"):
        if language == "ko":
            return f"{base} {idx}"
        return f"{base} {idx}"
    return base


def _previous_downbeat(t: float, downbeats: list[float]) -> float | None:
    """Find the largest downbeat strictly before t. Returns None if none."""
    prev = None
    for db in downbeats:
        if db < t - 0.01:
            prev = db
        else:
            break
    return prev


async def _build_cue_overlay(
    sections: list[SectionMarker],
    beat_grid: BeatGrid,
    duration_sec: float,
    sample_rate: int,
    language: str,
    voice: str | None,
    skip_first_intro: bool = True,
) -> CueOverlay:
    voice = voice or DEFAULT_VOICE.get(language, DEFAULT_VOICE["en"])
    n_total = int(duration_sec * sample_rate)
    overlay = np.zeros((n_total, 2), dtype=np.float32)

    if beat_grid.bpm <= 0 or not beat_grid.beats_sec:
        return CueOverlay(sample_rate, overlay, duration_sec, 0)

    beat_sec = 60.0 / beat_grid.bpm
    bar_sec = beat_sec * max(beat_grid.meter, 1)
    pre_roll_beats = beat_grid.meter      # 1 bar count-in

    verse_idx_map: dict = {}
    cues_placed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for idx, sec in enumerate(sections):
            # Skip leading intro to avoid talking over a pickup or silence.
            if skip_first_intro and idx == 0 and sec.start_sec < beat_sec:
                # we still allow numbering; just don't place a cue at t=0
                _ = _section_text(sec, language, verse_idx_map)
                continue

            # Find the downbeat we want as the "section landing" downbeat.
            db = _previous_downbeat(sec.start_sec, beat_grid.downbeats_sec)
            target_db = sec.start_sec if db is None else (
                sec.start_sec if abs(sec.start_sec - db) > beat_sec * 0.5 else db
            )
            cue_start = target_db - bar_sec    # 1 bar before
            if cue_start < 0:
                # No room for a full bar; nudge to the nearest later downbeat that has room.
                continue

            text = _section_text(sec, language, verse_idx_map)

            # 1) Synthesize the voice and load it.
            mp3 = tmp / f"cue_{idx:03d}.mp3"
            await _synth_text(text, voice, mp3)
            voice_mono = _load_mono_at_sr(mp3, sample_rate)

            # 2) Cap voice length to 1 beat - 50ms so it doesn't bleed into beat 2.
            max_voice_samples = int((beat_sec * 0.92) * sample_rate)
            if voice_mono.shape[0] > max_voice_samples:
                voice_mono = voice_mono[:max_voice_samples]
            # apply a 5 ms fade-out so the truncation isn't audible
            fade = int(0.005 * sample_rate)
            if fade and fade < voice_mono.shape[0]:
                voice_mono[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            # normalize to ~ -6 dBFS for clarity over the music
            peak = float(np.max(np.abs(voice_mono)) or 1e-6)
            voice_mono = voice_mono * (0.5 / peak)

            # 3) Mix voice into the overlay at the cue-start time.
            vstart = int(cue_start * sample_rate)
            vend = vstart + voice_mono.shape[0]
            vend = min(vend, n_total)
            overlay[vstart:vend, 0] += voice_mono[: vend - vstart]
            overlay[vstart:vend, 1] += voice_mono[: vend - vstart]

            # 4) Count-in ticks on beats 2..meter (skip beat 1 = voice slot).
            for b in range(1, pre_roll_beats):
                t = cue_start + b * beat_sec
                tick = _make_tick(
                    sample_rate,
                    freq=2200.0 if b == 0 else 1500.0,
                    dur_sec=0.05,
                    amp=0.55,
                )
                ti = int(t * sample_rate)
                te = min(ti + len(tick), n_total)
                if ti < n_total:
                    overlay[ti:te, 0] += tick[: te - ti]
                    overlay[ti:te, 1] += tick[: te - ti]

            cues_placed += 1

    np.clip(overlay, -1.0, 1.0, out=overlay)
    return CueOverlay(sample_rate, overlay, duration_sec, cues_placed)


def build_voice_cue_overlay(
    sections: list[SectionMarker],
    beat_grid: BeatGrid,
    duration_sec: float,
    sample_rate: int = 48000,
    language: str = "ko",
    voice: str | None = None,
) -> CueOverlay:
    """Sync wrapper around the async TTS pipeline."""
    return asyncio.run(_build_cue_overlay(
        sections, beat_grid, duration_sec, sample_rate, language, voice,
    ))


def write_monitor_track(
    base_audio: Path,
    cue_overlay: np.ndarray | None,
    click_overlay: np.ndarray | None,
    out_path: Path,
    target_sr: int = 48000,
) -> Path:
    """Mix the instrumental + cue + click bed into a single 'monitor' wav."""
    import librosa
    base, sr = sf.read(str(base_audio), dtype="float32", always_2d=True)
    if base.shape[1] == 1:
        base = np.repeat(base, 2, axis=1)
    elif base.shape[1] > 2:
        base = base[:, :2]
    if sr != target_sr:
        base = np.stack(
            [librosa.resample(base[:, c], orig_sr=sr, target_sr=target_sr,
                              res_type="soxr_hq")
             for c in range(2)],
            axis=-1,
        ).astype(np.float32)

    n = base.shape[0]
    mix = base.copy()
    for over in (cue_overlay, click_overlay):
        if over is None:
            continue
        m = min(n, over.shape[0])
        mix[:m] += over[:m]

    np.clip(mix, -1.0, 1.0, out=mix)
    ensure_dir(out_path.parent)
    sf.write(str(out_path), mix, target_sr, subtype="FLOAT")
    return out_path
