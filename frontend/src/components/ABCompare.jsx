import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Play, Pause, Volume2 } from "lucide-react";
import { artifactUrl } from "@/lib/api";
import { cn, formatDuration } from "@/lib/utils";
import { Tooltip } from "@/components/ui/Tooltip";

/**
 * A/B/C synced playback comparison.
 *
 *   <ABCompare job={job} />
 *
 * The single biggest trust event after vocal separation is "did it actually
 * work?" → this panel keeps three <audio> elements (source, instrumental,
 * vocals) locked to the same playhead. The user toggles which one is audible
 * with one click. Crossfading is browser-native (we just mute/unmute).
 *
 * Falls back gracefully when only one or two of the three tracks exist.
 */
// Static track config; label/sub resolve via t() at render time.
const TRACK_DEFS = [
  { key: "source",       artifact: "source",                                  labelKey: "ab.track_source_label", subKey: "ab.track_source_sub", accent: "violet" },
  { key: "instrumental", artifact: "instrumental_final", fallback: "instrumental", labelKey: "ab.track_inst_label",   subKey: "ab.track_inst_sub",   accent: "cyan" },
  { key: "vocals",       artifact: "vocals_final",       fallback: "vocals",        labelKey: "ab.track_voc_label",    subKey: "ab.track_voc_sub",    accent: "magenta" },
];

const ACCENT = {
  violet:  "ring-violet/40 bg-violet/15 text-violet",
  cyan:    "ring-cyan/40 bg-cyan/15 text-cyan",
  magenta: "ring-magenta/40 bg-magenta/15 text-magenta",
};

export function ABCompare({ job }) {
  const { t } = useTranslation();
  const tracks = TRACK_DEFS
    .map((d) => {
      const src = job.artifacts?.[d.artifact] ?? (d.fallback && job.artifacts?.[d.fallback]);
      if (!src) return null;
      // Pull through the streaming endpoint; "source" needs a special key.
      const url = artifactUrl(job.id, d.artifact);
      return { ...d, url, label: t(d.labelKey), sub: t(d.subKey) };
    })
    .filter(Boolean);

  const [active, setActive] = useState(tracks[1]?.key || tracks[0]?.key);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.85);
  const refs = useRef({});

  // Sync all <audio> elements to the same currentTime + play state.
  useEffect(() => {
    Object.values(refs.current).forEach((el) => {
      if (!el) return;
      el.volume = volume;
    });
  }, [volume, tracks.length]);

  const allPlay = () => {
    Object.values(refs.current).forEach((el) => {
      if (!el) return;
      // Keep all in sync — same position, all play, only one audible.
      el.play().catch(() => {});
    });
    setPlaying(true);
  };
  const allPause = () => {
    Object.values(refs.current).forEach((el) => el && el.pause());
    setPlaying(false);
  };
  const toggle = () => (playing ? allPause() : allPlay());

  // The "master" element (whichever is active) drives the progress meter.
  useEffect(() => {
    const master = refs.current[active];
    if (!master) return undefined;
    const onTime = () => setPosition(master.currentTime || 0);
    const onMeta = () => setDuration(master.duration || 0);
    const onEnd = () => setPlaying(false);
    master.addEventListener("timeupdate", onTime);
    master.addEventListener("loadedmetadata", onMeta);
    master.addEventListener("ended", onEnd);
    return () => {
      master.removeEventListener("timeupdate", onTime);
      master.removeEventListener("loadedmetadata", onMeta);
      master.removeEventListener("ended", onEnd);
    };
  }, [active]);

  // Seek seeks all tracks together.
  const seek = (sec) => {
    Object.values(refs.current).forEach((el) => {
      if (!el) return;
      try { el.currentTime = sec; } catch { /* ignore */ }
    });
    setPosition(sec);
  };

  // Mute all but the active one — keeps everything in sync but only one audible.
  useEffect(() => {
    tracks.forEach((t) => {
      const el = refs.current[t.key];
      if (!el) return;
      el.muted = t.key !== active;
    });
  }, [active, tracks]);

  if (tracks.length === 0) return null;

  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">{t("ab.title")}</span>
        <Tooltip content={t("ab.explain_tooltip")}>
          <span className="text-[10px] text-fg-muted underline decoration-dotted underline-offset-4 cursor-help">
            {t("ab.how_it_works")}
          </span>
        </Tooltip>
        <span className="ml-auto mono text-[11px] text-fg-muted">
          {formatDuration(position)} / {formatDuration(duration)}
        </span>
      </div>

      {/* Sync'd hidden audio elements */}
      {tracks.map((t) => (
        <audio
          key={t.key}
          ref={(el) => { refs.current[t.key] = el; }}
          src={t.url}
          preload="metadata"
          crossOrigin="anonymous"
        />
      ))}

      {/* Track-selector chips */}
      <div className="flex flex-wrap gap-1.5">
        {tracks.map((t) => {
          const on = active === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setActive(t.key)}
              className={cn(
                "px-3 py-1.5 rounded-full text-xs transition-all ring-1",
                on ? ACCENT[t.accent] : "ring-white/5 bg-white/3 text-fg-muted hover:text-fg",
              )}
            >
              <span className="font-semibold">{t.label}</span>
              <span className="ml-1 text-[10px] opacity-70">· {t.sub}</span>
            </button>
          );
        })}
      </div>

      {/* Transport bar */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={toggle}
          className="inline-flex items-center justify-center size-10 rounded-full bg-gradient-to-br from-violet to-magenta text-white hover:shadow-[0_10px_30px_-12px_rgba(139,92,246,0.7)] transition-all"
          aria-label={playing ? t("ab.pause_aria") : t("ab.play_aria")}
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
          aria-label={t("ab.seek_aria")}
        />
        <div className="flex items-center gap-1.5">
          <Volume2 className="size-3.5 text-fg-muted" />
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={volume}
            onChange={(e) => setVolume(Number(e.target.value))}
            className="w-20 accent-violet"
            aria-label={t("ab.volume_aria")}
          />
        </div>
      </div>

      <div className="text-[10px] text-fg-muted/70 leading-relaxed break-keep">
        {t("ab.hint")}
      </div>
    </div>
  );
}
