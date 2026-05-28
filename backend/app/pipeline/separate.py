"""Vocal/instrumental separation via the audio-separator library.

D3 scope: single-model separation with MDX23C-InstVoc HQ.
D4 will add Roformer + htdemucs_ft for ensemble.
"""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from ..core.paths import ensure_dir


# Canonical model filenames (from audio-separator's model registry).
MODELS = {
    "mdx23c_instvoc_hq": "MDX23C-8KFFT-InstVoc_HQ.ckpt",
    "mdx23c_instvoc_hq_2": "MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
    "bs_roformer_1297": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    "bs_roformer_1296": "model_bs_roformer_ep_368_sdr_12.9628.ckpt",
    "htdemucs_ft": "htdemucs_ft.yaml",
    "htdemucs_6s": "htdemucs_6s.yaml",
    # SOTA single-model (2024). Lowest vocal bleed of any 2-stem model.
    "melband_kim_inst_v2": "melband_roformer_inst_v2.ckpt",
    "melband_kim_inst_v1": "melband_roformer_inst_v1.ckpt",
    # Karaoke / vocal-residual cleanup post-processor. Run on the
    # already-separated instrumental to scrub remaining vocal leakage.
    "mel_karaoke_aufr33": "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
    # SOTA mirrors from HuggingFace Hub. NOT available until you run
    # ``python scripts/fetch_sota_separator.py`` — that script downloads
    # the weights and writes a registry JSON which we merge below at
    # import time. The aliases here MUST match SOURCES keys in the script.
    "melband_roformer_kim":               "MelBandRoformer.ckpt",
    "bs_roformer_hyperace_v2_inst":       "bs_roformer_inst_hyperacev2.ckpt",
    "bs_roformer_hyperace_v2_voc":        "bs_roformer_voc_hyperacev2.ckpt",
    "bs_roformer_large_inst_v2":          "bs_large_v2_inst.ckpt",
    "bs_roformer_anvuew_ft1":             "bs_roformer_ft1_anvuew_sdr_12.55.ckpt",
    "melband_roformer_4stem_ft_large":    "MelBandRoformer4StemFTLarge.ckpt",
    "mdx23c_instvoc_hq_2_live":           "MDX23C-8KFFT-InstVoc_HQ_2.ckpt",

    # SOTA models registered directly in audio-separator's own download
    # list (see ``audio_separator/models.json::roformer_download_list``).
    # Selecting these aliases triggers audio-separator's auto-download
    # path; no manual ckpt prep required. Recommended for the cleanest
    # vocal/instrumental split as of 2024-2025.
    "melband_kim_ft2":                    "mel_band_roformer_kim_ft2_unwa.ckpt",
    "melband_kim_ft2_bleedless":          "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt",
    "melband_kim_inst_v1e":               "melband_roformer_inst_v1e.ckpt",
    "melband_kim_syhft_v3":               "MelBandRoformerSYHFTV3Epsilon.ckpt",
    "melband_kim_big_beta6":              "melband_roformer_big_beta6.ckpt",
    "melband_bleed_suppressor":           "mel_band_roformer_bleed_suppressor_v1.ckpt",
    "melband_inst_bleedless_v2":          "mel_band_roformer_instrumental_bleedless_v2_gabox.ckpt",
    "vocals_mel_band_kim_original":       "vocals_mel_band_roformer.ckpt",
}


def _merge_sota_registry() -> None:
    """At import time, merge the SOTA-fetcher registry into MODELS so the
    aliases above resolve to absolute paths when the weights are present.

    Silently no-op if the registry doesn't exist yet."""
    here = Path(__file__).resolve().parents[3]
    registry_path = (
        here / "data" / "models" / "audio_separator" / "rechord_sota_registry.json"
    )
    if not registry_path.exists():
        return
    try:
        import json as _json
        reg = _json.loads(registry_path.read_text(encoding="utf-8"))
        for alias, info in reg.items():
            path = info.get("path")
            if path and Path(path).exists():
                MODELS[alias] = path
    except Exception:
        # Best-effort; never break import.
        pass


_merge_sota_registry()


@dataclass
class SeparateResult:
    job_id: str
    model: str
    stems: dict[str, Path] = field(default_factory=dict)
    elapsed_sec: float = 0.0
    input_duration_sec: float = 0.0

    @property
    def realtime_factor(self) -> float:
        if self.elapsed_sec <= 0 or self.input_duration_sec <= 0:
            return 0.0
        return self.input_duration_sec / self.elapsed_sec


def _release_cuda() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()


def _probe_duration(path: Path) -> float:
    import subprocess
    import shutil
    exe = shutil.which("ffprobe")
    if not exe:
        return 0.0
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _categorize_outputs(output_files: list[str], out_dir: Path) -> dict[str, Path]:
    """Map audio-separator output filenames into {stem_name: path}."""
    stems: dict[str, Path] = {}
    for f in output_files:
        p = Path(f)
        if not p.is_absolute():
            p = out_dir / p
        name = p.name.lower()
        if "vocal" in name:
            stems["vocals"] = p
        elif "instrumental" in name or "no_vocals" in name or "(inst)" in name:
            stems["instrumental"] = p
        elif "drums" in name:
            stems["drums"] = p
        elif "bass" in name:
            stems["bass"] = p
        elif "guitar" in name:
            stems["guitar"] = p
        elif "piano" in name:
            stems["piano"] = p
        elif "other" in name:
            stems["other"] = p
        else:
            stems[p.stem] = p
    return stems


def separate_two_stem(
    master: Path,
    job_id: str,
    model_filename: str = MODELS["mdx23c_instvoc_hq"],
) -> SeparateResult:
    """Run a single 2-stem (vocals/instrumental) model on the master wav."""
    from audio_separator.separator import Separator

    out_dir = settings.stems_dir / job_id / model_filename.rsplit(".", 1)[0]
    ensure_dir(out_dir)

    duration = _probe_duration(master)

    sep = Separator(
        model_file_dir=str(settings.models_dir),
        output_dir=str(out_dir),
        output_format="WAV",
        log_level=20,
    )

    t0 = time.perf_counter()
    sep.load_model(model_filename=model_filename)
    output_files = sep.separate(str(master))
    elapsed = time.perf_counter() - t0

    stems = _categorize_outputs(output_files, out_dir)

    del sep
    _release_cuda()

    # For 4-stem (htdemucs_ft) and 6-stem (htdemucs_6s) models, synthesize an
    # "instrumental" track by summing all non-vocal stems. This makes the result
    # interchangeable with 2-stem models in downstream ensemble combiners.
    if "instrumental" not in stems and "vocals" in stems:
        non_vocal = [p for k, p in stems.items()
                     if k not in ("vocals", "instrumental")]
        if non_vocal:
            synth_path = out_dir / "_synth_instrumental.wav"
            _sum_stems_to_wav(non_vocal, synth_path)
            stems["instrumental"] = synth_path

    return SeparateResult(
        job_id=job_id,
        model=model_filename,
        stems=stems,
        elapsed_sec=elapsed,
        input_duration_sec=duration,
    )


def _sum_stems_to_wav(sources: list[Path], out_path: Path) -> None:
    """Sum multiple stem files (same sr/shape) into one wav. Used to build
    htdemucs's missing 'instrumental' track from drums+bass+other(+guitar+piano)."""
    import numpy as np
    import soundfile as sf

    acc: np.ndarray | None = None
    sr_ref: int | None = None
    min_len: int | None = None
    arrays: list[np.ndarray] = []
    for p in sources:
        data, sr = sf.read(str(p), dtype="float32", always_2d=True)
        if sr_ref is None:
            sr_ref = sr
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        arrays.append(data)
        min_len = data.shape[0] if min_len is None else min(min_len, data.shape[0])

    assert sr_ref is not None and min_len is not None
    for a in arrays:
        seg = a[:min_len]
        acc = seg if acc is None else acc + seg
    assert acc is not None
    # Soft clip to [-1, 1] (sum of stems can exceed range in loud passages).
    np.clip(acc, -1.0, 1.0, out=acc)
    sf.write(str(out_path), acc, sr_ref, subtype="FLOAT")


def separate_multi_model(
    master: Path,
    job_id: str,
    model_aliases: list[str],
) -> list[SeparateResult]:
    """Sequentially run multiple 2-stem models, releasing VRAM between each.

    Returns one SeparateResult per model in the same order.
    """
    results: list[SeparateResult] = []
    for alias in model_aliases:
        filename = MODELS.get(alias, alias)
        r = separate_two_stem(master, job_id, model_filename=filename)
        results.append(r)
    return results
