"""Objective quality metrics for separation results.

We can't ship MUSDB18 ground truth (license + size), but we *can* run a
null-test on every job: a perfect separation would satisfy
    original ≈ instrumental + vocals
so the residual ``r = original - (inst + voc)`` tells us how much energy
the models lost or hallucinated.

Metrics produced per job:
  null_rms_dbfs   - residual RMS in dBFS (lower magnitude = better)
                    target: < -30 dB (good), < -40 dB (excellent)
  reconstruction_corr - Pearson correlation of (inst+voc) vs original
                        target: > 0.95 (good), > 0.99 (excellent)
  vocal_leak_dbfs - inst track's energy in the typical vocal band
                    (300-3400 Hz) vs out-of-vocal-band energy.
                    Lower = less residual singing in the MR.
  voc_inst_xcorr - cross-correlation between final vocal stem and
                   final instrumental at zero lag. Should be near 0;
                   high value means stems still bleed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class QualityReport:
    null_rms_dbfs: float
    reconstruction_corr: float
    vocal_leak_dbfs: float | None
    voc_inst_xcorr: float
    sample_rate: int
    duration_sec: float
    notes: list[str]

    def grade(self) -> str:
        """Single-letter shorthand grade for UI use."""
        score = 0
        if self.null_rms_dbfs <= -40: score += 2
        elif self.null_rms_dbfs <= -30: score += 1
        if self.reconstruction_corr >= 0.99: score += 2
        elif self.reconstruction_corr >= 0.95: score += 1
        if self.vocal_leak_dbfs is not None and self.vocal_leak_dbfs <= -15:
            score += 1
        if abs(self.voc_inst_xcorr) < 0.05: score += 1
        return ["E", "D", "C", "B", "B+", "A", "A+"][min(score, 6)]


def _load_stereo(path: Path, target_sr: int) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
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
    return data, target_sr


def _to_mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def _rms_dbfs(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(x ** 2) + 1e-20))
    return 20.0 * np.log10(max(rms, 1e-10))


def _band_energy_ratio_dbfs(
    x_mono: np.ndarray, sr: int, lo_hz: float, hi_hz: float,
) -> float:
    """In-band RMS minus out-of-band RMS, in dB. Positive ⇒ more energy in band."""
    n = len(x_mono)
    if n < 16:
        return 0.0
    spec = np.fft.rfft(x_mono)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    in_mask = (freqs >= lo_hz) & (freqs <= hi_hz)
    in_energy = float(np.sum(np.abs(spec[in_mask]) ** 2)) / max(in_mask.sum(), 1)
    out_energy = float(np.sum(np.abs(spec[~in_mask]) ** 2)) / max((~in_mask).sum(), 1)
    return 10.0 * np.log10((in_energy + 1e-20) / (out_energy + 1e-20))


def compute_quality(
    original_master: Path,
    instrumental: Path,
    vocals: Path,
    target_sr: int = 48000,
    sample_seconds: float = 90.0,
) -> QualityReport:
    """Compute the null-test report. Caps analysis to ~sample_seconds
    so long songs don't blow memory."""
    orig, _ = _load_stereo(original_master, target_sr)
    inst, _ = _load_stereo(instrumental, target_sr)
    voc, _ = _load_stereo(vocals, target_sr)

    n = min(orig.shape[0], inst.shape[0], voc.shape[0])
    max_samples = int(sample_seconds * target_sr)
    if max_samples > 0 and n > max_samples:
        # Pick a chunk from the middle, where music is usually densest.
        start = (n - max_samples) // 2
        orig = orig[start:start + max_samples]
        inst = inst[start:start + max_samples]
        voc = voc[start:start + max_samples]
        n = max_samples
    else:
        orig = orig[:n]; inst = inst[:n]; voc = voc[:n]

    reconst = inst + voc
    residual = orig - reconst

    null_rms = _rms_dbfs(residual)

    # Pearson correlation of (inst + voc) vs original (mono).
    orig_m = _to_mono(orig)
    rec_m = _to_mono(reconst)
    om = orig_m - orig_m.mean()
    rm = rec_m - rec_m.mean()
    denom = float(np.sqrt(np.sum(om ** 2) * np.sum(rm ** 2)) + 1e-20)
    recon_corr = float(np.sum(om * rm) / denom)

    # Vocal-leak proxy: how strong the instrumental is inside the human
    # vocal band, relative to out-of-band. If the model removed vocals well,
    # the instrumental shouldn't dominate the 300-3400 Hz band over the rest.
    inst_m = _to_mono(inst)
    try:
        leak = _band_energy_ratio_dbfs(inst_m, target_sr, 300.0, 3400.0)
    except Exception:
        leak = None

    # Zero-lag normalized cross-correlation between final stems (mono).
    voc_m = _to_mono(voc)
    a = inst_m - inst_m.mean()
    b = voc_m - voc_m.mean()
    denom2 = float(np.sqrt(np.sum(a ** 2) * np.sum(b ** 2)) + 1e-20)
    xcorr = float(np.sum(a * b) / denom2)

    notes: list[str] = []
    if null_rms > -25:
        notes.append("residual loud: 모델이 일부 정보를 놓치거나 곡 dynamic이 큼")
    if recon_corr < 0.9:
        notes.append("inst + voc ≠ original이 큼: 위상 정렬 / 모델 경계 문제 가능")
    if leak is not None and leak > -5:
        notes.append("instrumental의 보컬 대역(300-3400Hz) 비중이 큼: 보컬 잔재 또는 보컬 대역 악기")
    if abs(xcorr) > 0.15:
        notes.append("두 stem 간 잔류 상관 존재: 잔재/누설 가능성")

    return QualityReport(
        null_rms_dbfs=null_rms,
        reconstruction_corr=recon_corr,
        vocal_leak_dbfs=leak,
        voc_inst_xcorr=xcorr,
        sample_rate=target_sr,
        duration_sec=n / target_sr,
        notes=notes,
    )


def write_quality_json(report: QualityReport, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    d = asdict(report)
    d["grade"] = report.grade()
    out_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def suggest_diff_mask_strength(
    instrumental: Path,
    vocals: Path,
    target_sr: int = 48000,
    sample_seconds: float = 30.0,
    *,
    floor: float = 0.35,
    ceil: float = 0.75,
) -> dict:
    """Recommend a diff-mask strength from the measured vocal leakage.

    Runs a quick cross-correlation between the instrumental and the vocal
    stem inside the vocal band (300-3400 Hz). The more the instrumental
    still tracks the vocal there, the harder we should mask:

        xcorr < 0.10  → light masking  (floor)
        xcorr > 0.30  → heavy masking  (ceil)
        in between     → linear interpolation

    Returns ``{"strength": float, "measured_xcorr": float, "reason": str}``.
    A song with already-clean separation gets a gentle mask (preserves
    air); a song with heavy bleed gets an aggressive one.
    """
    try:
        inst, _ = _load_stereo(instrumental, target_sr)
        voc, _ = _load_stereo(vocals, target_sr)
    except Exception:
        return {"strength": (floor + ceil) / 2, "measured_xcorr": None,
                "reason": "load failed — used midpoint"}

    n = min(inst.shape[0], voc.shape[0], int(sample_seconds * target_sr))
    if n < target_sr:
        return {"strength": (floor + ceil) / 2, "measured_xcorr": None,
                "reason": "too short — used midpoint"}
    start = max(0, (min(inst.shape[0], voc.shape[0]) - n) // 2)
    inst_m = _to_mono(inst[start:start + n])
    voc_m = _to_mono(voc[start:start + n])

    # Band-limit both to the vocal band before correlating.
    def _bandlimit(x):
        spec = np.fft.rfft(x)
        freqs = np.fft.rfftfreq(len(x), 1.0 / target_sr)
        mask = (freqs >= 300.0) & (freqs <= 3400.0)
        spec[~mask] = 0
        return np.fft.irfft(spec, n=len(x))

    try:
        a = _bandlimit(inst_m); b = _bandlimit(voc_m)
        a = a - a.mean(); b = b - b.mean()
        denom = float(np.sqrt(np.sum(a ** 2) * np.sum(b ** 2)) + 1e-20)
        xcorr = abs(float(np.sum(a * b) / denom))
    except Exception:
        return {"strength": (floor + ceil) / 2, "measured_xcorr": None,
                "reason": "correlation failed — used midpoint"}

    # Map xcorr ∈ [0.10, 0.30] → strength ∈ [floor, ceil].
    lo_x, hi_x = 0.10, 0.30
    if xcorr <= lo_x:
        strength = floor
    elif xcorr >= hi_x:
        strength = ceil
    else:
        frac = (xcorr - lo_x) / (hi_x - lo_x)
        strength = floor + frac * (ceil - floor)
    return {
        "strength": round(float(strength), 3),
        "measured_xcorr": round(xcorr, 3),
        "reason": (f"vocal-band xcorr {xcorr:.3f} → "
                   f"{'heavy' if strength > 0.6 else 'moderate' if strength > 0.45 else 'light'} mask"),
    }


def measure_stem_overlap(
    stems: dict[str, Path],
    target_sr: int = 48000,
    sample_seconds: float = 60.0,
) -> dict:
    """Detect cross-bleed between separated stems (Stems mode QA).

    htdemucs_6s gives vocals/drums/bass/piano/guitar/other but the
    boundaries aren't perfect — bass guitar leaks into ``other``, rhythm
    guitar leaks into ``piano``, etc. We quantify this with the zero-lag
    normalised cross-correlation between every pair of stems on a mid-song
    window. A clean separation has near-zero pairwise correlation; a high
    value flags audible bleed the user should know about before they
    transcribe that stem.

    Returns:
        {
          "pairs": [{"a": "bass", "b": "other", "xcorr": 0.31,
                     "bleed": "moderate"}, ...],
          "worst_pair": {...},
          "max_xcorr": 0.31,
          "flagged": ["bass↔other"],          # pairs above the 0.25 threshold
        }
    """
    loaded: dict[str, np.ndarray] = {}
    for name, path in stems.items():
        try:
            p = Path(path)
            if not p.exists():
                continue
            arr, _ = _load_stereo(p, target_sr)
            mono = _to_mono(arr)
            n = min(len(mono), int(sample_seconds * target_sr))
            if n < target_sr:        # < 1 s — skip, not enough signal
                continue
            start = max(0, (len(mono) - n) // 2)
            loaded[name] = mono[start:start + n]
        except Exception:
            continue

    names = sorted(loaded.keys())
    pairs: list[dict] = []
    max_xcorr = 0.0
    worst = None
    flagged: list[str] = []

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = loaded[names[i]], loaded[names[j]]
            m = min(len(a), len(b))
            if m < target_sr:
                continue
            x = a[:m] - a[:m].mean()
            y = b[:m] - b[:m].mean()
            denom = float(np.sqrt(np.sum(x ** 2) * np.sum(y ** 2)) + 1e-20)
            xcorr = abs(float(np.sum(x * y) / denom))
            bleed = ("clean" if xcorr < 0.15
                     else "mild" if xcorr < 0.25
                     else "moderate" if xcorr < 0.4
                     else "heavy")
            pair = {"a": names[i], "b": names[j],
                    "xcorr": round(xcorr, 3), "bleed": bleed}
            pairs.append(pair)
            if xcorr >= 0.25:
                flagged.append(f"{names[i]}↔{names[j]}")
            if xcorr > max_xcorr:
                max_xcorr = xcorr
                worst = pair

    return {
        "pairs": pairs,
        "worst_pair": worst,
        "max_xcorr": round(max_xcorr, 3),
        "flagged": flagged,
    }
