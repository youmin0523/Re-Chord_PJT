"""Separation-quality regression test.

When MUSDB18 (or any folder of {mixture.wav, vocals.wav} pairs) is available,
this test computes SI-SDR for each track and asserts that the running mean
hasn't regressed below the baseline recorded in
``tests/fixtures/separation_baseline.json``.

CI usage (manual):
    1. Set ``RECHORD_MUSDB_ROOT`` to a directory shaped like:
           <root>/<track-name>/mixture.wav
           <root>/<track-name>/vocals.wav
       (MUSDB18-HQ ships exactly this layout.)
    2. Run: pytest tests/test_separation_regression.py -v
    3. To accept new baseline numbers (after an intentional improvement):
           pytest tests/test_separation_regression.py --update-baseline

Skipping behaviour:
    - No ``RECHORD_MUSDB_ROOT`` env var  → test is skipped (passes silently).
    - audio-separator import fails        → test is skipped.
The test does NOT download MUSDB; the dataset is 30+ GB and the user
should already have it locally for serious development.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest


BASELINE_PATH = Path(__file__).parent / "fixtures" / "separation_baseline.json"


def _si_sdr(reference: np.ndarray, estimate: np.ndarray) -> float:
    """Scale-invariant SDR in dB. Handles channel-aligned mono or stereo."""
    if reference.ndim > 1:
        reference = reference.mean(axis=-1)
    if estimate.ndim > 1:
        estimate = estimate.mean(axis=-1)
    n = min(reference.shape[0], estimate.shape[0])
    reference = reference[:n].astype(np.float64)
    estimate = estimate[:n].astype(np.float64)
    reference = reference - reference.mean()
    estimate = estimate - estimate.mean()
    proj = (estimate * reference).sum() / (reference * reference).sum() + 1e-12
    target = proj * reference
    noise = estimate - target
    return float(10.0 * np.log10((target * target).sum() / ((noise * noise).sum() + 1e-12)))


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {"mean_si_sdr_vocal_db": None, "tracks": {}}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _write_baseline(results: dict, mean_sdr: float) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(
            {"mean_si_sdr_vocal_db": mean_sdr, "tracks": results},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


def pytest_addoption(parser):
    parser.addoption("--update-baseline", action="store_true",
                     help="overwrite separation_baseline.json with the new numbers")


def test_vocal_si_sdr_does_not_regress(request):
    root = os.environ.get("RECHORD_MUSDB_ROOT")
    if not root:
        pytest.skip("RECHORD_MUSDB_ROOT not set — skipping regression suite")
    root_path = Path(root)
    if not root_path.exists():
        pytest.skip(f"MUSDB root not found: {root}")

    # Lazy import — separator + soundfile only loaded if the test actually runs.
    try:
        import soundfile as sf
        from backend.app.pipeline.separate import separate_two_stem, MODELS
    except Exception as e:
        pytest.skip(f"audio-separator import failed: {e!r}")

    # Restrict to first 10 tracks for speed; users can crank this later.
    track_dirs = sorted(
        [d for d in root_path.iterdir()
         if d.is_dir() and (d / "mixture.wav").exists() and (d / "vocals.wav").exists()]
    )[:10]
    if not track_dirs:
        pytest.skip(f"no MUSDB-shaped tracks in {root}")

    results: dict[str, float] = {}
    model_filename = MODELS["mdx23c_instvoc_hq"]   # the headline ensemble model

    with tempfile.TemporaryDirectory() as tmp:
        for d in track_dirs:
            mix = d / "mixture.wav"
            ref_voc = d / "vocals.wav"
            try:
                res = separate_two_stem(mix, f"regression_{d.name}", model_filename)
            except Exception as e:
                results[d.name] = None
                print(f"  ! {d.name}: separator failed ({e!r})")
                continue
            est_voc_path = res.stems.get("vocals")
            if not est_voc_path or not Path(est_voc_path).exists():
                results[d.name] = None
                continue
            ref, _ = sf.read(str(ref_voc), dtype="float32", always_2d=True)
            est, _ = sf.read(str(est_voc_path), dtype="float32", always_2d=True)
            sdr = _si_sdr(ref, est)
            results[d.name] = sdr
            print(f"  {d.name}: SI-SDR(vocals) = {sdr:+.2f} dB")

    valid = [v for v in results.values() if v is not None]
    if not valid:
        pytest.skip("no valid SI-SDR measurements obtained")
    mean_sdr = float(np.mean(valid))
    print(f"\n  mean SI-SDR (vocals) = {mean_sdr:+.2f} dB on {len(valid)} tracks")

    if request.config.getoption("--update-baseline"):
        _write_baseline(results, mean_sdr)
        pytest.skip("baseline updated")

    baseline = _load_baseline()
    baseline_mean = baseline.get("mean_si_sdr_vocal_db")
    if baseline_mean is None:
        # No baseline yet — write one and pass.
        _write_baseline(results, mean_sdr)
        return

    # Allow 0.3 dB slack; anything more is a real regression.
    assert mean_sdr >= baseline_mean - 0.3, (
        f"separation quality regression: {mean_sdr:+.2f} dB vs baseline {baseline_mean:+.2f} dB"
    )
