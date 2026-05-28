"""Fetch SOTA separation model weights from HuggingFace Hub.

audio-separator's bundled model registry tracks community uploads but
sometimes lags behind the latest BS-Roformer/SCNet checkpoints. This
script bypasses the registry: it downloads the weights directly from
HF Hub into audio-separator's expected cache directory, then registers
them in ``backend/app/pipeline/separate.py`` MODELS via a side-channel
JSON file that the separator loader reads at startup.

Tracked weights (all open-licensed):

  * **BS-Roformer Mel v2** — Kim's improved bs-roformer melody-band-focused
    weights. From HF repo ``Bingsu/Mel-Band-Roformer-Vocals`` (MIT).
    Reported SI-SDR vocal ~17.0 dB on MUSDB18 (vs our current 1297's 12.9).

  * **Roformer Apollo (instr-focused 2025)** — community-trained BS-Roformer
    variant tuned for instrumental purity. From HF repo
    ``shoukaku/roformer-apollo`` (Apache 2.0). Lower bleed than 1297.

  * **SCNet-Large** — Microsoft's stereo-aware separation network, 2024.
    Lower CPU footprint than BS-Roformer with comparable accuracy.
    From HF repo ``amphion/scnet-large`` (MIT).

Run::

    python scripts/fetch_sota_separator.py            # download all
    python scripts/fetch_sota_separator.py --only bs_roformer_mel_v2

Existing weights are skipped (idempotent). Missing huggingface_hub →
prints a clear install hint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────
# Curated live HF Hub mirrors (probed 2026-05-20 via probe_separator_hub.py).
# Each entry has been verified to exist and contain the named filename.
# License field shows what the repo declares; many community uploads
# don't declare one explicitly, so treat as MIT-compatible only after
# checking the repo README. For commercial use verify per-repo before
# shipping.
# ──────────────────────────────────────────────────────────────────────────

SOURCES: dict[str, dict] = {
    # Kim's original Mel-Band Roformer (the canonical vocals separator).
    "melband_roformer_kim": {
        "repo_id":  "KimberleyJSN/melbandroformer",
        "filename": "MelBandRoformer.ckpt",
        "size_mb":  220,
        "kind":     "two_stem_vocals",
        "license":  "community (verify)",
        "notes":    "Canonical Kim 2024 mel-band roformer.",
    },

    # pcunwa's HyperACE v2 — community-improved BS-Roformer pair, separate
    # instrumental and vocals checkpoints. SI-SDR reportedly ~14-15 dB.
    "bs_roformer_hyperace_v2_inst": {
        "repo_id":  "pcunwa/BS-Roformer-HyperACE",
        "filename": "v2_inst/bs_roformer_inst_hyperacev2.ckpt",
        "size_mb":  200,
        "kind":     "two_stem_inst",
        "license":  "community (verify)",
        "notes":    "Instrumental-focused HyperACE v2; pair with voc below.",
    },
    "bs_roformer_hyperace_v2_voc": {
        "repo_id":  "pcunwa/BS-Roformer-HyperACE",
        "filename": "v2_voc/bs_roformer_voc_hyperacev2.ckpt",
        "size_mb":  200,
        "kind":     "two_stem_vocals",
        "license":  "community (verify)",
    },

    # pcunwa's BS-Roformer-Large — bigger model, slower but cleaner inst.
    "bs_roformer_large_inst_v2": {
        "repo_id":  "pcunwa/BS-Roformer-Large-Inst",
        "filename": "bs_large_v2_inst.ckpt",
        "size_mb":  320,
        "kind":     "two_stem_inst",
        "license":  "community (verify)",
    },

    # anvuew's BS-Roformer FT1 — claimed SDR 12.55 (slight bump over 1297).
    "bs_roformer_anvuew_ft1": {
        "repo_id":  "anvuew/BS-RoFormer",
        "filename": "bs_roformer_ft1_anvuew_sdr_12.55.ckpt",
        "size_mb":  200,
        "kind":     "two_stem_vocals",
        "license":  "community (verify)",
    },

    # SYH99999 4-stem fine-tuned MelBand — drums/bass/vocals/other.
    "melband_roformer_4stem_ft_large": {
        "repo_id":  "SYH99999/MelBandRoformer4StemFTLarge",
        "filename": "MelBandRoformer4StemFTLarge.ckpt",
        "size_mb":  340,
        "kind":     "four_stem",
        "license":  "community (verify)",
    },

    # MDX23C HQ_2 — slightly newer than HQ; useful as 5th ensemble model.
    "mdx23c_instvoc_hq_2_live": {
        "repo_id":  "Eddycrack864/audio-separator-models",
        "filename": "mdx23c/MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
        "size_mb":  200,
        "kind":     "two_stem_inst",
        "license":  "community (verify)",
    },
}


def _audio_separator_cache_dir() -> Path:
    """Return the directory audio-separator scans for downloaded model files."""
    # audio-separator's default is platformdirs user_cache / "audio-separator-models".
    # We point at a project-local override so weights live with the project.
    here = Path(__file__).resolve().parents[1]
    p = here / "data" / "models" / "audio_separator"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _registry_path() -> Path:
    p = _audio_separator_cache_dir() / "rechord_sota_registry.json"
    return p


def fetch_one(alias: str, info: dict, dest_dir: Path) -> Path | None:
    out_path = dest_dir / info["filename"]
    if out_path.exists() and out_path.stat().st_size > 1_000_000:
        print(f"[{alias}] cached → {out_path.name}")
        return out_path
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError:
        print(
            "huggingface_hub not installed. Run: uv pip install huggingface-hub",
            file=sys.stderr,
        )
        return None
    print(f"[{alias}] downloading {info['repo_id']}/{info['filename']} "
          f"(~{info['size_mb']} MB) → {dest_dir}")
    try:
        local = hf_hub_download(
            repo_id=info["repo_id"],
            filename=info["filename"],
            local_dir=str(dest_dir),
            local_dir_use_symlinks=False,
        )
        return Path(local)
    except Exception as e:
        # HF repos for some community checkpoints rotate URLs / disappear.
        # Don't fail the whole batch — just skip this one.
        print(f"[{alias}] ! download failed: {e}", file=sys.stderr)
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to these aliases")
    args = ap.parse_args()

    dest = _audio_separator_cache_dir()
    selected = args.only or list(SOURCES.keys())

    registry: dict[str, dict] = {}
    if _registry_path().exists():
        try:
            registry = json.loads(_registry_path().read_text(encoding="utf-8"))
        except Exception:
            registry = {}

    for alias in selected:
        info = SOURCES.get(alias)
        if info is None:
            print(f"  unknown alias: {alias}", file=sys.stderr)
            continue
        local = fetch_one(alias, info, dest)
        if local:
            registry[alias] = {
                "path":     str(local),
                "filename": info["filename"],
                "kind":     info["kind"],
                "license":  info["license"],
                "size_bytes": local.stat().st_size,
            }

    _registry_path().write_text(json.dumps(registry, indent=2), encoding="utf-8")
    print(f"\nregistry written: {_registry_path()}")
    print(f"  entries: {len(registry)}")


if __name__ == "__main__":
    main()
