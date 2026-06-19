/**
 * Operational-impact (ROI) estimation — guest mode, localStorage.
 *
 * The FDE "정량적 성과 측정" step: turn raw usage into an *estimated* time
 * saved, so a worship team can see the tool's value week to week. Estimates
 * are deliberately transparent and conservative — every action carries an
 * explicit minutes-saved assumption (SAVINGS_MIN) the UI surfaces, never a
 * black-box number. This is an estimate, not a measurement; the card says so.
 *
 * We piggy-back on data we already keep, to avoid new tracking plumbing:
 *   - songs processed → useJobHistory items   (already in localStorage)
 *   - setlist songs    → useJobHistory setlists (already in localStorage)
 *   - key recommends   → the one action not otherwise logged (recorded here)
 */

const EVENTS_KEY = "rechord.usage.v1";
const MAX_EVENTS = 1000;
const DAY_MS = 86400000;

// Minutes saved per action — EXPLICIT, conservative assumptions, shown in the
// UI so the number is auditable rather than magic. Tune from real team feedback.
export const SAVINGS_MIN = {
  song_processed: 20,   // vs. hand-building an MR / hunting usable stems
  key_recommended: 5,   // vs. trial-and-error transposing by ear
  setlist_song: 3,      // vs. collating each song's chart/key/MR by hand
};

function read() {
  try {
    const raw = localStorage.getItem(EVENTS_KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v : [];
  } catch { return []; }
}

function write(events) {
  try {
    localStorage.setItem(EVENTS_KEY, JSON.stringify(events.slice(-MAX_EVENTS)));
  } catch { /* quota / private mode — silently ignore */ }
}

/** Log a key recommendation being applied — the one un-derivable action. */
export function recordKeyRecommended(at = Date.now()) {
  const events = read();
  events.push({ type: "key_recommended", at });
  write(events);
}

/** All logged usage events. */
export function getUsageEvents() { return read(); }

/** Wipe the usage log (used by "내 데이터 삭제" / tests). */
export function clearUsage() {
  try { localStorage.removeItem(EVENTS_KEY); } catch { /* ignore */ }
}

/**
 * Combine job history + logged events into an estimated impact summary for the
 * last ``sinceDays`` days. Pure — the caller passes the data in, so it's
 * trivially testable and free of localStorage in tests that don't want it.
 *
 * @param {{items?: Array, setlists?: Array}} history  useJobHistory shape
 * @param {Array<{type:string, at:number}>} events     getUsageEvents() output
 * @returns {{songs:number, setlistSongs:number, keyRecs:number,
 *            minutes:number, hours:number, sinceDays:number}}
 */
export function summarizeImpact(history, events, { sinceDays = 30, now = Date.now() } = {}) {
  const cutoff = now - sinceDays * DAY_MS;
  const items = Array.isArray(history?.items) ? history.items : [];
  const setlists = Array.isArray(history?.setlists) ? history.setlists : [];
  const evs = Array.isArray(events) ? events : [];

  const songs = items.filter((it) => (it.createdAt ?? 0) >= cutoff).length;
  const setlistSongs = setlists
    .filter((s) => (s.createdAt ?? 0) >= cutoff)
    .reduce((n, s) => n + (Array.isArray(s.jobIds) ? s.jobIds.length : 0), 0);
  const keyRecs = evs.filter(
    (e) => e.type === "key_recommended" && (e.at ?? 0) >= cutoff,
  ).length;

  const minutes =
    songs * SAVINGS_MIN.song_processed +
    keyRecs * SAVINGS_MIN.key_recommended +
    setlistSongs * SAVINGS_MIN.setlist_song;

  return {
    songs,
    setlistSongs,
    keyRecs,
    minutes,
    hours: Math.round((minutes / 60) * 10) / 10,
    sinceDays,
  };
}
