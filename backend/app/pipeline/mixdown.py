"""Sum a chosen subset of stems back into a single track.

The expensive part (separation) runs once. Mixdown is a thin combiner so
the user can iterate freely on stem selections (e.g. "no drums" today,
"no bass" tomorrow) without re-running the GPU pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.paths import ensure_dir


@dataclass
class MixdownResult:
    out_path: Path
    included_stems: list[str]
    excluded_stems: list[str]
    sample_rate: int
    duration_sec: float


def mixdown_stems(
    stem_paths: dict[str, Path],
    included: list[str],
    out_path: Path,
    target_sr: int = 48000,
    reference_path: Path | None = None,
    eq_match: bool = True,
    eq_boost_cap_db: float = 6.0,
) -> MixdownResult:
    """Sum the included stems into a single stereo wav at target_sr.

    Args:
        stem_paths: e.g. {"vocals": Path(...), "drums": Path(...), ...}
        included: subset of stem names to keep (everything else is excluded).
        out_path: where to write the mixdown (.wav).
        target_sr: resample stems to this rate if they differ (default 48 kHz).
        reference_path: original mix wav. When provided + ``eq_match=True``,
            the mixdown is tone-matched to this reference (restores the EQ
            balance lost when a stem is excluded). Defaults to None (skipped).
        eq_match: enable spectral envelope matching. Only fires when a
            ``reference_path`` is supplied AND the user excluded at least one
            stem (re-summing all stems is already spectrally identical to
            the source, so matching there would be a no-op).
    """
    chosen = [(name, stem_paths[name]) for name in included if name in stem_paths]
    if not chosen:
        raise ValueError(
            f"no stems to mix: included={included!r}, available={list(stem_paths)!r}"
        )

    arrays: list[np.ndarray] = []
    for _name, p in chosen:
        data, sr = sf.read(str(p), dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        if sr != target_sr:
            import librosa
            data = np.stack(
                [librosa.resample(data[:, c], orig_sr=sr, target_sr=target_sr,
                                  res_type="soxr_hq")
                 for c in range(data.shape[1])],
                axis=-1,
            ).astype(np.float32)
        arrays.append(data)

    min_len = min(a.shape[0] for a in arrays)
    arrays = [a[:min_len] for a in arrays]

    mix = np.sum(arrays, axis=0, dtype=np.float32)

    # Spectral envelope match — only when we've actually dropped a stem
    # (re-summing every stem already matches the source by construction,
    # so matching there is wasted FFT work).
    excluded_now = [n for n in stem_paths if n not in included]
    if eq_match and reference_path is not None and excluded_now:
        try:
            ref_data, ref_sr = sf.read(str(reference_path),
                                       dtype="float32", always_2d=True)
            if ref_data.shape[1] == 1:
                ref_data = np.repeat(ref_data, 2, axis=1)
            elif ref_data.shape[1] > 2:
                ref_data = ref_data[:, :2]
            if ref_sr != target_sr:
                import librosa
                ref_data = np.stack(
                    [librosa.resample(ref_data[:, c],
                                      orig_sr=ref_sr, target_sr=target_sr,
                                      res_type="soxr_hq")
                     for c in range(ref_data.shape[1])],
                    axis=-1,
                ).astype(np.float32)
            from .eq_match import eq_match_to_reference
            mix = eq_match_to_reference(
                mix, ref_data, target_sr,
                boost_cap_db=eq_boost_cap_db,
            )
        except Exception:
            # Tone-match is a best-effort polish — never block the mixdown.
            pass

    # Light soft-clip headroom: peak normalization only if we'd otherwise clip.
    peak = float(np.max(np.abs(mix)))
    if peak > 1.0:
        mix *= 0.99 / peak
    else:
        np.clip(mix, -1.0, 1.0, out=mix)

    ensure_dir(out_path.parent)
    sf.write(str(out_path), mix, target_sr, subtype="FLOAT")

    excluded = [n for n in stem_paths if n not in included]
    return MixdownResult(
        out_path=out_path,
        included_stems=[n for n, _ in chosen],
        excluded_stems=excluded,
        sample_rate=target_sr,
        duration_sec=min_len / target_sr,
    )
