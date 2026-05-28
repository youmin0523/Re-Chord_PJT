/**
 * Transposition helpers for band-master / multi-instrument use.
 *
 * Two concepts in play:
 *   (1) Concert-pitch shift: the actual semitone change applied to audio
 *       playback (uses backend transform). This is what every musician
 *       hears in their ears.
 *
 *   (2) Reading transposition: for transposing instruments (Bb trumpet,
 *       Eb alto sax), the written chord on their chart is shifted from
 *       concert pitch so they can finger their normal positions. This is
 *       a display-only label change — does NOT touch audio.
 *
 * Common transposing instruments + their concert→written shift in semitones:
 *
 *   Concert (piano, guitar, vocals, bass, etc.)  →  0
 *   Bb trumpet / clarinet / tenor sax            →  +2  (read 2 semitones higher)
 *   Eb alto sax / baritone sax                   →  +9  (or -3 + octave)
 *   F french horn                                →  +7
 *   Bass clef trombone (concert)                 →  0
 *   Capo guitar (capo on N)                      → −N (read N semitones lower)
 */

export const PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const PITCH_CLASSES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

export const INSTRUMENT_PRESETS = [
  { id: "concert",       label: "Concert (피아노/보컬/기타)",  shift: 0,  useFlats: false },
  { id: "bb_trumpet",    label: "Bb 트럼펫 / 클라리넷 / 테너 색소폰", shift: +2, useFlats: true  },
  { id: "eb_alto_sax",   label: "Eb 알토 / 바리톤 색소폰",     shift: +9, useFlats: true  },
  { id: "f_horn",        label: "F 호른",                       shift: +7, useFlats: false },
  { id: "capo_2",        label: "기타 카포 2",                  shift: -2, useFlats: false },
  { id: "capo_3",        label: "기타 카포 3",                  shift: -3, useFlats: true  },
  { id: "capo_4",        label: "기타 카포 4",                  shift: -4, useFlats: false },
  { id: "capo_5",        label: "기타 카포 5",                  shift: -5, useFlats: true  },
  { id: "bass_octave",   label: "베이스 1 옥타브 위",            shift: +12, useFlats: false },
];

/**
 * Parse a chord label like "F#m7", "Bbmaj7", "C/E" into:
 *   { root, suffix, bass }
 * Returns null if it doesn't look like a chord (e.g. "N").
 */
export function parseChord(label) {
  if (!label || label === "N" || label === "?") return null;
  const m = /^([A-G])([#b])?(.*?)(?:\/([A-G])([#b])?)?$/.exec(label.trim());
  if (!m) return null;
  return {
    root: m[1] + (m[2] || ""),
    suffix: m[3] || "",
    bass: m[4] ? m[4] + (m[5] || "") : null,
  };
}

/** Index in PITCH_CLASSES, accepting both sharps and flats. */
function pitchIndex(name) {
  const idx = PITCH_CLASSES.indexOf(name);
  if (idx >= 0) return idx;
  // try flats
  const flat = PITCH_CLASSES_FLAT.indexOf(name);
  if (flat >= 0) return flat;
  return -1;
}

/** Transpose a chord label by N semitones. Choose flats/sharps explicitly. */
export function transposeChord(label, semitones, useFlats = false) {
  const parsed = parseChord(label);
  if (!parsed) return label;
  const family = useFlats ? PITCH_CLASSES_FLAT : PITCH_CLASSES;
  const rIdx = pitchIndex(parsed.root);
  if (rIdx < 0) return label;
  const newRoot = family[(rIdx + semitones + 1200) % 12];
  let bass = "";
  if (parsed.bass) {
    const bIdx = pitchIndex(parsed.bass);
    if (bIdx >= 0) bass = "/" + family[(bIdx + semitones + 1200) % 12];
  }
  return newRoot + parsed.suffix + bass;
}

/** Transpose every chord event in a chords.json payload. */
export function transposeChordEvents(events, semitones, useFlats = false) {
  return (events || []).map((ev) => ({
    ...ev,
    label: transposeChord(ev.label, semitones, useFlats),
  }));
}

/** Transpose a key label like "C major" or "F# minor". */
export function transposeKey(keyName, semitones, useFlats = false) {
  if (!keyName) return keyName;
  const parts = keyName.split(/\s+/);
  if (parts.length < 2) return keyName;
  const newRoot = transposeChord(parts[0], semitones, useFlats);
  return `${newRoot} ${parts.slice(1).join(" ")}`;
}

// ── Key distance (for setlist sequencing) ─────────────────────────────────

/**
 * Shortest semitone distance between two keys' tonics, ignoring mode.
 * Returns a value in [-6, +6] — positive means "second key is higher".
 *
 *   keyDistance("C major", "D major")   →  +2
 *   keyDistance("C major", "B major")   →  -1
 *   keyDistance("F# major", "C major")  →  -6 (or +6 — equally distant)
 *
 * Use cases: warning a setlist when adjacent songs are >5 semitones apart
 * (jarring for the audience / hard for the band to retune mid-set), or
 * scoring how "flowing" a setlist transition is.
 */
export function keyDistance(fromKey, toKey) {
  if (!fromKey || !toKey) return null;
  const a = (fromKey.split(/\s+/)[0] || "").trim();
  const b = (toKey.split(/\s+/)[0] || "").trim();
  const aIdx = pitchIndex(a);
  const bIdx = pitchIndex(b);
  if (aIdx < 0 || bIdx < 0) return null;
  let diff = (bIdx - aIdx) % 12;
  if (diff > 6) diff -= 12;
  if (diff < -6) diff += 12;
  return diff;
}

// ── Vocal-range hints ─────────────────────────────────────────────────────

// Comfortable singing ranges for average untrained voices. Numbers are MIDI
// pitches (C4=60). Source: choral pedagogy averages — wide enough that most
// adults can hit either end without strain.
//
//   mixed     — typical mixed congregation / general crowd singalong (D3-D5)
//   alto/men  — wider but lower; useful for hymn baritone reading
//   sop/wmn   — wider but higher
//   trained   — solo lead vocalist (wider both ways)
export const VOCAL_RANGES = {
  mixed:   { low: 50, high: 74, label: "혼성 (보통 음역)" },     // D3–D5
  alto:    { low: 47, high: 69, label: "남성 평균" },             // B2–A4
  soprano: { low: 55, high: 77, label: "여성 평균" },             // G3–F5
  trained: { low: 43, high: 81, label: "훈련된 솔로" },           // G2–A5
};

/** Convert "C4" / "F#3" / "Bb2" to a MIDI integer (C4 = 60). */
export function noteToMidi(name) {
  if (!name) return null;
  const m = /^([A-G])([#b]?)(-?\d+)$/.exec(name.trim());
  if (!m) return null;
  const baseIdx = pitchIndex(m[1] + m[2]);
  if (baseIdx < 0) return null;
  return baseIdx + (Number(m[3]) + 1) * 12;
}

/** Convert MIDI integer → "C4" style. */
export function midiToNote(midi, useFlats = false) {
  if (midi == null || Number.isNaN(midi)) return "";
  const family = useFlats ? PITCH_CLASSES_FLAT : PITCH_CLASSES;
  return `${family[(midi % 12 + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

/**
 * Assess whether a song's vocal melody fits a target audience's range
 * after applying a semitone shift. Given the song's lowest/highest melody
 * pitches (from analyze.py or transcribe.py), reports whether the shifted
 * range stays inside the chosen audience range.
 *
 *   assessVocalRange({lowMidi: 55, highMidi: 74}, +2, "mixed")
 *     → { ok: false, overflow: 2, advice: "최고음 2 반음 초과 (F#5)" }
 */
export function assessVocalRange(melody, semitones, audience = "mixed") {
  const r = VOCAL_RANGES[audience];
  if (!r || !melody || melody.lowMidi == null || melody.highMidi == null) return null;
  const lo = melody.lowMidi + semitones;
  const hi = melody.highMidi + semitones;
  const tooHigh = hi - r.high;
  const tooLow = r.low - lo;
  const overflow = Math.max(0, tooHigh, tooLow);
  const advice =
    tooHigh > 0 ? `최고음 ${tooHigh} 반음 초과 (${midiToNote(hi)})`
    : tooLow > 0 ? `최저음 ${tooLow} 반음 부족 (${midiToNote(lo)})`
    : `${midiToNote(lo)} – ${midiToNote(hi)} (적정)`;
  return { ok: overflow === 0, overflow, advice, lo, hi, range: r };
}

// ── Capo recommender ───────────────────────────────────────────────────────

/**
 * Guitarist-friendly open-chord keys (when reading chords for an open-shape
 * guitar). Each key fingers comfortably as common cowboy chords.
 */
const OPEN_FRIENDLY_KEYS = ["G", "C", "D", "E", "A", "Em", "Am", "Dm"];

/**
 * Suggest the optimal capo position for playing in a target key while
 * fingering an open-friendly shape.
 *
 * Given a target concert-pitch key, returns ``{capo, readKey, savings}``
 * where:
 *   capo     — fret number (0..7)
 *   readKey  — the shape the player actually fingers
 *   savings  — qualitative reason ("open shapes available", etc.)
 *
 * Example:
 *   recommendCapo("Eb major")   → { capo: 1, readKey: "D major", reason: ... }
 *   recommendCapo("Bb major")   → { capo: 3, readKey: "G major", reason: ... }
 *   recommendCapo("F# major")   → { capo: 2, readKey: "E major", reason: ... }
 */
export function recommendCapo(targetKeyName, { maxFret = 7 } = {}) {
  if (!targetKeyName) return null;
  const parts = targetKeyName.split(/\s+/);
  const root = parts[0];
  const mode = parts[1] || "major";
  const isMinor = /^min/i.test(mode);

  const rIdx = PITCH_CLASSES.indexOf(root) >= 0
    ? PITCH_CLASSES.indexOf(root)
    : PITCH_CLASSES_FLAT.indexOf(root);
  if (rIdx < 0) return null;

  // For every capo position 0..maxFret, the player fingers the key whose root
  // is (target - capo) semitones, in the same mode.
  const candidates = [];
  for (let capo = 0; capo <= maxFret; capo += 1) {
    const fingerIdx = (rIdx - capo + 1200) % 12;
    const fingerRoot = PITCH_CLASSES[fingerIdx];
    const shape = isMinor ? `${fingerRoot}m` : fingerRoot;
    const friendly = OPEN_FRIENDLY_KEYS.includes(shape) || OPEN_FRIENDLY_KEYS.includes(fingerRoot);
    candidates.push({
      capo,
      readKey: `${fingerRoot} ${isMinor ? "minor" : "major"}`,
      shape,
      friendly,
    });
  }

  // Prefer the lowest capo position that gives an open-friendly shape.
  const best = candidates.find((c) => c.friendly) || candidates[0];
  return {
    capo: best.capo,
    readKey: best.readKey,
    shape: best.shape,
    reason: best.friendly
      ? `${best.shape} 모양 — 개방 코드 사용 가능`
      : `${best.shape} 모양 — 개방 코드는 어렵지만 가장 가까운 키`,
  };
}
