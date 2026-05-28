"""Optional CREMA backend for chord recognition.

CREMA (Brian McFee, Apache-2.0) is a deep-net chord recognizer. Its
170-class vocabulary = 12 roots × 14 qualities + N/X. The 14 qualities
(verified 2026-05-27 from the model's chord_tag encoder):

    maj  min  aug  dim          (triads)
    7  maj7  min7                (dominant + major/minor 7ths)
    dim7  hdim7  minmaj7         (diminished7, half-dim m7b5, minMaj7)
    maj6  min6                   (6th chords ≈ add6)
    sus2  sus4                   (suspensions)

IMPORTANT LIMITATION: CREMA tops out at 7th-level harmony. It CANNOT
detect 9/11/13 extensions, add9/add13, or altered dominants (7#9, 7b9,
7#5) — those are not classes in its vocabulary and collapse to the
nearest base (triad or 7th). Detecting those needs a larger-vocab model
or manual editing in the AuxCuesEditor / lead-sheet editor. Slash bass
(C/E) IS preserved from CREMA's chord_struct output.

When ``crema`` is installed this module returns per-frame chord labels
the ensemble merges (extension-preserving) with the librosa template
detector. Missing → ImportError → caller falls back to triad-only.

Install: ``uv pip install crema`` (~250 MB tensorflow + ~50 MB weights).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .chords import ChordEvent


_SKLEARN_PATCHED = False


def _patch_sklearn_check_is_fitted() -> None:
    """Revive CREMA under scikit-learn >= 1.6.

    CREMA/pumpp were built for sklearn < 1.6. In 1.6+, ``check_is_fitted``
    routes through ``get_tags`` which needs ``__sklearn_tags__`` — an
    attribute pumpp's vendored LabelEncoder lacks, so every CREMA
    ``transcribe`` raised ``AttributeError`` and was silently swallowed
    by the caller's try/except. Net effect: CREMA's 170-class vocabulary
    (7th/sus/dim/6) never reached users; only the 24-triad template ran.

    Rather than downgrade scikit-learn (7 packages depend on 1.8 here:
    librosa, basic-pitch, crepe, laion-clap, hmmlearn, ...), we wrap
    ``check_is_fitted`` so that when the new get_tags path fails, it falls
    back to the classic attribute-presence check (which is the correct,
    older behaviour: if ``classes_`` exists, the encoder IS fitted).
    Surgical, reversible, no dependency change.
    """
    global _SKLEARN_PATCHED
    if _SKLEARN_PATCHED:
        return
    try:
        import sklearn.utils.validation as _v
        _orig = _v.check_is_fitted

        def _safe_check_is_fitted(estimator, attributes=None, *args, **kwargs):
            try:
                return _orig(estimator, attributes, *args, **kwargs)
            except AttributeError:
                # sklearn 1.6+ get_tags incompat with pumpp's old encoder.
                if attributes is not None:
                    attrs = ([attributes] if isinstance(attributes, str)
                             else list(attributes))
                    if all(hasattr(estimator, a) for a in attrs):
                        return  # fitted (classic check) — proceed
                raise

        _v.check_is_fitted = _safe_check_is_fitted
        # pumpp imports the symbol directly in some versions — patch there too.
        try:
            import pumpp.labels as _pl
            if hasattr(_pl, "check_is_fitted"):
                _pl.check_is_fitted = _safe_check_is_fitted
        except Exception:
            pass
        _SKLEARN_PATCHED = True
    except Exception:
        pass


def is_available() -> bool:
    try:
        import crema  # type: ignore  # noqa: F401
        _patch_sklearn_check_is_fitted()
        return True
    except ImportError:
        return False


def transcribe_chords(audio_path: Path) -> list[ChordEvent]:
    """Return ChordEvent[] from CREMA. Raises ImportError if not installed."""
    _patch_sklearn_check_is_fitted()
    try:
        from crema.models.chord import ChordModel  # type: ignore
    except ImportError as e:
        raise ImportError(
            "crema not installed. Run `uv pip install crema`."
        ) from e

    model = ChordModel()
    output = model.predict(filename=str(audio_path))
    # CREMA's predict() return type varies by jams version: older builds
    # return a jams.JAMS (with .annotations), newer return the chord
    # jams.Annotation directly. Handle both.
    if hasattr(output, "annotations"):
        anns = output.annotations.search(namespace="chord")
        ann = anns[0] if anns else output.annotations[0]
    else:
        ann = output                      # already an Annotation
    events: list[ChordEvent] = []
    for obs in ann.data:
        label = str(obs.value).strip()
        if not label or label == "N" or label.upper() in {"N.C.", "X"}:
            events.append(ChordEvent(
                start_sec=float(obs.time),
                end_sec=float(obs.time + obs.duration),
                root="?", quality="N", label="N", confidence=float(obs.confidence or 0.5),
            ))
            continue
        root, quality, full_label = _parse_crema_label(label)
        events.append(ChordEvent(
            start_sec=float(obs.time),
            end_sec=float(obs.time + obs.duration),
            root=root, quality=quality,
            label=full_label,
            confidence=float(obs.confidence or 0.7),
        ))
    return events


def _parse_crema_label(label: str) -> tuple[str, str, str]:
    """CREMA labels look like 'C:maj', 'F:min7', 'G:7', 'D:min/F#'.

    Return (root, normalized_quality, pretty_label). We keep the original
    pretty label so 7ths / suspensions / slash bass show through to the UI.
    """
    if ":" not in label:
        return ("?", "maj", label)
    root_part, quality_part = label.split(":", 1)
    root = root_part.strip()
    # Strip bass-slash before deriving quality.
    bass = ""
    if "/" in quality_part:
        quality_part, bass = quality_part.split("/", 1)
    qp = quality_part.strip().lower()
    if qp.startswith("min"):
        norm = "min"
    elif qp.startswith("dim"):
        norm = "dim"
    elif qp.startswith("aug"):
        norm = "aug"
    elif qp.startswith("sus"):
        norm = "maj"      # sus → render via pretty label
    else:
        norm = "maj"
    pretty_suffix = _pretty_suffix(qp)
    pretty = f"{root}{pretty_suffix}"
    if bass:
        pretty = f"{pretty}/{bass.strip()}"
    return root, norm, pretty


def _pretty_suffix(qp: str) -> str:
    """Translate CREMA's `min7`, `maj7`, `7`, `sus4` etc. into pretty text."""
    if not qp or qp == "maj":
        return ""
    if qp.startswith("min"):
        rest = qp[3:]
        return "m" + rest          # min7 → m7
    return qp                        # 7, maj7, sus4, dim7, etc.


def merge_with_template(
    template_events: list[ChordEvent],
    crema_events: list[ChordEvent],
    template_weight: float = 0.45,
    crema_weight: float = 0.55,
) -> list[ChordEvent]:
    """Confidence-weighted merge of two chord-event streams.

    For each template event, find the CREMA event whose mid-point falls
    inside the template event's interval. Pick the candidate whose
    weighted confidence is higher; bump confidence for unanimous calls
    (both agree on the same label → confidence becomes 1 − (1−c1)(1−c2)).
    """
    if not crema_events:
        return template_events

    # Build a quick O(1) lookup of CREMA events by their start time.
    crema_sorted = sorted(crema_events, key=lambda e: e.start_sec)

    out: list[ChordEvent] = []
    for tev in template_events:
        midpoint = 0.5 * (tev.start_sec + tev.end_sec)
        cev = _crema_at(crema_sorted, midpoint)
        if cev is None:
            out.append(tev)
            continue
        if cev.label == tev.label:
            # Agreement — boost confidence using independent-sources rule.
            new_conf = 1.0 - (1.0 - tev.confidence) * (1.0 - cev.confidence)
            out.append(replace(tev, confidence=min(1.0, new_conf)))
            continue

        # ── Extension preservation (jazz harmony) ────────────────────
        # The base template detector only knows 24 triads, so it labels a
        # Cmaj7 as plain "C". When CREMA adds a 7th/9th/sus/add on the
        # SAME root with a COMPATIBLE quality family, that's not a
        # conflict — it's CREMA enriching the triad. Adopt CREMA's richer
        # label rather than letting the weighted vote discard the
        # extension (which is how 7ths/jazz chords were being lost).
        if (cev.root == tev.root
                and _family(cev.quality) == _family(tev.quality)):
            cr, tr = _richness(cev.label), _richness(tev.label)
            if cr > tr:
                # CREMA enriches the triad (e.g. C → Cmaj7) — adopt it.
                new_conf = 1.0 - (1.0 - tev.confidence) * (1.0 - cev.confidence)
                out.append(replace(tev, root=cev.root, quality=cev.quality,
                                   label=cev.label, confidence=min(1.0, new_conf)))
                continue
            if tr > cr:
                # Template already carries a richer extension (e.g. a
                # chroma-detected Cadd9) that CREMA's vocabulary can't
                # express — KEEP it rather than letting CREMA's confident
                # triad downgrade it. This is how add9/6/sus survive.
                new_conf = 1.0 - (1.0 - tev.confidence) * (1.0 - cev.confidence)
                out.append(replace(tev, confidence=min(1.0, new_conf)))
                continue

        # Genuine disagreement (different root, or maj-vs-min) — pick the
        # weighted winner. CREMA carries richer vocab so we bias toward it.
        t_score = template_weight * tev.confidence
        c_score = crema_weight * cev.confidence
        if c_score > t_score:
            out.append(replace(tev,
                                root=cev.root,
                                quality=cev.quality,
                                label=cev.label,
                                confidence=cev.confidence))
        else:
            out.append(tev)
    return out


def _family(quality: str) -> str:
    """Coarse quality family so 'maj' and 'maj7' count as compatible
    (same family), while 'maj' vs 'min' is a real conflict."""
    q = (quality or "").lower()
    if q.startswith("min") or q.startswith("m") and not q.startswith("maj"):
        return "minor"
    if q.startswith("dim"):
        return "dim"
    if q.startswith("aug"):
        return "aug"
    return "major"   # maj, maj7, 7(dominant lives on a major triad), sus


def _richness(label: str) -> int:
    """How many harmony extensions a label carries — used to decide
    whether CREMA's label is a strict enrichment of the triad. Counts
    7/9/11/13/sus/add/alterations."""
    s = (label or "").lower()
    score = 0
    for token in ("maj7", "7", "9", "11", "13", "sus", "add", "6", "dim", "aug"):
        if token in s:
            score += 1
    # '#' / 'b' alterations after the root add richness too.
    body = s[1:] if s else ""
    score += body.count("#") + body.count("b")
    return score


def _crema_at(events: list[ChordEvent], t: float) -> ChordEvent | None:
    # Linear scan is fine for typical track lengths (~50-200 events).
    for ev in events:
        if ev.start_sec <= t < ev.end_sec:
            return ev
    return None
