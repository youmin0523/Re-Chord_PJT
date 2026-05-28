"""Fetch + render the Arachno SoundFont (Maxime Abbey, CC BY-SA 3.0).

128 GM instruments, ~150 MB. The de-facto highest-quality fully open GM SF.
Once downloaded we delegate to ``render_sf2`` to produce one wav per preset.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from ._common import ReferenceItem, iter_existing_items
from .render_sf2 import render_sf2


# Stable mirror on archive.org. The official site rotates URLs annually.
# License: Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0).
ARACHNO_URL = (
    "https://archive.org/download/arachno-sound-font-version-1.0/"
    "Arachno%20SoundFont%20-%20Version%201.0.sf2"
)


def fetch(out_dir: Path) -> list[ReferenceItem]:
    """Download Arachno (cached) then render every GM preset."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sf2 = out_dir / "Arachno_v1.0.sf2"

    # Resume from cache when the manifest is already complete.
    if (out_dir / "wavs" / "manifest.json").exists() and sf2.exists():
        cached = list(iter_existing_items(out_dir / "wavs", source="arachno"))
        if cached:
            return cached

    if not sf2.exists() or sf2.stat().st_size < 50_000_000:
        print(f"[arachno] downloading {ARACHNO_URL} → {sf2}")
        urllib.request.urlretrieve(ARACHNO_URL, str(sf2))

    print(f"[arachno] rendering presets → {out_dir / 'wavs'}")
    items = render_sf2(sf2, out_dir / "wavs", source_tag="arachno")
    print(f"[arachno] {len(items)} presets rendered")
    return items
