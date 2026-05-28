import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Headphones, Download, Music, AudioWaveform } from "lucide-react";
import { downloadArtifact } from "@/lib/api";
import { cn, trackFilename } from "@/lib/utils";

export function MonitorPanel({ job }) {
  const { t } = useTranslation();
  const hasMonitor = !!job.artifacts?.monitor_track;
  const hasClick = !!job.artifacts?.click_track;
  if (!hasMonitor && !hasClick) return null;

  const bpm = job?.meta?.bpm;
  const ext = job.options?.format || "wav";
  const fileExt = ext === "aac" ? "m4a" : ext === "aiff" ? "aif" : ext;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-6 space-y-4 glow-cyan"
    >
      <div className="flex items-center gap-2">
        <Headphones className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("monitor2.title")}</span>
        {bpm && (
          <span className="ml-auto mono text-[11px] text-fg-muted">
            BPM <span className="text-cyan">{bpm.toFixed(1)}</span>
          </span>
        )}
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        {hasMonitor && (
          <Card
            label={t("monitor2.monitor_label")}
            sub={t("monitor2.monitor_sub")}
            icon={Music}
            color="violet"
            onClick={() =>
              downloadArtifact(
                job.id, "monitor_track",
                trackFilename(job, "monitor", fileExt),
              )
            }
          />
        )}
        {hasClick && (
          <Card
            label={t("monitor2.click_label")}
            sub={t("monitor2.click_sub")}
            icon={AudioWaveform}
            color="cyan"
            onClick={() =>
              downloadArtifact(
                job.id, "click_track",
                trackFilename(job, "click", fileExt),
              )
            }
          />
        )}
      </div>

      <div className="text-[11px] text-fg-muted/80 leading-relaxed">
        {t("monitor2.hint")}
      </div>
    </motion.div>
  );
}

function Card({ label, sub, icon: Icon, color, onClick }) {
  const { t } = useTranslation();
  const ringMap = {
    violet: "from-violet/15 to-cyan/10 ring-violet/30 hover:ring-violet/60 text-violet",
    cyan: "from-cyan/15 to-violet/10 ring-cyan/30 hover:ring-cyan/60 text-cyan",
    amber: "from-amber/15 to-magenta/10 ring-amber/30 hover:ring-amber/60 text-amber",
  };
  return (
    <motion.button
      whileHover={{ y: -2 }}
      onClick={onClick}
      className={cn(
        "rounded-2xl p-4 text-left bg-gradient-to-br ring-1 transition-all",
        ringMap[color],
      )}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <Icon className="size-4" />
        <span className="text-sm font-semibold text-fg">{label}</span>
      </div>
      <div className="text-[11px] text-fg-muted leading-relaxed">{sub}</div>
      <div className="mt-3 inline-flex items-center gap-1.5 text-xs">
        <Download className="size-3.5" /> {t("monitor2.pick_folder")}
      </div>
    </motion.button>
  );
}
