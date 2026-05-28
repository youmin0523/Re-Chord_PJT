"""Pitch shift + time stretch via librubberband.

Two execution paths:
  1) "finer" engine via rubberband-cli (R3, Ableton/Logic-grade, slower).
     Selected when rubberband.exe is on PATH OR vendored at bin/rubberband.exe.
  2) "faster" engine via ffmpeg's built-in rubberband filter (R2, fallback).
     ffmpeg 8.1 does NOT expose the R3 engine selector, so the ffmpeg path
     is forced to R2 even if the user requests "finer".

Per-stem presets pick the most natural Rubber Band knobs for each stem kind.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


RubberbandEngine = Literal["finer", "faster", "auto"]
StemKind = Literal[
    "instrumental", "vocals", "drums", "bass", "harmonic", "mix", "generic",
]


# Per-stem-kind preset tuned for natural perception.
# rubberband-cli flag names (R3 path):
#   --pitch-hq  ON for high pitch quality
#   --crisp / --smooth  trade transient sharpness vs smoothness (0-3 or named)
#   --formant / --no-formant
#   --realtime not used (we run offline)
#   --window-short / --window-long
#
# ffmpeg rubberband filter options (R2 fallback path):
#   transients=crisp|mixed|smooth
#   detector=compound|percussive|soft
#   phase=laminar|independent
#   window=standard|short|long
#   smoothing=off|on
#   formant=shifted|preserved
#   pitchq=quality|speed|consistency
@dataclass(frozen=True)
class StemPreset:
    # rubberband CLI (R3) flags
    cli_crispness: int            # 0..6 — see rubberband --full-help mapping
    cli_formant: bool             # --formant
    cli_centre_focus: bool        # --centre-focus (good for vocals & stereo mixes)
    cli_window: str               # "standard" | "short" | "long"
    # ffmpeg R2 fallback flags
    transients: str               # crisp|mixed|smooth
    detector: str                 # compound|percussive|soft
    phase: str                    # laminar|independent
    window: str                   # standard|short|long
    smoothing: str                # off|on
    formant: str                  # shifted|preserved


# Crispness reference (rubberband --full-help):
#   0  --no-transients --no-lamination --window-long
#   1  --detector-soft --no-lamination --window-long       (good for piano)
#   2  --no-transients --no-lamination
#   3  --no-transients
#   4  --bl-transients
#   5  default
#   6  --no-lamination --window-short                       (good for drums)
PRESETS: dict[StemKind, StemPreset] = {
    "instrumental": StemPreset(
        cli_crispness=4, cli_formant=False, cli_centre_focus=True, cli_window="standard",
        transients="mixed", detector="compound", phase="laminar",
        window="standard", smoothing="on", formant="shifted",
    ),
    "vocals": StemPreset(
        cli_crispness=4, cli_formant=True, cli_centre_focus=True, cli_window="standard",
        transients="mixed", detector="soft", phase="laminar",
        window="standard", smoothing="on", formant="preserved",
    ),
    "drums": StemPreset(
        cli_crispness=6, cli_formant=False, cli_centre_focus=False, cli_window="short",
        transients="crisp", detector="percussive", phase="independent",
        window="short", smoothing="off", formant="shifted",
    ),
    "bass": StemPreset(
        cli_crispness=4, cli_formant=False, cli_centre_focus=False, cli_window="standard",
        transients="mixed", detector="compound", phase="laminar",
        window="standard", smoothing="off", formant="shifted",
    ),
    "harmonic": StemPreset(
        cli_crispness=1, cli_formant=False, cli_centre_focus=False, cli_window="long",
        transients="smooth", detector="soft", phase="laminar",
        window="long", smoothing="on", formant="shifted",
    ),
    "mix": StemPreset(
        cli_crispness=5, cli_formant=False, cli_centre_focus=True, cli_window="standard",
        transients="mixed", detector="compound", phase="laminar",
        window="standard", smoothing="on", formant="shifted",
    ),
    "generic": StemPreset(
        cli_crispness=5, cli_formant=False, cli_centre_focus=False, cli_window="standard",
        transients="mixed", detector="compound", phase="laminar",
        window="standard", smoothing="on", formant="shifted",
    ),
}


@dataclass
class TransformResult:
    out_path: Path
    semitones: float
    tempo_ratio: float
    engine: str
    stem_kind: str
    elapsed_sec: float


def semitones_to_pitch_ratio(semitones: float) -> float:
    return 2.0 ** (semitones / 12.0)


def bpm_to_tempo_ratio(source_bpm: float, target_bpm: float) -> float:
    if source_bpm <= 0 or target_bpm <= 0:
        return 1.0
    return target_bpm / source_bpm


# --- engine discovery ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def find_rubberband_cli() -> str | None:
    """Find rubberband(-r3)(.exe) on PATH or vendored at <root>/bin/.

    Prefers the dedicated R3 binary when it's available (faster path through
    the R3 codepath, no need for explicit --fine flag).
    """
    for name in ("rubberband-r3", "rubberband"):
        exe = shutil.which(name)
        if exe:
            return exe
    for candidate in (
        PROJECT_ROOT / "bin" / "rubberband-r3.exe",
        PROJECT_ROOT / "bin" / "rubberband.exe",
        PROJECT_ROOT / "bin" / "rubberband-r3",
        PROJECT_ROOT / "bin" / "rubberband",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def resolve_engine(requested: RubberbandEngine) -> tuple[str, str | None]:
    """Resolve which engine to actually run.

    Returns (engine_label, cli_path_or_None).
    engine_label is one of:
        "r3-finer-cli"       - rubberband CLI with R3 engine (best)
        "r2-finer-ffmpeg"    - ffmpeg's R2 engine (ffmpeg can't expose R3)
        "r2-faster-ffmpeg"   - ffmpeg R2 explicit fallback
    """
    if requested == "faster":
        return "r2-faster-ffmpeg", None
    cli = find_rubberband_cli()
    if cli and requested in ("finer", "auto"):
        return "r3-finer-cli", cli
    return "r2-finer-ffmpeg", None


# --- main API -----------------------------------------------------------------

def transform_dual_render(
    input_path: Path,
    out_dir: Path,
    semitones: float,
    tempo_ratio: float = 1.0,
    stem_kind: StemKind = "vocals",
) -> dict[str, TransformResult | None]:
    """Render both Rubber Band R3 and WORLD vocoder variants for A/B.

    Use case: at the 4-6 semitone vocal-shift boundary, neither engine
    dominates — Rubber Band sounds tighter on consonants, WORLD preserves
    formant integrity on sustained vowels. Letting the user A/B them is
    cheaper than us guessing.

    Returns a dict {"rubberband": TransformResult|None, "world":
    TransformResult|None}. Either entry may be None if its engine isn't
    available; the caller decides what to expose.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, TransformResult | None] = {
        "rubberband": None, "world": None,
    }
    rb_path = out_dir / f"{input_path.stem}_rubberband.wav"
    world_path = out_dir / f"{input_path.stem}_world.wav"

    # Force the Rubber Band path (skip the auto-WORLD threshold).
    try:
        result["rubberband"] = transform_audio(
            input_path, rb_path, semitones, tempo_ratio,
            engine="auto", stem_kind=stem_kind,
            use_world_for_large_vocal_shift=False,
        )
    except Exception:
        result["rubberband"] = None

    # Force the WORLD path (vocals only).
    try:
        from .transform_world import is_available as _world_avail
        from .transform_world import transform_vocal as _world_transform
        if _world_avail():
            t0 = time.perf_counter()
            wr = _world_transform(
                input_path=input_path, out_path=world_path,
                semitones=semitones, tempo_ratio=tempo_ratio,
            )
            result["world"] = TransformResult(
                out_path=wr.out_path, semitones=wr.semitones,
                tempo_ratio=wr.tempo_ratio, engine="world-vocoder",
                stem_kind=stem_kind,
                elapsed_sec=time.perf_counter() - t0,
            )
    except Exception:
        result["world"] = None

    return result


def transform_audio(
    input_path: Path,
    out_path: Path,
    semitones: float = 0.0,
    tempo_ratio: float = 1.0,
    engine: RubberbandEngine = "auto",
    stem_kind: StemKind = "generic",
    preserve_formants: bool | None = None,
    *,
    use_world_for_large_vocal_shift: bool = True,
    world_threshold_semitones: float = 5.0,
) -> TransformResult:
    """Pitch / tempo transform.

    Args:
        engine: 'auto' picks R3 cli if available, else R2 ffmpeg.
                'finer' forces R3; falls back to R2 ffmpeg if cli missing.
                'faster' forces R2 ffmpeg.
        stem_kind: selects the preset. Caller (orchestrator) should pass:
                   "vocals" for vocal stems, "drums" for drum stems,
                   "harmonic" for piano/guitar/other, "bass" for bass,
                   "instrumental" for the combined instrumental MR,
                   "mix" for full-mix pre-separation transforms.
        preserve_formants: explicit override. Default = preset's choice.
        use_world_for_large_vocal_shift: when ``stem_kind == 'vocals'`` and
                |semitones| > ``world_threshold_semitones`` (default 5),
                route through the WORLD vocoder for materially better
                formant preservation at large pitch shifts. Auto-falls
                back to Rubber Band if pyworld isn't installed.
    """
    pitch_ratio = semitones_to_pitch_ratio(semitones)

    # Hybrid dispatch: large vocal shift → WORLD path (better formants).
    if (
        use_world_for_large_vocal_shift
        and stem_kind == "vocals"
        and abs(semitones) > world_threshold_semitones
    ):
        try:
            from .transform_world import is_available as world_available
            from .transform_world import transform_vocal as world_transform
            if world_available():
                t0 = time.perf_counter()
                world_res = world_transform(
                    input_path=input_path, out_path=out_path,
                    semitones=semitones, tempo_ratio=tempo_ratio,
                )
                return TransformResult(
                    out_path=world_res.out_path,
                    semitones=world_res.semitones,
                    tempo_ratio=world_res.tempo_ratio,
                    engine="world-vocoder",
                    stem_kind=stem_kind,
                    elapsed_sec=time.perf_counter() - t0,
                )
        except Exception:
            # Any WORLD failure → fall through to Rubber Band.
            pass

    # No-op shortcut.
    if abs(semitones) < 1e-6 and abs(tempo_ratio - 1.0) < 1e-6:
        from .paths import ensure_dir  # type: ignore  # noqa
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if str(input_path) != str(out_path):
            shutil.copyfile(input_path, out_path)
        return TransformResult(
            out_path=out_path, semitones=0.0, tempo_ratio=1.0,
            engine="noop", stem_kind=stem_kind, elapsed_sec=0.0,
        )

    preset = PRESETS.get(stem_kind, PRESETS["generic"])
    formant_pref = preset.cli_formant if preserve_formants is None else preserve_formants

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")

    engine_label, cli_path = resolve_engine(engine)

    t0 = time.perf_counter()
    if engine_label == "r3-finer-cli" and cli_path:
        # rubberband-r3.exe defaults to R3; --fine for the generic binary.
        is_r3_binary = "r3" in Path(cli_path).stem.lower()
        cmd: list[str] = [
            cli_path,
            "-q",                                       # suppress progress
            "--tempo", f"{tempo_ratio:.6f}",            # tempo multiplier
            "--pitch", f"{semitones:.6f}",              # pitch in semitones
            "--crisp", str(preset.cli_crispness),
        ]
        if not is_r3_binary:
            cmd.append("--fine")                        # force R3 on generic binary
        if formant_pref:
            cmd.append("--formant")
        if preset.cli_centre_focus:
            cmd.append("--centre-focus")
        if preset.cli_window == "short":
            cmd.append("--window-short")
        cmd.extend([str(input_path), str(tmp)])
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            # Fall back to ffmpeg if CLI failed.
            engine_label = "r2-finer-ffmpeg"
        else:
            tmp.replace(out_path)

    if engine_label.endswith("-ffmpeg"):
        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            raise RuntimeError("ffmpeg not found on PATH")
        parts = [
            f"pitch={pitch_ratio:.6f}",
            f"tempo={tempo_ratio:.6f}",
            f"transients={preset.transients}",
            f"detector={preset.detector}",
            f"phase={preset.phase}",
            f"window={preset.window}",
            f"smoothing={preset.smoothing}",
            "pitchq=quality",
        ]
        if formant_pref:
            parts.append("formant=preserved")
        af = "rubberband=" + ":".join(parts)
        cmd = [
            ffmpeg_exe, "-y",
            "-i", str(input_path),
            "-vn", "-map_metadata", "-1",
            "-af", af,
            "-c:a", "pcm_f32le",
            "-f", "wav",
            str(tmp),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"rubberband transform failed: {proc.stderr.strip()}")
        tmp.replace(out_path)

    elapsed = time.perf_counter() - t0
    return TransformResult(
        out_path=out_path,
        semitones=semitones,
        tempo_ratio=tempo_ratio,
        engine=engine_label,
        stem_kind=stem_kind,
        elapsed_sec=elapsed,
    )
