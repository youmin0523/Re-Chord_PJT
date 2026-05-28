"""Convert transcribed MIDI into clean, print-ready notation.

Improvements over the v1 single-stave / single-page output:

  * Grand staff for piano / harmonic stems (notes ≥ C4 → treble, < C4 → bass)
    so ledger-line pileups disappear and the score reads like normal piano music.
  * Real A4-style page break (Verovio multi-page) rather than one very long SVG.
  * Multi-page SVGs are stitched into a single PDF (svglib + reportlab) so users
    can print the score directly.
  * music21 handles quantization + key signature + meter inference.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)


StemKind = Literal[
    "vocals", "piano", "guitar", "bass", "drums", "other", "instrumental", "mix",
]
NotationStyle = Literal[
    "lead_sheet", "grand_staff", "single_treble", "single_bass",
    "drum", "guitar_tab", "bass_tab", "choir_satb",
]


# Stem -> default notation strategy.
#   "lead_sheet" : melody on a single treble + chord symbols + lyrics
#   "grand_staff": split by pitch into treble (≥ C4) + bass (< C4)
#   "drum"       : 1-line / 5-line percussion clef with onset-classified hits
#   "guitar_tab" : 6-line TAB with fret numbers (single melodic line)
#   "bass_tab"   : 4-line bass TAB
#   "choir_satb" : 4 voice parts split by pitch range (S/A/T/B)
#   "single_treble" / "single_bass": fallback single-clef views
NOTATION_BY_STEM: dict[str, str] = {
    "vocals": "lead_sheet",
    "guitar": "guitar_tab",     # guitarists overwhelmingly want TAB
    "bass": "bass_tab",
    "drums": "drum",
    "piano": "grand_staff",
    "other": "grand_staff",
    "instrumental": "grand_staff",
    "mix": "grand_staff",
}

# Standard 5-piece kit (kick · snare · tom1(high) · tom2(mid) · floor tom)
# + HH / ride / crash. This is the rock/pop/CCM default — 4-piece is jazz.
# Maps GM percussion MIDI numbers to our internal lane names.
GM_DRUM_LANES: dict[int, str] = {
    # Bass drum
    35: "kick",  36: "kick",
    # Snare (acoustic + electric/side variations)
    37: "snare", 38: "snare", 40: "snare",
    # Hi-hat
    42: "hh_closed", 44: "hh_pedal", 46: "hh_open",
    # Crash cymbals
    49: "crash1", 57: "crash2", 55: "splash",
    # Ride cymbals
    51: "ride1",  59: "ride2",  53: "ride_bell",
    # Toms — 5-piece convention: tom1 (highest, top of kit) → tom2 → floor
    50: "tom1", 48: "tom1",      # high tom
    47: "tom2", 45: "tom2",      # mid tom
    43: "floor", 41: "floor",    # floor tom
    # Aux percussion (cowbell, tambourine, etc.) — show on its own lane
    56: "cowbell", 54: "tambourine",
}

# Where each lane sits on the percussion staff (music21 line/space numbers).
# 5-line staff, lines numbered 1 (bottom) → 5 (top). Cymbals notated above.
DRUM_LANE_TO_STAFF: dict[str, tuple[str, int]] = {
    # (label, display_step) — step is a music21 pitch-like position used for layout
    "kick":      ("Bass Drum",   38),   # F4 (below middle line)
    "snare":     ("Snare",       50),   # D5 (third space)
    "tom1":      ("High Tom",    52),   # E5
    "tom2":      ("Mid Tom",     48),   # C5
    "floor":     ("Floor Tom",   45),   # A4
    "hh_closed": ("Hi-Hat",      55),   # G5 (above staff, x-notehead)
    "hh_open":   ("Hi-Hat Open", 55),
    "hh_pedal":  ("Hi-Hat Pedal",36),   # below staff, x-notehead
    "crash1":    ("Crash 1",     57),   # A5
    "crash2":    ("Crash 2",     58),   # A♯5/B5
    "ride1":     ("Ride",        56),   # G♯5
    "ride2":     ("Ride 2",      56),
    "ride_bell": ("Ride Bell",   56),
    "splash":    ("Splash",      59),
    "cowbell":   ("Cowbell",     53),
    "tambourine":("Tambourine",  54),
}

# Standard tuning for guitar/bass (low → high). Used to build fret maps.
GUITAR_TUNING_MIDI = [40, 45, 50, 55, 59, 64]   # E2 A2 D3 G3 B3 E4
BASS_TUNING_MIDI = [28, 33, 38, 43]              # E1 A1 D2 G2
GUITAR_MAX_FRET = 22
BASS_MAX_FRET = 22

C4_MIDI = 60


@dataclass
class ScoreResult:
    musicxml_path: Path
    svg_paths: list[Path]              # one per page
    pdf_path: Path | None
    title: str
    parts: int
    measures: int
    pages: int
    timemap_path: Path | None = None    # JSON: [{measure, start_sec, end_sec}, ...]


# ----------------------------------------------------------------------------
# MIDI -> music21 score with grand staff split when appropriate.
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Notation builders for specialised stems (drums / guitar TAB / bass TAB /
# choir SATB). Each builds a music21 Score directly from MIDI events; the
# common chord/lyrics/aux-cue overlays are still applied afterwards.
# ----------------------------------------------------------------------------

def _midi_pitch_to_fret(
    pitch: int, tuning: list[int], max_fret: int = 22,
    *, prev_string: int | None = None, prev_fret: int | None = None,
) -> tuple[int, int] | None:
    """Choose a playable (string, fret) for the requested MIDI pitch.

    The simple "lowest fret" pick produces wildly unplayable runs because
    every note jumps to the highest open string. We score each candidate
    by three factors:

      1. **Playability box** — frets 0-12 are the bread-and-butter range
         for most worship/pop guitar. Anything above 14 gets a penalty
         unless the previous note was already up there.
      2. **String continuity** — if we have a previous string/fret,
         prefer candidates on the same or adjacent string. The
         crow-flies distance on the fretboard is approximately
         ``|Δstring| + |Δfret| * 0.6``.
      3. **Open string bonus** — open strings (fret 0) are a slight
         bonus because they ring out and are easy to play.

    Returns ``(string_index, fret)`` or ``None`` if unplayable.
    """
    candidates: list[tuple[int, int]] = []
    for i, open_pitch in enumerate(tuning):
        fret = pitch - open_pitch
        if 0 <= fret <= max_fret:
            candidates.append((i, fret))
    if not candidates:
        return None
    if len(candidates) == 1 or prev_string is None or prev_fret is None:
        # No context — fall back to the lowest-fret choice, which is
        # still our default opening-position pick.
        return min(candidates, key=lambda c: (c[1], -c[0]))

    def _cost(cand: tuple[int, int]) -> float:
        s, f = cand
        # Distance to the previous fretted position.
        d_string = abs(s - prev_string)
        d_fret = abs(f - prev_fret)
        cost = d_string + 0.6 * d_fret
        # Penalty for high-position frets unless we were already up there.
        if f > 14 and prev_fret < 12:
            cost += 4.0
        if f > 17:
            cost += 2.0
        # Bonus for open strings.
        if f == 0:
            cost -= 0.4
        return cost

    return min(candidates, key=_cost)


def _flatten_midi_notes(midi_path: Path) -> list[dict]:
    """Read all (pitch, start, end) notes from a MIDI file as a flat list."""
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    notes: list[dict] = []
    for inst in pm.instruments:
        for n in inst.notes:
            notes.append({
                "pitch": int(n.pitch),
                "start": float(n.start),
                "end": float(n.end),
                "velocity": int(n.velocity),
            })
    notes.sort(key=lambda x: (x["start"], x["pitch"]))
    return notes


def _build_drum_score(midi_path: Path, bpm: float):
    """Drum notation on a percussion clef. Each detected pitch is mapped to
    a 5-piece kit lane (kick/snare/tom1/tom2/floor + HH/ride/crash)."""
    from music21 import stream, clef, instrument, note as m21note, meter

    score = stream.Score()
    part = stream.Part(id="drums")
    part.insert(0, instrument.Percussion())
    part.insert(0, clef.PercussionClef())
    part.insert(0, meter.TimeSignature("4/4"))

    qps = (bpm or 120.0) / 60.0
    raw = _flatten_midi_notes(midi_path)
    if not raw:
        score.insert(0, part)
        return score

    # Map onsets to drum lanes. The drum transcriber (a2d2) emits GM
    # percussion pitches directly, so GM_DRUM_LANES catches almost
    # everything. When the input is raw basic-pitch (non-GM), we fall
    # back to a register heuristic that mirrors the a2d2 band split.
    seen_lanes: set[str] = set()        # only label each lane's first hit
    for n in raw:
        lane = GM_DRUM_LANES.get(n["pitch"])
        if lane is None:
            p = n["pitch"]
            # Register heuristic tuned to acoustic-kit fundamentals:
            #   kick body ~40-100 Hz → MIDI ~28-43
            #   snare ~150-250 Hz    → MIDI ~44-57
            #   toms ~80-200 Hz fundamentals but transient mid energy
            #   cymbals/hats → bright, mapped to high MIDI
            if p < 44:
                lane = "kick"
            elif p < 50:
                lane = "snare"
            elif p < 58:
                lane = "tom2"
            elif p < 66:
                lane = "tom1"
            elif p < 72:
                lane = "floor"
            else:
                lane = "hh_closed"

        label, display_pitch = DRUM_LANE_TO_STAFF.get(lane, (lane, 50))
        is_cymbal = (lane.startswith("hh_") or lane.startswith("crash")
                     or lane.startswith("ride") or lane in ("splash",))
        nh = "x" if is_cymbal else "normal"
        try:
            nn = m21note.Note()
            nn.pitch.midi = display_pitch
            nn.notehead = nh
            # Stem direction convention: kick/floor down, everything else up.
            try:
                nn.stemDirection = "down" if lane in ("kick", "floor", "hh_pedal") else "up"
            except Exception:
                pass
            nn.offset = max(0.0, n["start"] * qps)
            nn.quarterLength = max(0.125, (n["end"] - n["start"]) * qps)
            # Label only the first occurrence of each lane so the staff
            # doesn't drown in repeated "Hi-Hat" text on every 8th note.
            if lane not in seen_lanes:
                nn.addLyric(label)
                seen_lanes.add(lane)
            part.insert(nn.offset, nn)
        except Exception:
            continue

    score.insert(0, part)
    return score


def _build_tab_score(midi_path: Path, bpm: float, tuning: list[int],
                     max_fret: int, instrument_name: str):
    """Guitar/Bass TAB. Each note gets its string + fret position and is
    placed on the standard 6-line (or 4-line) tab staff."""
    from music21 import stream, clef, instrument, note as m21note, meter, tablature

    score = stream.Score()
    part = stream.Part(id="tab")
    inst_cls = instrument.ElectricGuitar if instrument_name == "guitar" \
        else instrument.ElectricBass
    try:
        part.insert(0, inst_cls())
    except Exception:
        pass
    part.insert(0, meter.TimeSignature("4/4"))
    try:
        part.insert(0, clef.TabClef())
    except Exception:
        pass

    qps = (bpm or 120.0) / 60.0
    raw = _flatten_midi_notes(midi_path)
    if not raw:
        score.insert(0, part)
        return score

    # Sort by onset so the string-continuity heuristic in
    # _midi_pitch_to_fret sees notes in playing order.
    raw.sort(key=lambda r: r["start"])

    prev_string: int | None = None
    prev_fret: int | None = None
    n_strings = len(tuning)
    for n in raw:
        pos = _midi_pitch_to_fret(
            n["pitch"], tuning, max_fret,
            prev_string=prev_string, prev_fret=prev_fret,
        )
        if pos is None:
            continue
        string_idx, fret = pos
        prev_string, prev_fret = string_idx, fret
        try:
            nn = m21note.Note()
            nn.pitch.midi = n["pitch"]
            nn.quarterLength = max(0.125, (n["end"] - n["start"]) * qps)
            # music21 tab annotations: store fret + string index so musicxml
            # exporters mark them on the right tab line.
            try:
                ti = tablature.FretNote(fret=fret, string=string_idx + 1)
                nn.tablature = ti
            except Exception:
                pass
            # Music21 + Verovio TAB support is incomplete — render reliably
            # by appending a human-readable fret label and a fingering hint.
            # Label format: "<fret>(<string>)" with strings numbered from
            # the *high* E down (standard TAB convention: 1 = high E),
            # so we flip ``string_idx + 1`` for guitar.
            tab_string_label = (
                n_strings - string_idx if n_strings == 6 else string_idx + 1
            )
            nn.addLyric(f"{fret}({tab_string_label})")
            try:
                nn.editorial.fingering = str(fret)
            except Exception:
                pass
            part.insert(max(0.0, n["start"] * qps), nn)
        except Exception:
            continue

    score.insert(0, part)
    return score


# Pitch-range boundaries for forced SATB split. Imperfect by definition, see
# limitations note in the score panel: every choir auto-split is just a draft.
SATB_RANGES = {
    "S": (60, 84),   # C4 – C6
    "A": (53, 76),   # F3 – E5
    "T": (47, 67),   # B2 – G4
    "B": (40, 60),   # E2 – C4
}


def _build_choir_satb_score(midi_path: Path, bpm: float):
    """Force-split a polyphonic vocal MIDI into 4 parts (Soprano · Alto ·
    Tenor · Bass) by pitch register. Far from perfect — the user is the
    final arbiter via the manual editor — but a usable starting draft."""
    from music21 import stream, clef, instrument, note as m21note, meter

    score = stream.Score()
    parts: dict[str, stream.Part] = {}
    for voice, clef_obj, inst in [
        ("S", clef.TrebleClef(), instrument.Soprano),
        ("A", clef.TrebleClef(), instrument.Alto),
        ("T", clef.Treble8vbClef(), instrument.Tenor),
        ("B", clef.BassClef(), instrument.Bass),
    ]:
        p = stream.Part(id=f"choir_{voice.lower()}")
        try:
            p.insert(0, inst())
        except Exception:
            # An instrument shim that won't construct (rare, music21 version
            # mismatch) just means the part lacks the SATB voice tag — the
            # notes still render. Log so a regression surfaces in prod logs.
            log.warning("score.satb: instrument tag failed for voice=%s; rendering without", voice)
        p.insert(0, clef_obj)
        p.insert(0, meter.TimeSignature("4/4"))
        parts[voice] = p

    qps = (bpm or 120.0) / 60.0
    raw = _flatten_midi_notes(midi_path)

    # ── Chord-grouped voice assignment ──────────────────────────────
    # Assigning each note independently by range-midpoint distance causes
    # voice-crossing in the overlap zone (E4-C5, where both Alto and
    # Tenor are plausible). Instead we group simultaneous notes — notes
    # whose onsets fall within a small window — and assign them top-down
    # to S > A > T > B. This guarantees S ≥ A ≥ T ≥ B at every instant,
    # which is the defining property of a readable SATB reduction.
    ONSET_WINDOW = 0.08  # 80 ms — notes inside this window count as a chord
    groups: list[list[dict]] = []
    cur: list[dict] = []
    cur_onset: float | None = None
    for n in sorted(raw, key=lambda r: r["start"]):
        if cur_onset is None or abs(n["start"] - cur_onset) <= ONSET_WINDOW:
            cur.append(n)
            cur_onset = n["start"] if cur_onset is None else cur_onset
        else:
            groups.append(cur)
            cur = [n]
            cur_onset = n["start"]
    if cur:
        groups.append(cur)

    voice_order = ("S", "A", "T", "B")
    for group in groups:
        # Sort the simultaneous notes high → low.
        chord = sorted(group, key=lambda r: r["pitch"], reverse=True)
        # When ≤ 4 notes, assign top-down S/A/T/B. When > 4, the extra
        # (lowest) notes fold into the Bass so nothing is dropped.
        for idx, n in enumerate(chord):
            voice = voice_order[min(idx, 3)]
            try:
                nn = m21note.Note(midi=n["pitch"])
                nn.quarterLength = max(0.125, (n["end"] - n["start"]) * qps)
                parts[voice].insert(max(0.0, n["start"] * qps), nn)
            except Exception:
                continue

    for voice in ("S", "A", "T", "B"):
        score.insert(0, parts[voice])
    return score


def _normalise_chord_label(label: str) -> str:
    """Convert our internal chord label into a music21-parseable figure.

    music21's ``harmony.ChordSymbol`` accepts figures like
    ``"C"``, ``"Am"``, ``"G7"``, ``"Cmaj7"``, ``"Bb/F"``, ``"Dsus4"`` etc.
    Our pipeline emits a wider set (e.g. ``"D:min7"`` from CREMA,
    ``"Eadd9"`` from theory rerank). This normaliser:

      * Routes CREMA's ``"D:min7"`` -> ``"Dmin7"`` (colon → empty).
      * Maps the bare ``"Bm"`` family unchanged — music21 accepts it.
      * Routes ``"sus"``/``"add"``/``"dim"``/``"aug"`` extensions through
        untouched (parse failures fall back to root-only).
      * Strips trailing whitespace and stray characters that have broken
        previous engraves (e.g. ``"C  "``, ``"C "``).

    The function is intentionally lossless when in doubt — if the label
    is already valid, we return it as-is.
    """
    if not label:
        return ""
    # Strip every kind of whitespace, including U+00A0 (NBSP) that
    # sometimes leaks in from copy-paste / web sources.
    s = "".join(c for c in label if not c.isspace())
    # CREMA emits "Root:Quality" — strip the colon so music21 sees "Dmin7".
    if ":" in s:
        s = s.replace(":", "")
    # music21 spells flats as "-" not "b". Convert "Bb" → "B-", "Eb" → "E-",
    # "Ab/Eb" → "A-/E-". Only the lowercase b *immediately* following a
    # pitch letter is treated as a flat — leaves "Bsus" / "Cadd" intact.
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if ch in "ABCDEFG" and nxt == "b":
            out.append(ch); out.append("-")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _attach_chord_symbols(
    score, chord_events: list[dict] | None, bpm: float
) -> None:
    """Drop ChordSymbol objects onto the top part at the right offsets.

    chord_events: list of {start_sec, end_sec, label, root, quality}
    bpm: used to convert seconds -> quarterLength offsets.

    Robust parsing: each label is normalised first, parsed with
    ``harmony.ChordSymbol``, and on parse failure the chord is dropped
    to root-only (e.g. ``"D:min7"`` → ``"Dm7"`` → ``"Dm"`` → ``"D"``).
    A single defective chord never blocks the rest.
    """
    if not chord_events or bpm <= 0:
        return
    try:
        from music21 import harmony
    except Exception:
        return
    qps = bpm / 60.0
    try:
        target_part = score.parts[0]
    except (AttributeError, IndexError):
        target_part = score

    def _try_parse(fig: str):
        if not fig:
            return None
        try:
            cs = harmony.ChordSymbol(fig)
            # Force music21 to expand the figure into pitches so malformed
            # figures fail here rather than at render time.
            if not cs.pitches:
                return None
            return cs
        except Exception:
            return None

    # When the part already has measures (the common case after MIDI
    # import + makeNotation), a ChordSymbol inserted at a raw part-level
    # offset is silently dropped on MusicXML export. We must insert it
    # INTO the measure that contains the offset, at the measure-relative
    # position. Build the measure index once.
    measures = list(target_part.getElementsByClass("Measure"))

    def _place(cs, abs_offset: float) -> None:
        if measures:
            # Find the measure whose [offset, offset+barDuration) contains
            # abs_offset. music21 measure.offset is the part-absolute start.
            chosen = None
            for m in measures:
                m_start = float(m.offset)
                m_len = float(m.barDuration.quarterLength or 4.0)
                if m_start <= abs_offset < m_start + m_len:
                    chosen = m
                    break
            if chosen is None:
                chosen = measures[-1] if abs_offset >= float(measures[-1].offset) else measures[0]
            rel = max(0.0, abs_offset - float(chosen.offset))
            chosen.insert(rel, cs)
        else:
            target_part.insert(abs_offset, cs)

    prev_figure: str | None = None
    for ev in chord_events:
        label = _normalise_chord_label(ev.get("label") or "")
        if not label or label.upper() in {"N", "N.C.", "X"}:
            # A no-chord gap resets the run so the next chord re-prints
            # even if it matches the one before the gap.
            prev_figure = None
            continue
        cs = (_try_parse(label)
              # Strip extensions one at a time until parse succeeds.
              or _try_parse(label.split("/", 1)[0])
              # Drop slash bass.
              or _try_parse((ev.get("root") or "")
                            + (ev.get("quality") or "").replace("maj", ""))
              or _try_parse(ev.get("root") or ""))
        if cs is None:
            continue
        # Suppress consecutive duplicate chord symbols — a chord held for
        # 8 bars should print once, not on every beat the detector
        # emitted. Lead-sheet convention: a symbol means "play this until
        # the next symbol".
        figure = str(getattr(cs, "figure", "") or label)
        if figure == prev_figure:
            continue
        prev_figure = figure
        try:
            _place(cs, float(ev.get("start_sec", 0.0)) * qps)
        except Exception:
            continue


def _tempo_referent_for_meter(time_signature: str | None):
    """Return (music21 Duration, BPM scale) appropriate for a given meter.

    Musical reality:
      - Simple meters (4/4, 3/4, 2/4): quarter-note beat → ♩ = BPM (scale 1.0)
      - Compound (6/8, 9/8, 12/8):    dotted-quarter beat → ♩. = BPM/1.5
      - Cut time / alla breve (2/2):  half-note beat     → 𝅗𝅥 = BPM/2
      - Anything we can't classify cleanly: quarter, scale 1.0 (safe default)

    Returns ``(referent_duration, bpm_scale)`` — apply ``bpm * scale``
    to the source (librosa-detected, quarter-pulse) BPM before printing.
    """
    try:
        from music21 import duration as _dur
    except Exception:
        return None, 1.0
    quarter = _dur.Duration("quarter")
    if not time_signature or "/" not in time_signature:
        return quarter, 1.0
    try:
        num_s, den_s = time_signature.split("/", 1)
        num, den = int(num_s), int(den_s)
    except Exception:
        return quarter, 1.0
    # Compound meter: 8th-note denominator AND numerator a multiple of 3 ≥ 6.
    if den == 8 and num >= 6 and num % 3 == 0:
        # ♩. = dotted-quarter = 1.5 quarterLengths.
        dotted = _dur.Duration(quarterLength=1.5)
        return dotted, (1.0 / 1.5)
    # Cut time / alla breve.
    if den == 2 and num == 2:
        return _dur.Duration("half"), 0.5
    return quarter, 1.0


def _attach_tempo_mark(score, bpm: float, time_signature: str | None = None) -> None:
    """Insert a metronome mark at the top of the first measure so the
    tempo prints in the score's upper-left, as readers expect.

    The mark's referent (which note value the BPM is per) follows the
    detected time signature — compound meters get ♩. = BPM, cut time
    gets 𝅗𝅥 = BPM, simple meters keep ♩ = BPM. BPM input is assumed to be
    the librosa-detected quarter-note pulse and is rescaled accordingly.

    Idempotent-ish: relies on the caller to call it once per score build.
    """
    if not score or bpm <= 0:
        return
    try:
        from music21 import tempo as _tempo, stream as _stream
    except Exception:
        return
    try:
        parts = list(score.parts) or [score]
    except AttributeError:
        parts = [score]
    if not parts:
        return
    target = parts[0]
    try:
        measures = list(target.getElementsByClass(_stream.Measure))
    except Exception:
        measures = []
    container = measures[0] if measures else target
    referent, scale = _tempo_referent_for_meter(time_signature)
    display_bpm = round(float(bpm) * scale, 1)
    try:
        if referent is not None:
            mm = _tempo.MetronomeMark(number=display_bpm, referent=referent)
        else:
            mm = _tempo.MetronomeMark(number=display_bpm)
        container.insert(0, mm)
    except Exception:
        pass


def _ensure_measures(score) -> None:
    """Bar a score's parts into measures if they aren't already.

    The specialized builders (drum / TAB / SATB) insert notes at raw
    part-level offsets. Until music21 makes measures, the overlay
    attachers (section markers, tempo, chord symbols) have no measures
    to target and silently no-op — which is exactly how section markers
    were vanishing from drum/TAB/SATB scores on export.

    Calling makeMeasures up-front guarantees a measure-structured part
    so every overlay lands and survives MusicXML export. Best-effort:
    a malformed part is left as-is rather than raising.
    """
    try:
        from music21 import stream as _stream
    except Exception:
        return
    try:
        parts = list(score.parts) if hasattr(score, "parts") else []
    except Exception:
        parts = []
    if not parts:
        parts = [score]
    for part in parts:
        try:
            has_measures = bool(list(part.getElementsByClass(_stream.Measure)))
            if not has_measures:
                part.makeMeasures(inPlace=True)
        except Exception:
            # Leave unbarred — export's own makeNotation will still bar it,
            # we just lose overlays on this part. Never block the build.
            continue


def _attach_section_markers(
    score, sections: list[dict] | None, bpm: float,
) -> None:
    """Attach section labels (intro / verse / chorus / bridge / …) as
    rehearsal marks on every score, regardless of notation style.

    ``sections``: ordered list of dicts with at least ``start_sec`` and
    ``label`` (matches our sections.json schema). Marks are inserted at
    the nearest measure boundary so a drummer reading a percussion chart
    or a guitarist reading TAB still sees the song structure.

    Idempotent — calling twice on the same score appends two marks per
    boundary, so callers shouldn't.
    """
    if not sections or bpm <= 0:
        return
    try:
        from music21 import expressions, stream as _stream
    except Exception:
        return
    qps = bpm / 60.0
    try:
        parts = list(score.parts) or [score]
    except AttributeError:
        parts = [score]
    if not parts:
        return
    # Attach to the FIRST part only — RehearsalMark on one part renders
    # at the top of every system across the score.
    target = parts[0]
    try:
        measures = list(target.getElementsByClass(_stream.Measure))
    except Exception:
        measures = []
    if not measures:
        return
    # Map each section start to the nearest measure's offset.
    for s in sections:
        try:
            t_sec = float(s.get("start_sec") or 0.0)
            label = (s.get("label") or s.get("ko_label") or "").strip()
        except Exception:
            continue
        if not label:
            continue
        target_offset = t_sec * qps
        # Find measure whose offset is closest to (and ≤) the section start.
        nearest = measures[0]
        for m in measures:
            try:
                if float(m.offset) <= target_offset:
                    nearest = m
                else:
                    break
            except Exception:
                continue
        try:
            mark = expressions.RehearsalMark(label)
            nearest.insert(0, mark)
        except Exception:
            continue


def _attach_lyrics(score, lyrics_words: list[dict] | None, bpm: float) -> None:
    """Attach lyrics (word-level) to the closest note onset in each part.

    lyrics_words: [{ "word": str, "start_sec": float, "end_sec": float,
                     "confidence": float, optional "verse": int (1-based) }]
    """
    if not lyrics_words or bpm <= 0:
        return
    qps = bpm / 60.0
    try:
        from music21 import note as m21note
    except Exception:
        return

    # Collect all notes from all parts with their absolute offset (in quarter lengths).
    note_targets = []
    try:
        parts = list(score.parts) or [score]
    except AttributeError:
        parts = [score]
    for part in parts:
        for n in part.recurse().getElementsByClass(m21note.Note):
            try:
                note_targets.append((float(n.offset), n))
            except Exception:
                continue
    if not note_targets:
        return
    note_targets.sort(key=lambda t: t[0])

    # For each word, find the nearest note and append a lyric (multi-verse aware).
    import bisect
    offsets = [t[0] for t in note_targets]
    for w in lyrics_words:
        text = (w.get("word") or "").strip()
        if not text:
            continue
        verse = int(w.get("verse", 1))
        target_q = float(w.get("start_sec", 0.0)) * qps
        idx = bisect.bisect_left(offsets, target_q)
        candidates = []
        if idx < len(note_targets):
            candidates.append(note_targets[idx])
        if idx > 0:
            candidates.append(note_targets[idx - 1])
        if not candidates:
            continue
        best = min(candidates, key=lambda t: abs(t[0] - target_q))
        try:
            best[1].addLyric(text, lyricNumber=verse)
        except Exception:
            pass


def _attach_key_signature(score, key_name: str | None) -> None:
    """Insert a music21 ``KeySignature`` at offset 0 of every part.

    ``key_name`` examples: ``"C major"``, ``"F# minor"``. When the value
    is missing or unparseable we leave the score key-less (the renderer
    will show a blank key signature, which is correct for unknown keys).

    Why on every part: music21 only auto-propagates the key from the
    first part on insert; explicit insert on each part guarantees the
    key signature renders consistently across the grand staff / SATB /
    multi-part choir layouts.
    """
    if not key_name:
        return
    try:
        from music21 import key as m21_key
    except Exception:
        return
    parts = list(score.parts) if hasattr(score, "parts") else []
    if not parts:
        parts = [score]
    parts_norm = parts or []
    for part in parts_norm:
        try:
            ks = m21_key.Key(*key_name.strip().split(None, 1))
        except Exception:
            # Try just the tonic name (defaults to major).
            try:
                tonic = key_name.strip().split()[0]
                ks = m21_key.Key(tonic)
            except Exception:
                return
        try:
            # Insert at the very top of the part. music21 propagates the
            # key signature through every measure until the next change.
            part.insert(0.0, ks)
        except Exception:
            continue


def midi_to_musicxml(
    midi_path: Path,
    out_path: Path,
    stem_kind: str = "vocals",
    title: str = "",
    composer: str = "Re:Chord (AI transcription)",
    chord_events: list[dict] | None = None,
    bpm: float = 0.0,
    lyrics_words: list[dict] | None = None,
    notation_style: str = "",
    aux_cues: list[dict] | None = None,
    sections: list[dict] | None = None,
    time_signature: str | None = None,
    key_name: str | None = None,
) -> Path:
    """Convert MIDI to a clean MusicXML.

    notation_style: "" (auto from stem_kind) | "lead_sheet" | "grand_staff" |
                    "single_treble" | "single_bass" | "drum" |
                    "guitar_tab" | "bass_tab" | "choir_satb"

    key_name: optional ``"C major"`` / ``"F# minor"`` — emits the matching
    key signature on every part so accidentals stay readable.
    """
    from music21 import converter, instrument, metadata, stream, clef, layout
    import pretty_midi

    notation = notation_style or NOTATION_BY_STEM.get(stem_kind, "single_treble")
    is_lead_sheet = (notation == "lead_sheet")
    if is_lead_sheet:
        notation = "single_treble"

    # Specialised notations build their own Score and skip the generic
    # treble/grand-staff path entirely.
    if notation == "drum":
        score = _build_drum_score(midi_path, bpm)
        md = metadata.Metadata(); md.title = title or midi_path.stem; md.composer = composer
        score.metadata = md
        # Bar into measures so section markers / tempo / chord symbols
        # attach and survive export (they silently vanished otherwise).
        _ensure_measures(score)
        _attach_tempo_mark(score, bpm, time_signature)
        # Drums benefit from chord symbols + section marks too — the
        # drummer follows the harmonic form and needs to see intro/verse
        # /chorus boundaries to lock in dynamics. Key signature is
        # purely informational on a percussion clef but readers expect
        # to see it printed.
        _attach_key_signature(score, key_name)
        _attach_chord_symbols(score, chord_events, bpm)
        _attach_section_markers(score, sections, bpm)
        if aux_cues:
            from .aux_cues import attach_aux_cues_to_score
            attach_aux_cues_to_score(score, aux_cues)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        score.write("musicxml", fp=str(out_path))
        return out_path

    if notation in ("guitar_tab", "bass_tab"):
        tuning = GUITAR_TUNING_MIDI if notation == "guitar_tab" else BASS_TUNING_MIDI
        max_fret = GUITAR_MAX_FRET if notation == "guitar_tab" else BASS_MAX_FRET
        inst = "guitar" if notation == "guitar_tab" else "bass"
        score = _build_tab_score(midi_path, bpm, tuning, max_fret, inst)
        md = metadata.Metadata(); md.title = title or midi_path.stem; md.composer = composer
        score.metadata = md
        _ensure_measures(score)
        _attach_tempo_mark(score, bpm, time_signature)
        _attach_key_signature(score, key_name)
        # Chord symbols are very common on TABs — keep them.
        _attach_chord_symbols(score, chord_events, bpm)
        _attach_section_markers(score, sections, bpm)
        if aux_cues:
            from .aux_cues import attach_aux_cues_to_score
            attach_aux_cues_to_score(score, aux_cues)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        score.write("musicxml", fp=str(out_path))
        return out_path

    if notation == "choir_satb":
        score = _build_choir_satb_score(midi_path, bpm)
        md = metadata.Metadata(); md.title = title or midi_path.stem; md.composer = composer
        score.metadata = md
        _ensure_measures(score)
        _attach_tempo_mark(score, bpm, time_signature)
        _attach_key_signature(score, key_name)
        _attach_chord_symbols(score, chord_events, bpm)
        _attach_lyrics(score, lyrics_words, bpm)
        _attach_section_markers(score, sections, bpm)
        if aux_cues:
            from .aux_cues import attach_aux_cues_to_score
            attach_aux_cues_to_score(score, aux_cues)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        score.write("musicxml", fp=str(out_path))
        return out_path

    score = stream.Score()
    md = metadata.Metadata()
    md.title = title or midi_path.stem
    md.composer = composer
    score.metadata = md

    if notation == "grand_staff":
        # Re-parse via pretty_midi so we can route notes by pitch.
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        all_notes = []
        for inst in pm.instruments:
            for n in inst.notes:
                all_notes.append(n)

        # Split by pitch.
        treble_pm = pretty_midi.PrettyMIDI(initial_tempo=pm.estimate_tempo() or 120.0)
        bass_pm = pretty_midi.PrettyMIDI(initial_tempo=pm.estimate_tempo() or 120.0)
        ti = pretty_midi.Instrument(program=0)   # Acoustic Grand Piano
        bi = pretty_midi.Instrument(program=0)
        for n in all_notes:
            (ti if n.pitch >= C4_MIDI else bi).notes.append(n)
        treble_pm.instruments.append(ti)
        bass_pm.instruments.append(bi)

        # Render both halves to temp midis -> music21 streams -> attach to score.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t_mid = Path(tmp) / "treble.mid"
            b_mid = Path(tmp) / "bass.mid"
            treble_pm.write(str(t_mid))
            bass_pm.write(str(b_mid))

            t_stream = converter.parse(str(t_mid))
            b_stream = converter.parse(str(b_mid))

        # Flatten into a single Part each (music21 wraps midi in a Score, so
        # take its parts and re-clef). The instrument that the MIDI parser
        # guessed (basic_pitch often emits Electric Piano / program 4) has
        # to be *removed* first — ``part.insert(0, Piano())`` only prepends,
        # so without removing the existing one the MIDI guess wins the label.
        # We also label the two staves identically so the engraver groups
        # them into a single grand-staff system instead of two separate
        # instruments.
        def flatten_first_part(s, clef_obj, label: str, abbrev: str):
            try:
                part = s.parts[0]
            except IndexError:
                part = s
            for existing in list(part.getElementsByClass(instrument.Instrument)):
                part.remove(existing)
            piano = instrument.Piano()
            piano.partName = label
            piano.partAbbreviation = abbrev
            part.insert(0, piano)
            part.insert(0, clef_obj)
            return part

        # Stem name drives the visible label (e.g. "Instrumental", "Piano",
        # "Other") so the score header matches what the user asked for —
        # not whatever GM program basic_pitch happened to emit.
        label = stem_kind.replace("_", " ").title()
        abbrev = (label[:5] + ".") if len(label) > 5 else label
        treble_part = flatten_first_part(t_stream, clef.TrebleClef(), label, abbrev)
        bass_part = flatten_first_part(b_stream, clef.BassClef(), label, abbrev)

        score.insert(0, treble_part)
        score.insert(0, bass_part)
        # Brace the two staves into a real grand-staff system. Without this
        # they render as two unrelated instruments and any empty bar on one
        # side collapses (which is what produced the "bass-only from m.4"
        # artefact users reported).
        score.insert(0, layout.StaffGroup(
            [treble_part, bass_part],
            name=label,
            abbreviation=abbrev,
            symbol="brace",
            barTogether=True,
        ))
    else:
        s = converter.parse(str(midi_path))
        try:
            part = s.parts[0]
        except IndexError:
            part = s
        # Pick the right single clef for the stem.
        if notation == "single_bass":
            part.insert(0, clef.BassClef())
        else:
            part.insert(0, clef.TrebleClef())
        score.insert(0, part)

    # Quantize lightly so basic-pitch's small onset jitter snaps to 16ths.
    try:
        score.quantize(quarterLengthDivisors=(4, 3), processOffsets=True,
                       processDurations=True, inPlace=True)
    except Exception:
        pass

    # Tempo mark at the top of measure 1 — ♩ = BPM.
    _attach_tempo_mark(score, bpm, time_signature)
    # Key signature (e.g. "G major" → 1 sharp) — accidental count is
    # what readers expect at the top of the line.
    _attach_key_signature(score, key_name)

    # Attach chord symbols (C, Am, G7, ...) above the top staff.
    _attach_chord_symbols(score, chord_events, bpm)

    # Attach per-word lyrics under the notes (lead sheet workflow).
    _attach_lyrics(score, lyrics_words, bpm)

    # Section rehearsal marks (intro / verse / chorus / bridge / …).
    _attach_section_markers(score, sections, bpm)

    # Attach AUX patch cues ("AUX · 오르간", "AUX · 패드", ...) per measure.
    if aux_cues:
        from .aux_cues import attach_aux_cues_to_score
        attach_aux_cues_to_score(score, aux_cues)

    # ── Dynamics + articulation auto-attach ─────────────────────────
    # The MIDI velocity carries musical loudness intent; without
    # mapping it to standard dynamic markings (ppp..fff) the engraved
    # score reads as a flat MIDI dump. We also infer articulation from
    # note duration: extremely short notes become staccato, sustained
    # legato runs become slurred.
    try:
        _attach_dynamics_and_articulation(score)
    except Exception:
        # Best-effort; never block score generation.
        pass

    out_path.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=str(out_path))
    return out_path


def _attach_dynamics_and_articulation(score) -> dict:
    """Auto-attach dynamics + articulation markings derived from MIDI.

    Dynamics
        We compute the mean velocity of every *measure*, classify it
        against the standard 6-step ladder (ppp/pp/p/mp/mf/f/ff/fff),
        and only emit a marking when the level *changes* from the
        previous measure. Continuous dynamic markings clutter the score
        — engravers traditionally write a marking once and let it
        carry until the next change.

    Articulation
        * Staccato — note whose actual duration is < 25 % of its
          notated quarterLength. Indicates a clipped, separated attack.
        * Tenuto   — note whose duration is > 95 % of its notated
          quarterLength AND > 1 quarter long. Indicates sustained,
          full-value playing.
        * Accent   — note whose velocity is > 1.3 × the running
          measure-mean. Marks per-note emphasis on top of the bar-level
          dynamic.

    Returns a stats dict {"measures_marked": ..., "notes_articulated":
    ...} so callers (and tests) can pin the behaviour.
    """
    from music21 import dynamics as m21_dyn, articulations, note as m21_note

    # 6-step velocity ladder (1..127 → marking name).
    # Tuned so 80 mid-range = mf, our basic-pitch default.
    LADDER = [
        (33,  "ppp"),
        (45,  "pp"),
        (60,  "p"),
        (75,  "mp"),
        (90,  "mf"),
        (105, "f"),
        (118, "ff"),
        (127, "fff"),
    ]

    def _classify(v: float) -> str:
        for thresh, label in LADDER:
            if v <= thresh:
                return label
        return "fff"

    stats = {"measures_marked": 0, "notes_articulated": 0}
    for part in (score.parts if hasattr(score, "parts") and len(score.parts)
                  else [score]):
        last_marking: str | None = None
        for m in part.getElementsByClass("Measure"):
            # Collect velocities of every non-rest note in this measure.
            vels: list[int] = []
            for n in m.recurse().notes:
                v = None
                if isinstance(n, m21_note.Note):
                    v = getattr(n.volume, "velocity", None)
                elif n.isChord:
                    v = getattr(n.volume, "velocity", None)
                if v is not None and v > 0:
                    vels.append(int(v))
            if not vels:
                continue

            mean_v = sum(vels) / len(vels)
            marking = _classify(mean_v)

            # Bar-level dynamic — emit only on change.
            if marking != last_marking:
                try:
                    m.insert(0.0, m21_dyn.Dynamic(marking))
                    stats["measures_marked"] += 1
                    last_marking = marking
                except Exception:
                    pass

            # Per-note articulation.
            for n in m.recurse().notes:
                ql = float(getattr(n.duration, "quarterLength", 0.0) or 0.0)
                if ql <= 0:
                    continue
                # Staccato — very short relative to its written length.
                # basic-pitch writes the *acoustic* duration as quarterLength,
                # so we compare to the quantization grid: notes shorter
                # than a 16th (0.25 quarter) with low residual silence get
                # the dot.
                if ql < 0.25:
                    try:
                        n.articulations.append(articulations.Staccato())
                        stats["notes_articulated"] += 1
                    except Exception:
                        pass
                # Tenuto — long sustained notes (≥ quarter).
                elif ql >= 1.0:
                    try:
                        n.articulations.append(articulations.Tenuto())
                        stats["notes_articulated"] += 1
                    except Exception:
                        pass

                # Accent — per-note velocity well above the bar mean.
                try:
                    vn = (getattr(n.volume, "velocity", None)
                          if isinstance(n, m21_note.Note) or n.isChord else None)
                except Exception:
                    vn = None
                if vn is not None and mean_v > 0 and vn > 1.3 * mean_v:
                    try:
                        n.articulations.append(articulations.Accent())
                        stats["notes_articulated"] += 1
                    except Exception:
                        pass

    return stats


# ----------------------------------------------------------------------------
# MusicXML -> per-page SVG (Verovio) -> single PDF (svglib + reportlab).
# ----------------------------------------------------------------------------

# A4 portrait at ~150 DPI in points: 595 x 842 ~~ pageWidth/Height for Verovio
# but Verovio units are in *0.01mm* when scale is set; default scale=40 gives
# nicer print output. Roughly 2480x3508 px equivalents at 300 DPI.
_PAGE_WIDTH = 2100
_PAGE_HEIGHT = 2970   # ~A4 portrait at this scale


def render_pages(
    musicxml_path: Path,
    out_dir: Path,
    base_name: str,
) -> list[Path]:
    """Render Verovio multi-page SVGs to <base>_p1.svg, _p2.svg, …"""
    import verovio
    tk = verovio.toolkit()
    tk.setOptions({
        "scale": 40,
        "pageWidth": _PAGE_WIDTH,
        "pageHeight": _PAGE_HEIGHT,
        "pageMarginTop": 100,
        "pageMarginBottom": 100,
        "pageMarginLeft": 100,
        "pageMarginRight": 100,
        "adjustPageHeight": False,
        "breaks": "auto",
        "spacingSystem": 12,
        "spacingStaff": 10,
        "footer": "always",
        "header": "auto",
        # Number every measure (Verovio 4.x option name; the old
        # "measureNumber":"system" key is unsupported and was silently
        # ignored, so measures were never numbered).
        "mnumInterval": 1,
        "lyricSize": 4.5,                  # legible Korean lyrics
    })
    if not tk.loadFile(str(musicxml_path)):
        return []
    n_pages = tk.getPageCount()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(1, n_pages + 1):
        svg = _sanitize_svg_colors(tk.renderToSVG(i))
        p = out_dir / f"{base_name}_p{i}.svg"
        p.write_text(svg, encoding="utf-8")
        paths.append(p)
    return paths


_BAD_HEX_RE = None


def _sanitize_svg_colors(svg: str) -> str:
    """Fix malformed hex colours in Verovio's SVG output.

    Verovio occasionally emits a 5-digit hex (e.g. ``#00000``) which
    svglib can't parse ("Can't handle color: #00000"). We pad such
    values to a valid 6-digit form so the svglib→PDF conversion is
    clean. Valid 3/6-digit colours pass through untouched.
    """
    global _BAD_HEX_RE
    if _BAD_HEX_RE is None:
        import re as _re
        # Match #hex with 1,2,4, or 5 digits (the invalid lengths).
        _BAD_HEX_RE = _re.compile(r"#([0-9a-fA-F]{1,5})(?![0-9a-fA-F])")

    def _fix(m):
        digits = m.group(1)
        if len(digits) in (3, 6):
            return m.group(0)            # already valid
        if len(digits) == 5:
            # Most common case: a dropped leading zero. Pad to 6.
            return "#0" + digits
        # 1, 2, or 4 digits → pad right to the nearest valid length.
        padded = (digits + "000000")[:6]
        return "#" + padded

    try:
        return _BAD_HEX_RE.sub(_fix, svg)
    except Exception:
        return svg


def svgs_to_pdf(
    svg_paths: list[Path],
    pdf_path: Path,
    *,
    title: str | None = None,
    copyright_line: str | None = None,
) -> Path | None:
    """Stitch the per-page SVGs into a single PDF.

    Each page receives a footer with the song title (left) and
    ``page N / M`` (right). When ``copyright_line`` is provided, it
    replaces the default "© <year> <title> · 자동 전사 by Re:Chord".
    Footer is drawn AFTER the score so it sits on top — required when
    the staff extends close to the page bottom.
    """
    if not svg_paths:
        return None
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.colors import HexColor
    except Exception:
        return None

    import datetime as _dt
    year = _dt.date.today().year
    title_text = (title or "").strip() or "Untitled"
    footer_left = (copyright_line or f"© {year} {title_text} · 자동 전사 by Re:Chord")
    # Truncate over-long titles so the footer doesn't collide with the page count.
    if len(footer_left) > 80:
        footer_left = footer_left[:77] + "…"

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    page_w, page_h = A4
    total = len(svg_paths)
    grey = HexColor("#777777")
    written = 0
    for idx, sp in enumerate(svg_paths, start=1):
        try:
            drawing = svg2rlg(str(sp))
            if drawing is None:
                continue
            scale = min(page_w / drawing.width, page_h / drawing.height) * 0.95
            drawing.width *= scale
            drawing.height *= scale
            drawing.scale(scale, scale)
            x = (page_w - drawing.width) / 2
            y = (page_h - drawing.height) / 2
            renderPDF.draw(drawing, c, x, y)

            # Footer — 14mm in from the edge, ~9pt grey.
            c.setFillColor(grey)
            c.setFont("Helvetica", 9)
            margin_mm = 14
            margin_pt = margin_mm * 2.83465        # mm → pt
            c.drawString(margin_pt, margin_pt, footer_left)
            page_str = f"page {idx} / {total}"
            text_w = c.stringWidth(page_str, "Helvetica", 9)
            c.drawString(page_w - margin_pt - text_w, margin_pt, page_str)

            c.showPage()
            written += 1
        except Exception:
            continue
    if written == 0:
        return None
    c.save()
    return pdf_path


def _extract_measure_timemap(
    score,
    bpm: float,
    *,
    downbeats_sec: list[float] | None = None,
) -> list[dict]:
    """Walk the score and return per-measure ``{measure, start_sec, end_sec}``.

    Two strategies:

    1. **Beat-grid (preferred)**: when ``downbeats_sec`` is supplied, every
       score measure is mapped directly to the *actual* downbeat timeline
       extracted by ``sections.detect_beat_grid``. This handles rubato,
       ritardando, and tempo shifts without drift because the grid was
       measured from the audio itself. Extra audio measures beyond the
       score length are still recorded (so the UI's playback cursor never
       runs out of map).

    2. **Constant-BPM fallback**: when no grid is supplied (or the grid
       has fewer downbeats than the score has measures), we fall back to
       the legacy ``measure_quarterLength × 60/BPM`` calculation. The UI
       should flag drift when this branch fires on a long song.

    Beats are quarter notes (music21 ``quarterLength``).
    """
    try:
        part = score.parts[0] if getattr(score, "parts", None) else score
        measures = list(part.getElementsByClass("Measure"))
        if not measures:
            return []

        # Strategy 1 — beat-grid alignment.
        if downbeats_sec and len(downbeats_sec) >= 2:
            out: list[dict] = []
            db = list(downbeats_sec)
            # Extend the grid by one more "downbeat" so the last measure
            # has an end-time: use the average gap of the last 4 bars.
            if len(db) >= 5:
                tail_gap = (db[-1] - db[-5]) / 4.0
            else:
                tail_gap = db[-1] - db[-2]
            end_extra = db[-1] + max(0.1, tail_gap)
            for i, _m in enumerate(measures, start=1):
                if i - 1 < len(db):
                    start = float(db[i - 1])
                else:
                    # Score has more measures than audio downbeats; project
                    # using the last observed gap.
                    extra = (i - len(db)) * tail_gap
                    start = float(db[-1] + extra)
                if i < len(db):
                    end = float(db[i])
                elif i == len(db):
                    end = float(end_extra)
                else:
                    extra = ((i + 1) - len(db)) * tail_gap
                    end = float(db[-1] + extra)
                out.append({"measure": i,
                            "start_sec": round(start, 3),
                            "end_sec": round(end, 3)})
            return out

        # Strategy 2 — constant-BPM fallback.
        bps = max(0.1, float(bpm or 120.0)) / 60.0
        sec_per_quarter = 1.0 / bps
        out2: list[dict] = []
        cursor = 0.0
        for i, m in enumerate(measures, start=1):
            ql = float(m.duration.quarterLength or 0.0)
            start = cursor
            end = cursor + ql * sec_per_quarter
            out2.append({"measure": i, "start_sec": round(start, 3),
                         "end_sec": round(end, 3)})
            cursor = end
        return out2
    except Exception:
        return []


def build_score(
    midi_path: Path,
    out_dir: Path,
    stem_kind: str = "vocals",
    title: str = "",
    write_svg: bool = True,
    write_pdf: bool = True,
    chord_events: list[dict] | None = None,
    bpm: float = 0.0,
    lyrics_words: list[dict] | None = None,
    notation_style: str = "",
    aux_cues: list[dict] | None = None,
    sections: list[dict] | None = None,
    time_signature: str | None = None,
    downbeats_sec: list[float] | None = None,
    key_name: str | None = None,
) -> ScoreResult:
    """High-level: MIDI → MusicXML → per-page SVG → PDF.

    ``chord_events``: chords.json payload → overlay chord symbols above staff.
    ``lyrics_words``: lyrics.json payload (with optional ``verse``) → lyrics under notes.
    ``aux_cues``: aux_cues.json payload → "AUX · 패치명" text above measure.
    ``notation_style``: "lead_sheet" forces melody + chords + lyrics. Default
                       picks lead_sheet for vocals/guitar, grand_staff for piano/other.
    """
    from music21 import converter

    suffix = notation_style or NOTATION_BY_STEM.get(stem_kind, "")
    name = f"{midi_path.stem}_{suffix}" if suffix else midi_path.stem
    musicxml_path = out_dir / f"{name}.musicxml"
    midi_to_musicxml(midi_path, musicxml_path,
                     stem_kind=stem_kind,
                     title=title or midi_path.stem,
                     chord_events=chord_events, bpm=bpm,
                     lyrics_words=lyrics_words,
                     notation_style=notation_style,
                     aux_cues=aux_cues,
                     sections=sections,
                     time_signature=time_signature,
                     key_name=key_name)

    svg_paths: list[Path] = []
    pdf_path: Path | None = None
    if write_svg:
        svg_paths = render_pages(musicxml_path, out_dir, name)
    if write_pdf and svg_paths:
        pdf_path = svgs_to_pdf(svg_paths, out_dir / f"{name}.pdf", title=title)

    # Quick stats for the report.
    score = converter.parse(str(musicxml_path))
    parts = len(getattr(score, "parts", [score]))
    measures = 0
    try:
        measures = len(score.parts[0].getElementsByClass("Measure"))
    except Exception:
        pass

    # Per-measure timemap so the frontend can highlight the current measure
    # in sync with audio playback. When ``downbeats_sec`` is provided we
    # align each measure to the detected downbeat grid (rubato-safe);
    # otherwise we fall back to a constant-BPM approximation.
    timemap_path: Path | None = None
    try:
        tm = _extract_measure_timemap(score, bpm or 120.0,
                                      downbeats_sec=downbeats_sec)
        if tm:
            import json as _json
            timemap_path = out_dir / f"{name}_timemap.json"
            timemap_path.write_text(
                _json.dumps({"bpm": bpm or 120.0, "measures": tm}, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception:
        timemap_path = None

    return ScoreResult(
        musicxml_path=musicxml_path,
        svg_paths=svg_paths,
        pdf_path=pdf_path,
        title=title or midi_path.stem,
        parts=parts,
        measures=measures,
        pages=len(svg_paths),
        timemap_path=timemap_path,
    )
