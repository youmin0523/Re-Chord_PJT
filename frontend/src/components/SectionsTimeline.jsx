import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Map as MapIcon } from "lucide-react";
import { getSections } from "@/lib/api";
import { cn, formatDuration } from "@/lib/utils";

// Backend stores English section IDs ("intro", "verse", "pre-chorus", …).
// Map each to its i18n key — render-time t() resolves to ko/en.
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
const labelFor = (t, raw) => {
  const key = SECTION_KEY[raw];
  return key ? t(`sections2.${key}`) : raw;
};

// Color per functional section so the same role keeps the same color across the song.
const SECTION_COLOR = {
  intro:        "from-fg-muted/40 to-fg-muted/20",
  verse:        "from-violet/40 to-violet/15",
  "pre-chorus": "from-cyan/40 to-cyan/15",
  chorus:       "from-magenta/55 to-magenta/20",
  "post-chorus":"from-magenta/30 to-magenta/10",
  bridge:       "from-amber/45 to-amber/15",
  instrumental: "from-cyan/30 to-cyan/10",
  solo:         "from-amber/55 to-magenta/20",
  outro:        "from-fg-muted/30 to-fg-muted/10",
};

/**
 * Click-to-seek section timeline.
 *  onSeek(seconds) is optional — let the parent jump a wavesurfer instance.
 */
export function SectionsTimeline({ job, onSeek }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getSections(job.id).then(setData).catch((e) => setErr(e.message));
  }, [job.id]);

  if (err) {
    return (
      <div className="glass rounded-2xl p-4 text-xs text-rose-300">
        {t("common2.loading_failed", { label: t("common2.load_section"), err })}
      </div>
    );
  }
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="glass rounded-2xl p-6 text-center space-y-1">
        <div className="text-sm font-semibold text-fg">{t("sections2.no_sections_title")}</div>
        <div className="text-[12px] text-fg-muted">
          {t("sections2.no_sections_hint")}
        </div>
      </div>
    );
  }

  const sections = data.sections || [];
  if (sections.length === 0) return null;
  const totalEnd = sections[sections.length - 1].end_sec || 1;
  // Index sections so multiple "verse" labels become Verse 1, Verse 2...
  const counts = {};
  const numbered = sections.map((s) => {
    counts[s.label] = (counts[s.label] || 0) + 1;
    return { ...s, idx: counts[s.label] };
  });
  const showNumber = (label) => counts[label] > 1;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-3"
    >
      <div className="flex items-center gap-2">
        <MapIcon className="size-4 text-violet" />
        <span className="text-sm font-semibold">{t("sections2.title")}</span>
        <span className="ml-auto mono text-[11px] text-fg-muted">
          {sections.length}개 · BPM {data.bpm?.toFixed(1) ?? "—"}
        </span>
      </div>

      {/* Stacked bar */}
      <div className="relative h-10 rounded-lg overflow-hidden bg-black/30 ring-1 ring-white/5">
        {numbered.map((s, i) => {
          const left = (s.start_sec / totalEnd) * 100;
          const width = ((s.end_sec - s.start_sec) / totalEnd) * 100;
          const gradient = SECTION_COLOR[s.label] || "from-white/15 to-white/5";
          return (
            <button
              key={i}
              type="button"
              onClick={() => onSeek?.(s.start_sec)}
              title={`${labelFor(t, s.label)}${showNumber(s.label) ? ` ${s.idx}` : ""} · ${formatDuration(s.start_sec)}–${formatDuration(s.end_sec)}`}
              className={cn(
                "absolute top-0 bottom-0 inline-flex items-center justify-center",
                "bg-gradient-to-b text-[10px] mono text-fg/90",
                "transition-all hover:brightness-125 hover:-translate-y-px",
                gradient,
              )}
              style={{ left: `${left}%`, width: `calc(${width}% - 1px)`, marginLeft: "1px" }}
            >
              {width > 6 && (
                <span className="px-1 whitespace-nowrap">
                  {labelFor(t, s.label)}
                  {showNumber(s.label) ? ` ${s.idx}` : ""}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Detail list */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
        {numbered.map((s, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onSeek?.(s.start_sec)}
            className="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md bg-white/3 hover:bg-white/10 text-left transition-all"
          >
            <span className="text-xs text-fg truncate">
              {labelFor(t, s.label)}
              {showNumber(s.label) ? ` ${s.idx}` : ""}
            </span>
            <span className="mono text-[10px] text-fg-muted shrink-0">
              {formatDuration(s.start_sec)}
            </span>
          </button>
        ))}
      </div>

      <div className="text-[10px] text-fg-muted/70">
        {t("sections2.click_hint")}
      </div>
    </motion.div>
  );
}
