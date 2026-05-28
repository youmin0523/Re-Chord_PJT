"""4-stem separation regression (vocals + drums + bass + other).

The original test_separation_regression.py only measures vocals SI-SDR.
For commercial release we also need drums/bass/other accuracy bounds so
a model swap can't silently degrade non-vocal stems.

Requires MUSDB18-HQ layout:
    <root>/<track-name>/vocals.wav
    <root>/<track-name>/drums.wav
    <root>/<track-name>/bass.wav
    <root>/<track-name>/other.wav
    <root>/<track-name>/mixture.wav

Skipping behaviour matches test_separation_regression.py.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest


BASELINE_PATH = Path(__file__).parent / "fixtures" / "separation_4stem_baseline.json"
THRESHOLDS_PATH = Path(__file__).parent / "fixtures" / "accuracy_thresholds.json"

STEMS = ("vocals", "drums", "bass", "other")


def _si_sdr(reference: np.ndarray, estimate: np.ndarray) -> float:
    if reference.ndim > 1:
        reference = reference.mean(axis=-1)
    if estimate.ndim > 1:
        estimate = estimate.mean(axis=-1)
    n = min(reference.shape[0], estimate.shape[0])
    reference = reference[:n].astype(np.float64)
    estimate = estimate[:n].astype(np.float64)
    reference = reference - reference.mean()
    estimate = estimate - estimate.mean()
    denom = (reference * reference).sum() + 1e-12
    proj = (estimate * reference).sum() / denom
    target = proj * reference
    noise = estimate - target
    return float(10.0 * np.log10((target * target).sum() / ((noise * noise).sum() + 1e-12)))


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {"per_stem_mean_db": {}, "tracks": {}}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _write_baseline(per_stem_mean: dict[str, float], tracks: dict) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps({"per_stem_mean_db": per_stem_mean, "tracks": tracks},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_thresholds() -> dict:
    if not THRESHOLDS_PATH.exists():
        return {}
    return json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def test_4stem_si_sdr_does_not_regress(request):
    root = os.environ.get("RECHORD_MUSDB_ROOT")
    if not root:
        pytest.skip("RECHORD_MUSDB_ROOT not set — skipping 4-stem regression")
    root_path = Path(root)
    if not root_path.exists():
        pytest.skip(f"MUSDB root not found: {root}")

    try:
        import soundfile as sf
        from backend.app.pipeline.separate import separate_two_stem, MODELS
    except Exception as e:
        pytest.skip(f"audio-separator import failed: {e!r}")

    track_dirs = []
    for d in sorted(root_path.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "mixture.wav").exists():
            continue
        if all((d / f"{s}.wav").exists() for s in STEMS):
            track_dirs.append(d)
    track_dirs = track_dirs[:6]
    if not track_dirs:
        pytest.skip(f"no MUSDB-shaped 4-stem tracks in {root}")

    htdemucs_6s = MODELS.get("htdemucs_6s")
    if not htdemucs_6s:
        pytest.skip("htdemucs_6s not registered in MODELS")

    per_stem: dict[str, list[float]] = {s: [] for s in STEMS}
    tracks: dict[str, dict[str, float]] = {}

    with tempfile.TemporaryDirectory() as tmp:
        for d in track_dirs:
            mix = d / "mixture.wav"
            try:
                res = separate_two_stem(mix, f"reg4_{d.name}", htdemucs_6s)
            except Exception as e:
                print(f"  ! {d.name}: separator failed ({e!r})")
                continue
            row: dict[str, float] = {}
            for stem in STEMS:
                ref_p = d / f"{stem}.wav"
                est_p = res.stems.get(stem)
                if not est_p or not Path(est_p).exists():
                    continue
                ref, _ = sf.read(str(ref_p), dtype="float32", always_2d=True)
                est, _ = sf.read(str(est_p), dtype="float32", always_2d=True)
                sdr = _si_sdr(ref, est)
                per_stem[stem].append(sdr)
                row[stem] = round(sdr, 2)
                print(f"  {d.name} [{stem}]: SI-SDR = {sdr:+.2f} dB")
            tracks[d.name] = row

    means = {s: float(np.mean(v)) for s, v in per_stem.items() if v}
    if not means:
        pytest.skip("no valid SI-SDR measurements obtained")

    print(f"\n  per-stem mean SI-SDR: {means}")

    if request.config.getoption("--update-baseline", default=False):
        _write_baseline(means, tracks)
        pytest.skip("4-stem baseline updated")

    baseline = _load_baseline().get("per_stem_mean_db") or {}
    thresholds = _load_thresholds().get("separation", {})
    slack = thresholds.get("regression_slack_db", {}).get("min", 0.3)

    failures: list[str] = []
    for stem, m in means.items():
        base = baseline.get(stem)
        if base is None:
            continue
        if m < base - slack:
            failures.append(f"{stem}: {m:+.2f} < baseline {base:+.2f} - {slack:.2f}")

    if failures:
        raise AssertionError(
            "4-stem separation regression:\n  " + "\n  ".join(failures)
        )

    if not baseline:
        _write_baseline(means, tracks)
