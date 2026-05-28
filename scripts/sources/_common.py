"""Shared data structures + helpers for AUX reference source fetchers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# Final category vocabulary — mirrors AUX_CATEGORIES in aux_classifier.py.
CATEGORIES: tuple[str, ...] = (
    "organ", "pad", "synth_lead", "string", "brass", "bell",
    "piano", "epiano", "choir", "guitar_atmos", "fx",
)


@dataclass
class ReferenceItem:
    """One labelled audio clip going into the reference embedding bank."""
    wav_path: Path
    category: str                  # one of CATEGORIES
    source: str                    # e.g. "nsynth", "arachno", "dexed"
    instrument: str = ""           # raw preset / patch name for debug


# General MIDI program number → our category. None means "skip" (drums,
# bass, percussion, ethnic — handled by other stems or out of scope).
GM_PROGRAM_TO_CATEGORY: dict[int, str | None] = {
    # 0–7   Piano
    0: "piano", 1: "piano", 2: "piano", 3: "piano",
    4: "epiano", 5: "epiano", 6: "piano", 7: "epiano",
    # 8–15  Chromatic Percussion
    8: "bell", 9: "bell", 10: "bell", 11: "bell",
    12: "bell", 13: "bell", 14: "bell", 15: "bell",
    # 16–23 Organ
    16: "organ", 17: "organ", 18: "organ", 19: "organ",
    20: "organ", 21: "organ", 22: "organ", 23: "organ",
    # 24–31 Guitar
    24: "guitar_atmos", 25: "guitar_atmos", 26: "guitar_atmos", 27: "guitar_atmos",
    28: "guitar_atmos", 29: "guitar_atmos", 30: "guitar_atmos", 31: "guitar_atmos",
    # 32–39 Bass (skip — goes to bass stem, not AUX)
    32: None, 33: None, 34: None, 35: None,
    36: None, 37: None, 38: None, 39: None,
    # 40–47 Strings
    40: "string", 41: "string", 42: "string", 43: "string",
    44: "string", 45: "string", 46: "string", 47: "bell",       # 47 = timpani → bell-ish
    # 48–55 Ensemble
    48: "string", 49: "string", 50: "pad", 51: "pad",
    52: "choir", 53: "choir", 54: "choir", 55: "brass",
    # 56–63 Brass
    56: "brass", 57: "brass", 58: "brass", 59: "brass",
    60: "brass", 61: "brass", 62: "brass", 63: "brass",
    # 64–71 Reed
    64: "brass", 65: "brass", 66: "brass", 67: "brass",
    68: "brass", 69: "brass", 70: "brass", 71: "brass",
    # 72–79 Pipe
    72: "pad", 73: "pad", 74: "pad", 75: "pad",
    76: "pad", 77: "pad", 78: "pad", 79: "pad",
    # 80–87 Synth Lead
    80: "synth_lead", 81: "synth_lead", 82: "synth_lead", 83: "synth_lead",
    84: "synth_lead", 85: "synth_lead", 86: "synth_lead", 87: "synth_lead",
    # 88–95 Synth Pad
    88: "pad", 89: "pad", 90: "pad", 91: "pad",
    92: "pad", 93: "pad", 94: "pad", 95: "pad",
    # 96–103 Synth Effects
    96: "fx", 97: "fx", 98: "fx", 99: "fx",
    100: "fx", 101: "fx", 102: "fx", 103: "fx",
    # 104–111 Ethnic (skip — out of typical worship AUX scope)
    104: None, 105: None, 106: None, 107: None,
    108: None, 109: None, 110: None, 111: None,
    # 112–119 Percussive (skip — drums)
    112: None, 113: None, 114: None, 115: None,
    116: None, 117: None, 118: None, 119: None,
    # 120–127 Sound Effects
    120: "fx", 121: "fx", 122: "fx", 123: "fx",
    124: "fx", 125: "fx", 126: "fx", 127: "fx",
}


def gm_program_to_category(program: int) -> str | None:
    """Map a GM patch number (0..127) to our AUX category, or None to skip."""
    return GM_PROGRAM_TO_CATEGORY.get(int(program))


def iter_existing_items(out_dir: Path, source: str) -> Iterable[ReferenceItem]:
    """Yield existing items from a fetcher's cache dir based on a manifest."""
    manifest = out_dir / "manifest.json"
    if not manifest.exists():
        return
    import json
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for row in data.get("items", []):
        wav = Path(row["wav_path"])
        if not wav.exists():
            continue
        yield ReferenceItem(
            wav_path=wav,
            category=row["category"],
            source=source,
            instrument=row.get("instrument", ""),
        )


def save_manifest(out_dir: Path, items: list[ReferenceItem]) -> Path:
    """Persist a fetcher's items list for incremental rebuilds."""
    import json
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.json"
    manifest.write_text(
        json.dumps({
            "version": 1,
            "items": [
                {
                    "wav_path": str(it.wav_path),
                    "category": it.category,
                    "source": it.source,
                    "instrument": it.instrument,
                }
                for it in items
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
