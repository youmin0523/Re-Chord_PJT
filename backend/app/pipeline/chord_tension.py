"""Chroma-based tension/extension detection — covers what CREMA can't.

CREMA's vocabulary tops out at 7ths + 6 + sus (no 9/11/13/add). This
post-processor inspects the beat-synchronous chroma a chord spans and
adds the extensions that are actually ringing:

    add9  — the major 2nd (root+2 semitones) is present, no 7th
    add6  — the major 6th (root+9) is present, no 7th  → "6"
    7     — the minor 7th (root+10) present on a major triad
    maj7  — the major 7th (root+11) present
    sus2  — the 2nd replaces the 3rd
    sus4  — the 4th replaces the 3rd

This is a heuristic energy test, not a trained model. On clean material
it recovers tensions reliably; on dense mixes it is conservative (only
fires when the extension tone clearly outweighs the noise floor) so it
doesn't hallucinate jazz chords onto plain triads. Always editable by
the user in the lead-sheet editor.
"""

from __future__ import annotations

import numpy as np

# semitone offset from root → extension token (degree).
_DEG = {2: "2", 3: "m3", 4: "M3", 5: "4", 9: "6", 10: "b7", 11: "M7", 14 % 12: "9"}

_PC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _root_pc(label_or_root: str) -> int | None:
    s = (label_or_root or "").strip()
    if not s:
        return None
    # label may be "Cmaj7", "F#m", "Bb/D" → take the root token.
    head = s.split("/", 1)[0]
    root = head[:2] if len(head) > 1 and head[1] in "#b" else head[:1]
    flat = {"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10}
    if root in flat:
        return flat[root]
    return _PC.index(root) if root in _PC else None


def detect_tensions(
    root_pc: int,
    is_minor: bool,
    chroma_vec: np.ndarray,
    *,
    present_thresh: float = 0.55,
    absent_thresh: float = 0.35,
) -> dict:
    """Given a chord root + its beat chroma (12,), return which tensions
    are present. ``chroma_vec`` is normalised to its own max internally.

    Returns dict: {"sus": "sus2"|"sus4"|None, "seventh": "7"|"maj7"|None,
                   "add": "add9"|"6"|None, "tokens": [...]}.
    """
    v = np.asarray(chroma_vec, dtype=np.float64)
    if v.size != 12 or v.max() <= 0:
        return {"sus": None, "seventh": None, "add": None, "ext": None,
                "alt": None, "tokens": []}
    v = v / v.max()

    def deg(semi):                       # energy at root+semi
        return float(v[(root_pc + semi) % 12])

    flat9 = deg(1)
    third_maj = deg(4)
    third_min = deg(3)                   # also the #9 pitch-class
    second = deg(2)
    fourth = deg(5)
    sharp11 = deg(6)                     # also the b5 pitch-class
    fifth = deg(7)
    sharp5 = deg(8)                      # also the b13 pitch-class
    sixth = deg(9)
    min7 = deg(10)
    maj7 = deg(11)

    out = {"sus": None, "seventh": None, "add": None, "ext": None,
           "alt": None, "tokens": []}

    # sus: the 3rd is weak but the 2nd or 4th is strong.
    third = third_min if is_minor else third_maj
    if third < absent_thresh:
        if fourth > present_thresh and fourth >= second:
            out["sus"] = "sus4"
        elif second > present_thresh:
            out["sus"] = "sus2"

    # 7th family — present when the 7th tone clearly rings.
    if maj7 > present_thresh and maj7 > min7:
        out["seventh"] = "maj7"
    elif min7 > present_thresh:
        out["seventh"] = "7"

    # ── Upper-structure extensions (9 / 11 / 13) ──────────────────────
    # Only meaningful ON a 7th chord — a 9/11/13 implies the 7th below it.
    # We read the tertian stack above the 7th:
    #   9th  = major 2nd  (root+2)
    #   11th = perfect 4th (root+5)
    #   13th = major 6th  (root+9)
    # Report the HIGHEST present extension (standard naming: a 13 chord
    # subsumes 9 and 11). Slightly higher bar than add-tones so an upper
    # structure must clearly ring over the dense 7th chord, not just leak
    # from a lower tone's harmonics.
    if out["seventh"] is not None:
        ext_thresh = present_thresh + 0.05
        if sixth > ext_thresh:            # 13th
            out["ext"] = "13"
        elif fourth > ext_thresh:         # 11th
            out["ext"] = "11"
        elif second > ext_thresh:         # 9th
            out["ext"] = "9"

    # ── Altered tensions (conservative) ───────────────────────────────
    # Only meaningful once the underlying quality is known:
    #   dominant (M3 + b7)  → b9 / #9 / #11(or b5) / #5(or b13)
    #   major7   (M3 + M7)  → #11 (lydian, e.g. Cmaj7#11)
    # Anchoring on the base quality resolves the enharmonic ambiguity: a
    # STRONG major 3rd means the b3 pitch-class is really #9 (not a minor
    # third), and the natural 5th's presence tells #11 (b5) and #5 (b13)
    # apart. Higher bar than plain extensions so we don't hallucinate
    # alterations from harmonic leakage on a dense chord.
    alt_thresh = present_thresh + 0.05
    is_dominant = (third_maj > present_thresh and min7 > present_thresh
                   and maj7 <= min7)
    is_major7 = (third_maj > present_thresh and maj7 > present_thresh
                 and maj7 > min7)
    alts: list[str] = []
    if is_dominant:
        if flat9 > alt_thresh:
            alts.append("b9")
        if third_min > alt_thresh:                 # #9 (b3 pc, but M3 present)
            alts.append("#9")
        if sharp11 > alt_thresh:
            alts.append("#11" if fifth > absent_thresh else "b5")
        if sharp5 > alt_thresh:
            alts.append("b13" if fifth > present_thresh else "#5")
    elif is_major7:
        if sharp11 > alt_thresh:
            alts.append("#11")
    if alts:
        out["alt"] = alts

    # add tones (only when NO 7th, else it's a 9/13 handled above).
    if out["seventh"] is None and out["sus"] is None:
        if second > present_thresh:
            out["add"] = "add9"
        elif sixth > present_thresh:
            out["add"] = "6"

    return out


def _upgrade_seventh(base: str, ext: str) -> str | None:
    """Replace a 7th label's degree with a higher extension.

    C7→C9/C11/C13, Cmaj7→Cmaj9/Cmaj11/Cmaj13, Dm7→Dm9/Dm11/Dm13.
    Returns None if the base has no plain 7th to upgrade (or already
    carries a 9/11/13/add/sus, or is a dim/aug whose 7th naming we don't
    extend heuristically).
    """
    low = base.lower()
    if any(x in low for x in ("9", "11", "13", "add", "sus", "dim", "aug")):
        return None
    if "maj7" in low:
        return base[: low.index("maj7")] + "maj" + ext
    if "m7" in low and "maj" not in low:        # minor 7th: Dm7, F#m7…
        idx = low.index("m7")
        return base[:idx] + "m" + ext
    if low.endswith("7"):                       # dominant 7th: C7, G7…
        return base[:-1] + ext
    return None


def _compose_altered(base: str, alts: list) -> str | None:
    """Compose an altered label from a 7th base + detected alterations.

    Dominant: C7 → C7b9 / C7#9 / C7#11 / C7#5; two-or-more alterations
    collapse to the conventional shorthand C7alt. Major-7th lydian:
    Cmaj7 → Cmaj7#11. Returns None when the base isn't a plain dominant
    or maj7 we can extend (minor 7ths and already-extended labels are
    left untouched).
    """
    low = base.lower()
    if any(x in low for x in ("9", "11", "13", "add", "sus", "dim", "aug", "alt")):
        return None
    if "maj7" in low:                           # major lydian: #11 only
        return base + "#11" if "#11" in alts else None
    if "m7" in low and "maj" not in low:        # minor 7th → not a dominant
        return None
    if low.endswith("7"):                       # dominant 7th
        relevant = [a for a in alts if a in ("b9", "#9", "#11", "b5", "#5", "b13")]
        if not relevant:
            return None
        return base + relevant[0] if len(relevant) == 1 else base + "alt"
    return None


def enrich_label(base_label: str, root: str, quality: str,
                 tensions: dict) -> str:
    """Compose an enriched chord label from base + detected tensions.

    Keeps the existing label when no tension fires. Never downgrades —
    if the base already carries a 7th/sus (from CREMA), we don't strip it.
    A base that already has a 7th but no upper structure CAN be upgraded
    to 9/11/13 when the chroma shows the extension ringing.
    """
    base = (base_label or "").strip()
    if not base or base.upper() in ("N", "N.C.", "X"):
        return base
    low = base.lower()

    # Already fully enriched (9/11/13/add/sus) → trust it, don't touch.
    if any(t in low for t in ("9", "11", "13", "add", "sus")):
        return base

    # Base already carries a 7th (CREMA gave C7/Cmaj7/Dm7). Altered tones
    # take precedence (C7 → C7b9); otherwise an upper-structure extension
    # upgrades the 7th → 9/11/13. Falls back to keeping the 7th as-is.
    if "7" in low:
        alt = tensions.get("alt")
        if alt:
            altered = _compose_altered(base, alt)
            if altered:
                return altered
        ext = tensions.get("ext")
        if ext:
            upgraded = _upgrade_seventh(base, ext)
            if upgraded:
                return upgraded
        return base

    # Base is a plain triad — apply sus/seventh(+ext)/add.
    is_minor = quality == "min" or (base.endswith("m") and not base.endswith("maj"))
    if tensions.get("sus"):
        # sus replaces the third → e.g. "Csus4".
        return f"{root}{tensions['sus']}"
    if tensions.get("seventh"):
        seventh = tensions["seventh"]
        if seventh == "maj7":
            sev = f"{base}maj7" if not is_minor else f"{base}M7"
        else:
            sev = f"{base}7"
        # Chroma may show a full 9/11/13 over a triad CREMA under-called.
        ext = tensions.get("ext")
        if ext:
            return _upgrade_seventh(sev, ext) or sev
        return sev
    if tensions.get("add"):
        add = tensions["add"]
        return f"{base}{'add9' if add == 'add9' else '6'}"
    return base


def apply_tension_enrichment(
    events: list,
    chroma_by_event: list[np.ndarray],
) -> dict:
    """Enrich a list of ChordEvents in place using per-event chroma.

    ``chroma_by_event`` must align 1:1 with ``events`` (the chroma vector
    each chord spanned). Returns stats {"enriched": k}.
    """
    enriched = 0
    for ev, chroma in zip(events, chroma_by_event):
        if chroma is None:
            continue
        root_pc = _root_pc(getattr(ev, "root", "") or getattr(ev, "label", ""))
        if root_pc is None:
            continue
        is_minor = (getattr(ev, "quality", "") == "min")
        t = detect_tensions(root_pc, is_minor, chroma)
        new_label = enrich_label(getattr(ev, "label", ""),
                                 getattr(ev, "root", ""),
                                 getattr(ev, "quality", ""), t)
        if new_label != getattr(ev, "label", ""):
            try:
                ev.label = new_label
                ev.tension = t
                if getattr(ev, "source", None) is not None:
                    ev.source = "chroma_tension"
                enriched += 1
            except Exception:
                pass
    return {"enriched": enriched}
