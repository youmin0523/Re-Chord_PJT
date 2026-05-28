/**
 * Stage-weighted ETA tracker for long-running jobs.
 *
 * Backend publishes events {stage, progress, ts}. We learn typical durations
 * per stage as we observe them, then project remaining time as a weighted sum
 * of (stages not yet started) × (typical duration).
 *
 * Returns { elapsedMs, remainingMs, etaText } updated on every event push.
 */

import { useEffect, useMemo, useRef, useState } from "react";

// Empirical baselines (seconds) for a 4-minute song on RTX 5070-class GPU.
// These get refined by observed event timestamps during the run.
const DEFAULTS = {
  ingest:    8,
  decode:    4,
  separate: 90,
  ensemble:  6,
  karaoke:  12,
  analyze:   8,
  transform: 6,
  lyrics:   18,
  score:    14,
  monitor:   6,
  encode:    4,
};

const STAGE_ORDER = [
  "ingest", "decode", "separate", "ensemble", "karaoke",
  "analyze", "transform", "lyrics", "monitor", "score", "encode",
];

function fmtMs(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return "0초";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}분 ${r}초` : `${m}분`;
}

export function useEta(job, logs) {
  const startRef = useRef(null);
  const stageStartRef = useRef({}); // stage -> ms
  const stageDurRef = useRef({});   // stage -> observed ms (final)
  const [tick, setTick] = useState(0);

  // Drive a low-frequency re-render so elapsed/remaining update once per second.
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return undefined;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [job?.status]);

  // Ingest events: mark start of stages, infer durations as we transition.
  useEffect(() => {
    if (!logs?.length) return;
    if (startRef.current == null) startRef.current = Date.now();
    let prev = null;
    for (const ev of logs) {
      if (ev.type === "ping") continue;
      const stage = ev.stage;
      if (!stage) continue;
      if (!(stage in stageStartRef.current)) {
        stageStartRef.current[stage] = Date.now();
      }
      if (prev && prev.stage && prev.stage !== stage) {
        // A stage transition — finalise prev duration.
        const s = stageStartRef.current[prev.stage];
        if (s) stageDurRef.current[prev.stage] = Date.now() - s;
      }
      prev = ev;
    }
  }, [logs]);

  return useMemo(() => {
    const start = startRef.current ?? Date.now();
    const elapsedMs = Date.now() - start;
    const currentStage = job?.stage;
    const progress = job?.progress ?? 0;

    // Sum of "remaining" stages including current.
    const seenDurs = stageDurRef.current;
    const inferRemaining = () => {
      // Find the index of the current stage in the canonical order.
      const idx = currentStage ? STAGE_ORDER.indexOf(currentStage) : -1;
      if (idx < 0) {
        // unknown stage — fall back to linear extrapolation from progress
        if (progress > 0.02) return (elapsedMs / progress) * (1 - progress);
        return 60000;
      }
      let rem = 0;
      // Time left in the current stage: scale by stage progress estimate.
      const curStart = stageStartRef.current[currentStage] ?? start;
      const curElapsed = Math.max(0, Date.now() - curStart);
      const expCur = DEFAULTS[currentStage] != null ? DEFAULTS[currentStage] * 1000 : 30000;
      rem += Math.max(0, expCur - curElapsed);
      for (let i = idx + 1; i < STAGE_ORDER.length; i += 1) {
        const s = STAGE_ORDER[i];
        const seen = seenDurs[s];
        rem += seen ?? (DEFAULTS[s] ?? 10) * 1000;
      }
      return rem;
    };

    const remainingMs = job?.status === "done" ? 0
      : job?.status === "error" ? null
      : inferRemaining();

    return {
      elapsedMs,
      remainingMs,
      elapsedText: fmtMs(elapsedMs),
      remainingText: remainingMs == null ? "—" : fmtMs(remainingMs),
      etaText: remainingMs == null ? "—" : `남은 시간 ~${fmtMs(remainingMs)}`,
    };
  }, [job?.stage, job?.status, job?.progress, tick]);
}
