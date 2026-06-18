"""Fetch the NSynth ``valid`` split (Google Magenta, CC BY 4.0).

The full NSynth dataset is 30+ GB; the ``valid`` subset is ~3 GB and gives us
12,678 4-second 16 kHz mono samples across the 11 NSynth instrument
families — more than enough for reference-DB diversity.

Instrument families NSynth provides (mapped to our AUX categories):
    bass        → skip (covered by bass stem)
    brass       → brass
    flute       → pad
    guitar      → guitar_atmos
    keyboard    → piano  (the meta.json "instrument_source" disambiguates EP)
    mallet      → bell
    organ       → organ
    reed        → brass
    string      → string
    synth_lead  → synth_lead
    vocal       → choir
"""

from __future__ import annotations

import json
import tarfile
import urllib.request
from pathlib import Path

from ._common import ReferenceItem, iter_existing_items, save_manifest


NSYNTH_VALID_URL = (
    "http://download.magenta.tensorflow.org/datasets/nsynth/nsynth-valid.jsonwav.tar.gz"
)

FAMILY_TO_CATEGORY: dict[str, str | None] = {
    "bass": None,
    "brass": "brass",
    "flute": "pad",
    "guitar": "guitar_atmos",
    "keyboard": "piano",       # refined per-source below (electronic → epiano)
    "mallet": "bell",
    "organ": "organ",
    "reed": "brass",
    "string": "string",
    "synth_lead": "synth_lead",
    "vocal": "choir",
}


def _category_for(ex: dict) -> str | None:
    """Map one NSynth example → AUX category.

    The keyboard family is split by ``instrument_source``: the 1,751
    *electronic* keyboards in the valid split are electric pianos
    (Rhodes/Wurli/EP voices) and belong in ``epiano`` — lumping them into
    ``piano`` (the old behaviour) left ``epiano`` with only 3 Arachno
    presets (0% accuracy). Acoustic + synthetic keyboards stay ``piano``.
    """
    fam = ex.get("instrument_family_str", "")
    if fam == "keyboard":
        return "epiano" if ex.get("instrument_source_str", "") == "electronic" else "piano"
    return FAMILY_TO_CATEGORY.get(fam)


def fetch(out_dir: Path, *, max_per_family: int = 600) -> list[ReferenceItem]:
    """Download NSynth ``valid`` split, subset to ``max_per_family`` items.

    600 × 11 families = ~6,600 references is a good balance of coverage
    vs build time. Pass ``max_per_family=0`` to keep everything.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    extract_root = out_dir / "nsynth-valid"

    if (out_dir / "manifest.json").exists():
        cached = list(iter_existing_items(out_dir, source="nsynth"))
        if cached:
            return cached

    tar_path = out_dir / "nsynth-valid.jsonwav.tar.gz"
    if not extract_root.exists():
        if not tar_path.exists() or tar_path.stat().st_size < 1_000_000_000:
            print(f"[nsynth] downloading {NSYNTH_VALID_URL} → {tar_path} (~3GB)")
            urllib.request.urlretrieve(NSYNTH_VALID_URL, str(tar_path))
        print(f"[nsynth] extracting → {extract_root}")
        with tarfile.open(tar_path, "r:gz") as tf:
            tf.extractall(out_dir)

    examples = json.loads(
        (extract_root / "examples.json").read_text(encoding="utf-8")
    )
    audio_dir = extract_root / "audio"

    # Reservoir-style cap: keep the first N per *category* in dict-iteration
    # order (keyboard is split into piano/epiano, so cap per category not per
    # family — otherwise epiano would re-merge with piano under one cap).
    by_cat: dict[str, list[str]] = {}
    for name, ex in examples.items():
        cat = _category_for(ex)
        if cat is None:
            continue
        by_cat.setdefault(cat, []).append(name)

    items: list[ReferenceItem] = []
    for cat, names in by_cat.items():
        keep = names if max_per_family <= 0 else names[:max_per_family]
        for n in keep:
            wav = audio_dir / f"{n}.wav"
            if not wav.exists():
                continue
            # NSynth audio is already a clean 4-second 16 kHz mono note;
            # the build script will resample to 48 kHz on embed.
            items.append(ReferenceItem(
                wav_path=wav, category=cat, source="nsynth",
                instrument=examples[n].get("instrument_str", n),
            ))

    save_manifest(out_dir, items)
    print(f"[nsynth] kept {len(items)} samples across {len(by_cat)} categories: "
          f"{ {c: len(v) for c, v in by_cat.items()} }")
    return items
