/**
 * Setlist progression analyzer — flags rough transitions between consecutive
 * songs in a setlist so the band-master can plan interludes / re-orderings.
 *
 * Three kinds of warnings:
 *   - key_jump   : root jumps > 6 semitones (or distant relative). Suggests
 *                  an interlude in a connecting key.
 *   - bpm_jump   : tempo change > 30% with no obvious modulation pad.
 *   - mode_swap  : major↔minor flip within 8 seconds. Often jarring.
 *
 * Each warning includes a recommendation string so the UI can render it
 * straight. The analyzer is pure (no I/O); the page fetches each job's
 * meta and feeds it in.
 */

import { PITCH_CLASSES, PITCH_CLASSES_FLAT } from "./transpose";

function pitchIndex(name) {
  const i = PITCH_CLASSES.indexOf(name);
  if (i >= 0) return i;
  const f = PITCH_CLASSES_FLAT.indexOf(name);
  return f >= 0 ? f : -1;
}

function semitoneDistance(rootA, rootB) {
  const a = pitchIndex(rootA);
  const b = pitchIndex(rootB);
  if (a < 0 || b < 0) return null;
  const d = (b - a + 1200) % 12;
  return d > 6 ? d - 12 : d;     // shortest signed distance
}

// Circle-of-fifths order: each step is a perfect fifth.
const FIFTHS_ORDER = ["C", "G", "D", "A", "E", "B", "F#", "C#", "G#", "D#", "A#", "F"];

/**
 * Circle-of-fifths distance — captures harmonic closeness better than
 * raw semitone distance for setlist flow. C→G = 1, C→F = 1 (other way),
 * C→F# = 6 (farthest).
 */
function fifthsDistance(rootA, rootB) {
  const a = FIFTHS_ORDER.indexOf(rootA);
  const b = FIFTHS_ORDER.indexOf(rootB);
  if (a < 0 || b < 0) return null;
  let d = Math.abs(a - b);
  if (d > 6) d = 12 - d;
  return d;
}

/** True when two keys are relative major/minor (e.g. C major ↔ A minor). */
function isRelative(a, b) {
  if (!a.key_root || !b.key_root || !a.key_mode || !b.key_mode) return false;
  if (a.key_mode === b.key_mode) return false;
  const ai = pitchIndex(a.key_root);
  const bi = pitchIndex(b.key_root);
  if (ai < 0 || bi < 0) return false;
  // major root + 9 semitones = relative minor's tonic (e.g. C → A).
  const expected = a.key_mode === "major" ? (ai + 9) % 12 : (ai + 3) % 12;
  return expected === bi;
}

function bridgeKey(rootA, rootB) {
  // Suggest a key half-way between two roots on the circle of fifths.
  const a = FIFTHS_ORDER.indexOf(rootA);
  const b = FIFTHS_ORDER.indexOf(rootB);
  if (a < 0 || b < 0) return null;
  // walk halfway around the shorter arc.
  let d = b - a;
  if (Math.abs(d) > 6) d = d > 0 ? d - 12 : d + 12;
  const midFifthsIdx = (a + Math.round(d / 2) + 12) % 12;
  return FIFTHS_ORDER[midFifthsIdx];
}

export { fifthsDistance, isRelative };

/**
 * @param {Array<{id:string, title:string, key_root?:string, key_mode?:string, bpm?:number}>} setlist
 * @returns {Array<{after_idx:number, kind:string, severity:'warn'|'info', message:string, recommendation:string}>}
 */
export function analyzeSetlist(setlist) {
  const warnings = [];
  for (let i = 0; i < setlist.length - 1; i += 1) {
    const a = setlist[i];
    const b = setlist[i + 1];

    // Key jump.
    if (a.key_root && b.key_root) {
      const d = semitoneDistance(a.key_root, b.key_root);
      const fifths = fifthsDistance(a.key_root, b.key_root);
      // Flag when chromatically distant AND not a relative-key flip.
      if (d != null && Math.abs(d) > 6 && !isRelative(a, b)) {
        const bridge = bridgeKey(a.key_root, b.key_root);
        warnings.push({
          after_idx: i,
          kind: "key_jump",
          severity: "warn",
          message: `${a.title} (${a.key_root}) → ${b.title} (${b.key_root}): ${Math.abs(d)} st · 5도권 거리 ${fifths}`,
          recommendation: bridge
            ? `중간 ${bridge} 키로 8마디 인터루드를 끼우거나 ${b.title}을 ${a.key_root}쪽 키로 이조해 보세요.`
            : "두 곡 사이에 짧은 인터루드를 권장합니다.",
        });
      } else if (isRelative(a, b)) {
        warnings.push({
          after_idx: i,
          kind: "relative_key",
          severity: "info",
          message: `${a.title} (${a.key_root} ${a.key_mode}) ↔ ${b.title} (${b.key_root} ${b.key_mode}): 관계조 — 자연스러운 흐름`,
          recommendation: "추가 인터루드 없이 바로 이어가도 무리 없습니다.",
        });
      }
      // Mode flip (major↔minor) on the same root.
      if (a.key_mode && b.key_mode && a.key_mode !== b.key_mode) {
        const sameRoot = a.key_root === b.key_root;
        if (sameRoot) {
          warnings.push({
            after_idx: i,
            kind: "mode_swap",
            severity: "info",
            message: `${a.title} (${a.key_root} ${a.key_mode}) → ${b.title} (${b.key_root} ${b.key_mode}): 같은 root에서 mode flip`,
            recommendation: "감정 전환이 강합니다. 8초+ 페달톤을 사이에 두면 자연스럽습니다.",
          });
        }
      }
    }

    // BPM jump.
    if (a.bpm && b.bpm) {
      const ratio = b.bpm / a.bpm;
      if (Math.abs(ratio - 1) > 0.3) {
        const direction = ratio > 1 ? "↑" : "↓";
        warnings.push({
          after_idx: i,
          kind: "bpm_jump",
          severity: "warn",
          message: `${a.title} ${a.bpm.toFixed(0)} BPM → ${b.title} ${b.bpm.toFixed(0)} BPM ${direction} (${Math.round((ratio - 1) * 100)}%)`,
          recommendation:
            ratio > 1
              ? "빠른 곡으로 전환되니 카운트인 8비트를 두는 게 좋습니다."
              : "느린 곡으로 전환되니 잔향 페이드를 길게 잡으세요.",
        });
      }
    }
  }
  return warnings;
}
