import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Hash } from "lucide-react";
import { getChords } from "@/lib/api";
import { cn, formatDuration } from "@/lib/utils";

// Confidence color buckets.
const conf2tone = (c) =>
  c >= 0.8 ? "text-cyan" :
  c >= 0.65 ? "text-violet" :
  c >= 0.5 ? "text-fg" :
  "text-fg-muted";

export function ChordsPanel({ job, onSeek }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getChords(job.id).then(setData).catch((e) => setErr(e.message));
  }, [job.id]);

  if (err) {
    return (
      <div className="glass rounded-2xl p-4 text-xs text-rose-300">
        {t("common2.loading_failed", { label: t("common2.load_chord"), err })}
      </div>
    );
  }
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="glass rounded-2xl p-6 text-center space-y-1">
        <div className="text-sm font-semibold text-fg">{t("chords_panel.no_chords_title")}</div>
        <div className="text-[12px] text-fg-muted">
          {t("chords_panel.no_chords_hint")}
        </div>
      </div>
    );
  }
  const events = data.events || [];
  if (events.length === 0) return null;

  const avgConf = events.reduce((a, e) => a + (e.confidence || 0), 0) / events.length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-3"
    >
      <div className="flex items-center gap-2">
        <Hash className="size-4 text-magenta" />
        <span className="text-sm font-semibold">{t("chords_panel.title")}</span>
        <span className="ml-auto mono text-[11px] text-fg-muted">
          {events.length}구간 · avg conf{" "}
          <span className={conf2tone(avgConf)}>{avgConf.toFixed(2)}</span>
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {events.map((e, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onSeek?.(e.start_sec)}
            title={`${formatDuration(e.start_sec)}–${formatDuration(e.end_sec)} · conf ${(e.confidence ?? 0).toFixed(2)}`}
            className={cn(
              "px-3 py-1.5 rounded-lg text-sm transition-all bg-white/3 hover:bg-white/10",
              "ring-1 ring-white/5 hover:ring-magenta/40",
              conf2tone(e.confidence ?? 0),
            )}
          >
            <span className="font-semibold mono">{e.label}</span>
            <span className="ml-1.5 text-[10px] mono text-fg-muted">
              {formatDuration(e.start_sec)}
            </span>
          </button>
        ))}
      </div>

      <div className="text-[10px] text-fg-muted/70">
        {t("chords_panel.method_hint")}
      </div>
    </motion.div>
  );
}
