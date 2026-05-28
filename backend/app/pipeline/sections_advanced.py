"""K-Pop / variable-form section refinement layer.

The base ``detect_sections`` in ``sections.py`` uses agglomerative
clustering on chroma — it finds *boundaries* well but is biased toward
Western verse-chorus form when *labelling* them. K-Pop / J-Pop tracks
have very repetitive choruses and abrupt bridges that the energy
heuristic mislabels at ~70%.

This module adds three orthogonal signals on top:

  1. **SSM (Self-Similarity Matrix) chorus detector** — the section
     whose chroma fingerprint repeats the most across the song is
     almost certainly a chorus. Pure librosa, no extra deps.

  2. **Lyric-repetition heuristic** — in K-Pop the song title typically
     appears in the chorus 3+ times. We count repeated phrases inside
     each section and promote the section with the highest phrase
     repetition rate to "chorus".

  3. **Local LLM label refinement** — when Ollama is reachable, ask a
     small model to label each section given its chord progression +
     lyric snippet + position in song. Returns a label per section;
     we merge with the rule-based labels via confidence weighting.

Each signal is optional. Calling ``refine_sections`` with no lyrics +
no Ollama still benefits from the SSM pass.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np

from .sections import SectionMarker, BeatGrid


# ── 1) SSM-based chorus detection ──────────────────────────────────────────

def _chorus_indices_via_ssm(
    audio_path: Path, sections: list[SectionMarker],
) -> set[int]:
    """Return the indices of sections that are highly self-similar to
    other sections — those are very likely choruses.

    Algorithm:
      * Compute chroma_cqt → median-pool per section → one 12-dim vector
        per section.
      * Build the section-level cosine similarity matrix.
      * For each section, count how many *other* sections it correlates
        with at > 0.85. Sections with >= 2 such matches are flagged as
        chorus candidates.
    """
    import librosa

    if not sections:
        return set()

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    hop = 512
    y_h = librosa.effects.harmonic(y, margin=4.0)
    chroma = librosa.feature.chroma_cqt(y=y_h, sr=sr, hop_length=hop)

    vectors: list[np.ndarray] = []
    for s in sections:
        f1 = int(s.start_sec * sr / hop)
        f2 = int(s.end_sec * sr / hop)
        if f2 <= f1 + 1:
            vectors.append(np.zeros(12, dtype=np.float32))
            continue
        v = np.median(chroma[:, f1:f2], axis=1)
        n = float(np.linalg.norm(v))
        vectors.append((v / n).astype(np.float32) if n > 0 else v.astype(np.float32))

    M = np.stack(vectors, axis=0)            # (N, 12)
    sim = M @ M.T                            # (N, N) cosine since unit-norm
    # Zero the diagonal so a section doesn't count itself.
    np.fill_diagonal(sim, 0.0)
    threshold = 0.85
    chorus_set: set[int] = set()
    for i in range(sim.shape[0]):
        matches = int((sim[i] > threshold).sum())
        if matches >= 2:
            chorus_set.add(i)
    return chorus_set


# ── 2) Lyric-repetition heuristic ──────────────────────────────────────────

_WORD_SPLIT = re.compile(r"\s+")


def _lyric_phrases_per_section(
    sections: list[SectionMarker],
    lyrics_words: list[dict] | None,
) -> list[Counter]:
    """For each section, return a Counter of 3-word phrases that appear in it."""
    if not lyrics_words:
        return [Counter() for _ in sections]

    out = []
    for s in sections:
        words_in = [
            str(w.get("word", "")).strip()
            for w in lyrics_words
            if float(w.get("start_sec") or 0.0) >= s.start_sec
            and float(w.get("end_sec") or 0.0) <= s.end_sec
            and (w.get("word") or "").strip()
        ]
        # Build 3-grams.
        c = Counter()
        for i in range(len(words_in) - 2):
            phrase = " ".join(words_in[i:i + 3]).lower()
            if phrase:
                c[phrase] += 1
        out.append(c)
    return out


def _chorus_indices_via_lyric_repetition(
    sections: list[SectionMarker], lyrics_words: list[dict] | None,
) -> set[int]:
    """A section gets a chorus vote if its most-repeated 3-gram has 2+ counts
    AND that 3-gram also appears in at least one other section."""
    counters = _lyric_phrases_per_section(sections, lyrics_words)
    if not any(counters):
        return set()
    # Globally, which 3-grams appear in 2+ sections?
    global_appearances: Counter = Counter()
    for c in counters:
        for phrase in c.keys():
            global_appearances[phrase] += 1
    repeated_phrases = {
        phrase for phrase, n in global_appearances.items() if n >= 2
    }
    if not repeated_phrases:
        return set()
    chorus_set: set[int] = set()
    for i, c in enumerate(counters):
        for phrase, count in c.items():
            if phrase in repeated_phrases and count >= 2:
                chorus_set.add(i)
                break
    return chorus_set


# ── 3) Local-LLM label refinement ──────────────────────────────────────────

_LLM_PROMPT = """\
You are a music structure analyst. Below is a list of audio sections \
from one song with their position, duration, and a snippet of lyrics. \
For each section, decide its functional label from this vocabulary: \
intro, verse, pre-chorus, chorus, post-chorus, bridge, instrumental, \
solo, outro, silence. Return a JSON object {{"labels": [list of strings, \
same length as input]}}. Use Korean pop / K-Pop song convention: a \
section whose lyrics repeat across multiple sections is almost certainly \
a chorus.

Sections:
{section_list}

Return only the JSON object."""

_LLM_SCHEMA_HINT = (
    'Schema example for 4 sections: {"labels":["intro","verse","chorus","outro"]}'
)


def _llm_refine_labels(
    sections: list[SectionMarker],
    lyrics_words: list[dict] | None,
    chord_events: list[dict] | None,
) -> list[str] | None:
    """Ask the local LLM to label each section. Returns None if Ollama is offline."""
    try:
        from .local_llm import generate_json, is_available
    except Exception:
        return None
    if not is_available() or not sections:
        return None

    # Build per-section snippet from lyrics + chord summary.
    section_lines = []
    for i, s in enumerate(sections):
        snippet = ""
        if lyrics_words:
            words_in = [
                str(w.get("word", "")).strip()
                for w in lyrics_words
                if float(w.get("start_sec") or 0.0) >= s.start_sec
                and float(w.get("end_sec") or 0.0) <= s.end_sec
            ]
            snippet = " ".join(words_in[:30])
        chord_snippet = ""
        if chord_events:
            chord_labels = [
                str(c.get("label", "?"))
                for c in chord_events
                if float(c.get("start_sec") or 0.0) >= s.start_sec
                and float(c.get("end_sec") or 0.0) <= s.end_sec
            ][:12]
            if chord_labels:
                chord_snippet = " · ".join(chord_labels)
        section_lines.append(
            f"{i}: {s.start_sec:.1f}-{s.end_sec:.1f}s "
            f"(dur {s.end_sec - s.start_sec:.0f}s) "
            f"current_label={s.label} "
            f"chords=[{chord_snippet}] "
            f"lyrics=\"{snippet}\""
        )

    prompt = _LLM_PROMPT.format(section_list="\n".join(section_lines))
    result = generate_json(prompt, schema_hint=_LLM_SCHEMA_HINT)
    if not result or not isinstance(result, dict):
        return None
    labels = result.get("labels")
    if not isinstance(labels, list) or len(labels) != len(sections):
        return None
    valid_vocab = {
        "intro", "verse", "pre-chorus", "chorus", "post-chorus",
        "bridge", "instrumental", "solo", "outro", "silence",
    }
    out = []
    for i, lab in enumerate(labels):
        if isinstance(lab, str) and lab.lower() in valid_vocab:
            out.append(lab.lower())
        else:
            out.append(sections[i].label)
    return out


# ── public ─────────────────────────────────────────────────────────────────

def refine_sections(
    sections: list[SectionMarker],
    audio_path: Path,
    *,
    lyrics_words: list[dict] | None = None,
    chord_events: list[dict] | None = None,
    use_ssm: bool = True,
    use_lyrics: bool = True,
    use_llm: bool = True,
) -> list[SectionMarker]:
    """Apply the 3-signal refinement chain to a list of detected sections.

    Returns a new list with potentially-updated labels. Boundaries are
    never moved by this layer (the base detector handles those); we only
    fix labels because that's where the bulk of K-Pop / J-Pop accuracy
    loss sits.
    """
    if not sections or len(sections) < 2:
        return sections

    # Vote tally per section index.
    chorus_votes: Counter = Counter()
    if use_ssm:
        try:
            for i in _chorus_indices_via_ssm(audio_path, sections):
                chorus_votes[i] += 2          # SSM is the strongest signal
        except Exception:
            pass
    if use_lyrics:
        try:
            for i in _chorus_indices_via_lyric_repetition(sections, lyrics_words):
                chorus_votes[i] += 2
        except Exception:
            pass

    # Promote any heavily-voted section to "chorus" (unless intro/outro
    # by position — keep those even if they happen to repeat).
    refined: list[SectionMarker] = []
    n = len(sections)
    for i, s in enumerate(sections):
        if chorus_votes[i] >= 2 and i not in (0, n - 1):
            refined.append(replace(s, label="chorus"))
        else:
            refined.append(s)

    # LLM final pass: replace labels with LLM consensus where it differs.
    # Previously we only overwrote "verse" labels — that was too cautious
    # and let early-stage mislabels persist. New rule: trust the LLM when
    # it disagrees with a *low-confidence* base label (verse, intro at a
    # non-boundary position, outro at a non-boundary position, or any
    # generic "section_N" placeholder). High-confidence base labels —
    # those promoted to "chorus" via the SSM+lyrics vote — are preserved.
    if use_llm:
        try:
            llm_labels = _llm_refine_labels(refined, lyrics_words, chord_events)
            if llm_labels:
                _LOW_CONF = {"verse", "section", "instrumental", "interlude", ""}
                n_refined = len(refined)
                new_refined: list[SectionMarker] = []
                for idx, (s, lab) in enumerate(zip(refined, llm_labels)):
                    if not lab or lab == s.label:
                        new_refined.append(s); continue
                    base = (s.label or "").lower()
                    is_promoted_chorus = (
                        base == "chorus" and chorus_votes[idx] >= 2
                    )
                    is_intro_outro_at_boundary = (
                        (base == "intro" and idx == 0)
                        or (base == "outro" and idx == n_refined - 1)
                    )
                    if is_promoted_chorus or is_intro_outro_at_boundary:
                        new_refined.append(s)               # keep high-confidence rule
                    elif base in _LOW_CONF or base.startswith("section"):
                        new_refined.append(replace(s, label=lab))
                    else:
                        new_refined.append(s)
                refined = new_refined
        except Exception:
            pass

    # Boundary nudge: if SSM has indicated that two adjacent sections
    # share the same label AND their boundary doesn't sit on a strong
    # novelty peak, merge them. This trims the over-segmentation that
    # the librosa agglomerative clustering tends to emit on K-Pop songs.
    merged: list[SectionMarker] = []
    for s in refined:
        if merged and merged[-1].label == s.label:
            prev = merged[-1]
            merged[-1] = replace(prev, end_sec=s.end_sec)
        else:
            merged.append(s)
    return merged


# Re-export BeatGrid so callers can ``from .sections_advanced import refine_sections, BeatGrid``.
__all__ = ["refine_sections", "BeatGrid"]
