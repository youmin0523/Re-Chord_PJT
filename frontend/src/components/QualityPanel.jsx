import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Activity, AlertTriangle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Visualizes the null-test quality report. Pulls values from job.meta.
 * If no quality data is present, renders nothing.
 */
export function QualityPanel({ job }) {
  const { t } = useTranslation();
  const meta = job.meta || {};
  const has = meta.quality_grade != null
    || meta.quality_null_rms_dbfs != null;
  if (!has) return null;

  const grade = meta.quality_grade || "?";
  const nullRms = meta.quality_null_rms_dbfs;
  const recon = meta.quality_recon_corr;
  const leak = meta.quality_vocal_leak_dbfs;
  const xcorr = meta.quality_voc_inst_xcorr;

  const gradeColor =
    grade.startsWith("A") ? "from-emerald-400 to-cyan"
      : grade.startsWith("B") ? "from-cyan to-violet"
      : grade.startsWith("C") ? "from-violet to-magenta"
      : "from-amber to-magenta";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-6 space-y-5"
    >
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("quality2.title")}</span>
        <span className="ml-auto inline-flex items-center gap-2">
          <span className="text-[11px] text-fg-muted mono">GRADE</span>
          <span
            className={cn(
              "mono font-extrabold text-2xl bg-gradient-to-br bg-clip-text text-transparent",
              gradeColor,
            )}
          >
            {grade}
          </span>
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric
          label={t("quality2.stat_residual_rms")}
          value={nullRms != null ? `${nullRms.toFixed(1)} dB` : "—"}
          good={nullRms != null && nullRms <= -30}
          hint={t("quality2.stat_residual_hint")}
        />
        <Metric
          label={t("quality2.stat_recon_corr")}
          value={recon != null ? recon.toFixed(3) : "—"}
          good={recon != null && recon >= 0.95}
          hint={t("quality2.stat_recon_hint")}
        />
        <Metric
          label={t("quality2.stat_band_strength")}
          value={leak != null ? `${leak.toFixed(1)} dB` : "—"}
          good={leak == null || leak <= -5}
          hint={t("quality2.stat_band_hint")}
        />
        <Metric
          label={t("quality2.stat_stem_corr")}
          value={xcorr != null ? xcorr.toFixed(3) : "—"}
          good={xcorr != null && Math.abs(xcorr) < 0.05}
          hint={t("quality2.stat_stem_hint")}
        />
      </div>

      <div className="text-[11px] text-fg-muted/80 leading-relaxed">
        {t("quality2.hint")}
      </div>
    </motion.div>
  );
}

function Metric({ label, value, good, hint }) {
  return (
    <div className="rounded-xl bg-white/3 ring-1 ring-white/5 p-3 space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-fg-muted">{label}</span>
        {good ? (
          <CheckCircle2 className="size-3.5 text-emerald-400" />
        ) : (
          <AlertTriangle className="size-3.5 text-amber" />
        )}
      </div>
      <div className="mono text-lg text-fg">{value}</div>
      <div className="text-[10px] text-fg-muted/70 leading-relaxed">{hint}</div>
    </div>
  );
}
