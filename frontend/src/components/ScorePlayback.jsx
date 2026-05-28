import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Play, Pause, SkipBack, Volume2 } from "lucide-react";
import { artifactUrl } from "@/lib/api";
import { formatDuration } from "@/lib/utils";

/**
 * Score-aware audio playback overlay.
 *
 * Renders a thin transport bar above a Score component and uses the
 * track's duration to highlight the "current" score page (which the
 * caller renders separately). Page-mapping is linear by default
 * (currentTime / duration → page index); when ``measureTimes`` is
 * provided we instead map measure-by-measure so the highlight tracks
 * the actual notes.
 *
 *   <ScorePlayback
 *      job={job}
 *      pageCount={pageCount}
 *      onPageChange={setPage}      // current page index (0-based)
 *      onMeasureChange={...}        // current measure index (1-based)
 *   />
 */
export function ScorePlayback({
  job,
  pageCount,
  measureTimes = null,
  onPageChange,
  onMeasureChange,
}) {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.85);

  const src = useMemo(() => artifactUrl(job.id, "instrumental_final"), [job.id]);

  // Linear page-mapping fallback when measureTimes aren't available.
  useEffect(() => {
    if (!duration || !pageCount) return;
    if (measureTimes && measureTimes.length) {
      // Find which measure we're in, then derive page from that.
      let m = 0;
      for (let i = 0; i < measureTimes.length; i += 1) {
        if (measureTimes[i] <= position) m = i;
        else break;
      }
      onMeasureChange?.(m + 1);
      // Distribute measures evenly across pages.
      const perPage = Math.max(1, Math.ceil(measureTimes.length / pageCount));
      onPageChange?.(Math.min(pageCount - 1, Math.floor(m / perPage)));
    } else {
      const idx = Math.min(pageCount - 1, Math.floor((position / duration) * pageCount));
      onPageChange?.(Math.max(0, idx));
    }
  }, [position, duration, pageCount, measureTimes, onPageChange, onMeasureChange]);

  const toggle = () => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) { el.play(); setPlaying(true); }
    else { el.pause(); setPlaying(false); }
  };
  const reset = () => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = 0;
    el.play(); setPlaying(true);
  };
  const seek = (t) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = Math.max(0, Math.min(duration, t));
  };

  // Volume sync.
  useEffect(() => {
    const el = audioRef.current;
    if (el) el.volume = volume;
  }, [volume]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl bg-white/[0.03] ring-1 ring-white/10 p-3 flex items-center gap-3"
    >
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onTimeUpdate={(e) => setPosition(e.target.currentTime || 0)}
        onLoadedMetadata={(e) => setDuration(e.target.duration || 0)}
        onEnded={() => setPlaying(false)}
      />
      <button
        type="button"
        onClick={reset}
        className="inline-flex items-center justify-center size-9 rounded-full bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
        aria-label="처음부터"
        title="처음부터 (Home)"
      >
        <SkipBack className="size-4" />
      </button>
      <button
        type="button"
        onClick={toggle}
        className="inline-flex items-center justify-center size-11 rounded-full bg-gradient-to-br from-violet to-magenta text-white shadow-[0_8px_22px_-12px_rgba(139,92,246,0.6)]"
        aria-label={playing ? "일시정지" : "재생"}
      >
        {playing ? <Pause className="size-4" /> : <Play className="size-4 ml-0.5" />}
      </button>
      <input
        type="range"
        min={0}
        max={Math.max(duration, 0.01)}
        step={0.01}
        value={Math.min(position, duration || 0)}
        onChange={(e) => seek(Number(e.target.value))}
        className="flex-1 accent-violet"
        aria-label="재생 위치"
      />
      <span className="mono text-[11px] text-fg-muted shrink-0">
        {formatDuration(position)} / {formatDuration(duration)}
      </span>
      <div className="hidden sm:flex items-center gap-1.5 shrink-0">
        <Volume2 className="size-3.5 text-fg-muted" />
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
          className="w-20 accent-violet"
          aria-label="볼륨"
        />
      </div>
    </motion.div>
  );
}
