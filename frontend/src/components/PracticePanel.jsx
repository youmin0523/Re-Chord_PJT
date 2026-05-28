import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Play, Pause, RotateCcw, Layers, Volume2, VolumeX, Headphones, Repeat } from "lucide-react";
import { useTranslation } from "react-i18next";
import { artifactUrl, getSections } from "@/lib/api";
import { ACTION_EVENT } from "@/lib/chatActions";
import { cn, formatDuration } from "@/lib/utils";

// Section ID → i18n key. Mirrors SectionsTimeline so the loop pills read
// in the active locale without duplicating translation strings.
const SECTION_KEY = {
  intro: "label_intro",
  verse: "label_verse",
  "pre-chorus": "label_pre_chorus",
  chorus: "label_chorus",
  "post-chorus": "label_post_chorus",
  bridge: "label_bridge",
  instrumental: "label_instrumental",
  solo: "label_solo",
  outro: "label_outro",
  silence: "label_silence",
};
const SECTION_TONE = {
  intro: "bg-white/5 text-fg-muted hover:text-fg",
  verse: "bg-violet/15 text-violet hover:bg-violet/25",
  "pre-chorus": "bg-cyan/15 text-cyan hover:bg-cyan/25",
  chorus: "bg-magenta/20 text-magenta hover:bg-magenta/30",
  "post-chorus": "bg-magenta/10 text-magenta hover:bg-magenta/20",
  bridge: "bg-amber/15 text-amber hover:bg-amber/25",
  instrumental: "bg-cyan/10 text-cyan hover:bg-cyan/20",
  solo: "bg-amber/20 text-amber hover:bg-amber/30",
  outro: "bg-white/5 text-fg-muted hover:text-fg",
};

/**
 * 단계별 학습 모드 — Practice Panel.
 *
 * Layered mixer with up to four channels, each backed by a real artifact
 * the orchestrator produced. The user can mute/solo/adjust volume per
 * channel and step up the difficulty by un-muting layers progressively.
 *
 *   Layer 1: 클릭 / 메트로놈 only (click_track)
 *   Layer 2: + Vocal (vocals_final)         — sing along
 *   Layer 3: + Instrumental MR              — full band
 *   Layer 4: + Monitor (voice cue + click)  — drummer's IEM track
 *
 * Channels that don't exist for the current job are simply omitted (no
 * fake placeholders). All audio elements share a single playhead, kept
 * in sync via a master controller; seek/pause/play propagate.
 */
export function PracticePanel({ job }) {
  const { t } = useTranslation();
  // Resolve available layers. Order matters for the "increase difficulty"
  // narrative — left to right, simplest to fullest.
  const layers = useMemo(() => {
    const candidates = [
      { id: "click_track",        labelKey: "practice2.click_label",   descKey: "practice2.click_desc",   defaultGain: 1.0, defaultMuted: false },
      { id: "vocals_final",       labelKey: "practice2.vocal_label",   descKey: "practice2.vocal_desc",   defaultGain: 0.8, defaultMuted: true  },
      { id: "instrumental_final", labelKey: "practice2.mr_label",      descKey: "practice2.mr_desc",      defaultGain: 0.9, defaultMuted: true  },
      { id: "monitor_track",      labelKey: "practice2.monitor_label", descKey: "practice2.monitor_desc", defaultGain: 0.7, defaultMuted: true  },
    ];
    return candidates.filter((c) => !!job.artifacts?.[c.id]);
  }, [job.artifacts]);

  const audioRefs = useRef({});
  const [gains, setGains] = useState(() =>
    Object.fromEntries(layers.map((l) => [l.id, l.defaultGain])),
  );
  const [muted, setMuted] = useState(() =>
    Object.fromEntries(layers.map((l) => [l.id, l.defaultMuted])),
  );
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);

  // Section loop — when set, the transport wraps from end → start instead
  // of playing to the end of the song. Toggling a section twice clears it.
  // Sections come from the analysis stage; absent on Quick MR jobs.
  const [sections, setSections] = useState(null);
  const [loop, setLoop] = useState(null);  // { id, label, start, end } | null

  useEffect(() => {
    if (!job?.id) return;
    let cancelled = false;
    getSections(job.id)
      .then((d) => { if (!cancelled && d?.available && Array.isArray(d.sections)) setSections(d.sections); })
      .catch(() => { /* analysis not requested or backend offline */ });
    return () => { cancelled = true; };
  }, [job.id]);

  // Apply gain + mute to elements whenever they change.
  useEffect(() => {
    for (const l of layers) {
      const a = audioRefs.current[l.id];
      if (a) {
        a.muted = !!muted[l.id];
        a.volume = Math.max(0, Math.min(1, gains[l.id] ?? 1));
      }
    }
  }, [gains, muted, layers]);

  const togglePlay = () => {
    if (playing) {
      layers.forEach((l) => audioRefs.current[l.id]?.pause());
      setPlaying(false);
    } else {
      // Re-align all to the first available channel's currentTime to
      // recover from any drift accrued during seek scrubbing.
      const master = layers.find((l) => !!audioRefs.current[l.id]);
      const t = master ? audioRefs.current[master.id].currentTime : 0;
      layers.forEach((l) => {
        const a = audioRefs.current[l.id];
        if (a) { a.currentTime = t; a.play().catch(() => {}); }
      });
      setPlaying(true);
    }
  };

  const seek = (t) => {
    layers.forEach((l) => {
      const a = audioRefs.current[l.id];
      if (a) a.currentTime = Math.max(0, Math.min(duration, t));
    });
    setPosition(t);
  };

  // Click a section pill → loop that range. Click the same one again → off.
  // Seek into the section so the user hears the result immediately.
  const toggleLoop = (sec) => {
    setLoop((cur) => {
      const next = cur && cur.id === sec.id ? null : sec;
      if (next) seek(next.start);
      return next;
    });
  };

  // Chatbot action handler — "loop_section" / "stop_loop" arrive when the
  // user clicks an "apply" button. Match the requested section by label
  // (e.g. "chorus") to the first occurrence in the analysed timeline.
  useEffect(() => {
    const onAction = (ev) => {
      const a = ev.detail;
      if (!a) return;
      if (a.type === "stop_loop") {
        setLoop(null);
        return;
      }
      if (a.type === "loop_section") {
        if (!sections) return;
        const target = (a.args?.section || "").toLowerCase();
        const idx = sections.findIndex(
          (s) => (s.label || s.name || "").toLowerCase() === target,
        );
        if (idx < 0) return;
        const s = sections[idx];
        const start = s.start ?? s.start_sec ?? s.start_time ?? 0;
        const end = s.end ?? s.end_sec ?? s.end_time ?? start;
        const id = s.id ?? `${s.label || "section"}-${idx}`;
        toggleLoop({ id, label: target, start, end });
      }
    };
    window.addEventListener(ACTION_EVENT, onAction);
    return () => window.removeEventListener(ACTION_EVENT, onAction);
    // ``sections`` and ``toggleLoop`` are intentional deps; toggleLoop is
    // a stable inline function inside this component so it's fine.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections]);

  if (layers.length === 0) {
    return null;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-3"
    >
      <div className="flex items-center gap-2">
        <Layers className="size-4 text-violet" />
        <span className="text-sm font-semibold">{t("practice2.title")}</span>
        <span className="ml-auto text-[11px] mono text-fg-muted">
          {t("practice2.active_count", { active: layers.filter((l) => !muted[l.id]).length, total: layers.length })}
        </span>
      </div>

      <div className="text-[11px] text-fg-muted leading-relaxed">
        {t("practice2.hint")}
      </div>

      {/* Section loop pills — only shown when the analysis stage produced
          section boundaries. Tapping one wraps playback to that range; tap
          again to clear. */}
      {sections && sections.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] mono uppercase tracking-[0.18em] text-fg-muted">
            <Repeat className="size-3" />
            {t("practice2.loop_label", { defaultValue: "구간 반복" })}
            {loop && (
              <button
                type="button"
                onClick={() => setLoop(null)}
                className="ml-auto normal-case tracking-normal text-[10px] text-violet/80 hover:text-violet underline-offset-2 hover:underline"
              >
                {t("practice2.loop_clear", { defaultValue: "해제" })}
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {sections.map((s, idx) => {
              const start = s.start ?? s.start_sec ?? s.start_time ?? 0;
              const end = s.end ?? s.end_sec ?? s.end_time ?? start;
              const id = s.id ?? `${s.label || "section"}-${idx}`;
              const raw = (s.label || s.name || "").toLowerCase();
              const key = SECTION_KEY[raw];
              const label = key ? t(`sections2.${key}`) : (s.label || s.name || `#${idx + 1}`);
              const tone = SECTION_TONE[raw] || "bg-white/5 text-fg-muted hover:text-fg";
              const isActive = loop?.id === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => toggleLoop({ id, label, start, end })}
                  aria-pressed={isActive}
                  className={cn(
                    "px-2.5 py-1 rounded-full text-[11px] transition-colors ring-1",
                    isActive
                      ? "bg-violet/30 text-fg ring-violet/60 shadow-[0_0_0_3px_rgba(139,92,246,0.18)]"
                      : `${tone} ring-white/10`,
                  )}
                  title={`${label} · ${formatDuration(start)} - ${formatDuration(end)}`}
                >
                  {label}
                  <span className="ml-1.5 mono text-[10px] opacity-60">
                    {formatDuration(start)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Layer rows */}
      <div className="space-y-2">
        {layers.map((l) => {
          const isMuted = !!muted[l.id];
          const label = l.labelKey ? t(l.labelKey) : l.label;
          const desc = l.descKey ? t(l.descKey) : l.desc;
          return (
            <div
              key={l.id}
              className="flex items-center gap-3 rounded-md bg-white/[0.025] ring-1 ring-white/5 px-3 py-2"
            >
              <button
                type="button"
                onClick={() =>
                  setMuted((p) => ({ ...p, [l.id]: !p[l.id] }))
                }
                aria-pressed={!isMuted}
                aria-label={isMuted ? t("practice2.channel_on_aria", { label }) : t("practice2.channel_off_aria", { label })}
                className={
                  isMuted
                    ? "inline-flex items-center justify-center size-8 rounded-full bg-white/5 text-fg-muted"
                    : "inline-flex items-center justify-center size-8 rounded-full bg-violet/20 text-violet ring-1 ring-violet/40"
                }
              >
                {isMuted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
              </button>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-semibold text-fg">{label}</div>
                <div className="text-[11px] text-fg-muted">{desc}</div>
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={gains[l.id] ?? 0}
                onChange={(e) =>
                  setGains((p) => ({ ...p, [l.id]: Number(e.target.value) }))
                }
                disabled={isMuted}
                aria-label={t("practice2.volume_aria", { label })}
                className="w-28 accent-violet disabled:opacity-40"
              />
            </div>
          );
        })}
      </div>

      {/* Transport */}
      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={() => seek(0)}
          className="inline-flex items-center justify-center size-9 rounded-full bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
          aria-label={t("practice2.from_start_aria")}
          title={t("practice2.from_start_title")}
        >
          <RotateCcw className="size-4" />
        </button>
        <button
          type="button"
          onClick={togglePlay}
          className="inline-flex items-center justify-center size-11 rounded-full bg-gradient-to-br from-violet to-cyan text-white shadow-[0_8px_22px_-12px_rgba(139,92,246,0.6)]"
          aria-label={playing ? t("practice2.pause_aria") : t("practice2.play_aria")}
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4 ml-0.5" />}
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(duration, 0.01)}
          step={0.05}
          value={Math.min(position, duration || 0)}
          onChange={(e) => seek(Number(e.target.value))}
          className="flex-1 accent-violet"
          aria-label={t("practice2.seek_aria")}
        />
        <span className="mono text-[11px] text-fg-muted shrink-0">
          {formatDuration(position)} / {formatDuration(duration)}
        </span>
        <Headphones className="size-3.5 text-fg-muted hidden sm:inline-flex" />
      </div>

      {/* Hidden audio elements — one per layer, share playhead via seek/play. */}
      {layers.map((l) => (
        <audio
          key={l.id}
          ref={(el) => { if (el) audioRefs.current[l.id] = el; }}
          src={artifactUrl(job.id, l.id)}
          preload="metadata"
          onLoadedMetadata={(e) => setDuration((d) => Math.max(d, e.target.duration || 0))}
          onTimeUpdate={(e) => {
            // Use the first available channel as time-source so we don't
            // thrash state on every channel's tick.
            if (l.id !== layers[0].id) return;
            const cur = e.target.currentTime || 0;
            // Section loop: wrap to start when we cross the end.
            if (loop && cur >= loop.end - 0.02) {
              seek(loop.start);
              return;
            }
            setPosition(cur);
          }}
          onEnded={() => {
            // If looping, restart from the section's start instead of stopping.
            if (loop) { seek(loop.start); return; }
            setPlaying(false);
          }}
        />
      ))}
    </motion.div>
  );
}
