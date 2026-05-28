/**
 * Per-instrumentalist view roles for the Performance / Practice screens.
 *
 * A "role" defines which UI surfaces are visible and which artifacts the
 * playback engine prefers. Same job, different on-stage view per musician.
 *
 *   - vocalist  : lyrics + melody + monitor cues. Hides chord ribbon.
 *   - keys      : chord chart + AUX patch cues + sections. Hides lyrics.
 *   - drummer   : click track + sections only. Big BPM + bar counter.
 *   - bassist   : root-only chord chart (slash notes) + sections.
 *   - guitarist : chord chart + capo hint + lyrics (if singing).
 *   - leader    : everything (current default — band-master view).
 */

import {
  Mic2 as VocalIcon,
  Piano as KeysIcon,
  Drum as DrumIcon,
  Music as BassIcon,
  Guitar as GuitarIcon,
  Crown as LeaderIcon,
} from "lucide-react";

// labelKey resolves via t("perform.role_*") at render time — keeps the
// ROLES list a static module export while still tracking the active locale.
export const ROLES = [
  {
    id: "leader",
    labelKey: "perform.role_leader",
    icon: LeaderIcon,
    show: { chords: true, lyrics: true, sections: true, aux: true, notes: true, big_bpm: false, bar_counter: false, root_only: false },
    audio: "instrumental_final",   // band-master uses the MR
  },
  {
    id: "vocalist",
    labelKey: "perform.role_vocalist",
    icon: VocalIcon,
    show: { chords: false, lyrics: true, sections: true, aux: false, notes: true, big_bpm: false, bar_counter: false, root_only: false },
    audio: "instrumental_final",
  },
  {
    id: "keys",
    labelKey: "perform.role_keys",
    icon: KeysIcon,
    show: { chords: true, lyrics: false, sections: true, aux: true, notes: true, big_bpm: false, bar_counter: false, root_only: false },
    audio: "instrumental_final",
  },
  {
    id: "drummer",
    labelKey: "perform.role_drummer",
    icon: DrumIcon,
    show: { chords: false, lyrics: false, sections: true, aux: false, notes: true, big_bpm: true, bar_counter: true, root_only: false },
    audio: "monitor_track",         // click + cues if available
  },
  {
    id: "bassist",
    labelKey: "perform.role_bassist",
    icon: BassIcon,
    show: { chords: true, lyrics: false, sections: true, aux: false, notes: true, big_bpm: false, bar_counter: false, root_only: true },
    audio: "instrumental_final",
  },
  {
    id: "guitarist",
    labelKey: "perform.role_guitarist",
    icon: GuitarIcon,
    show: { chords: true, lyrics: true, sections: true, aux: false, notes: true, big_bpm: false, bar_counter: false, root_only: false },
    audio: "instrumental_final",
  },
];

export const ROLE_BY_ID = Object.fromEntries(ROLES.map((r) => [r.id, r]));

/** Strip a chord to its root only (for bass slash-style reading).
 *  C, Am, F/A → C, A, A   (root of the bass, not the chord)
 *  Used when role.show.root_only is true.
 */
export function rootOnly(label) {
  if (!label || label === "N" || label === "?") return label;
  // If there's a slash bass, that's what the bassist plays.
  if (label.includes("/")) {
    const bass = label.split("/")[1].trim();
    const m = /^([A-G][#b]?)/.exec(bass);
    if (m) return m[1];
  }
  const m = /^([A-G][#b]?)/.exec(label);
  return m ? m[1] : label;
}
