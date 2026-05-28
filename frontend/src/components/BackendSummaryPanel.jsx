import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Cpu, Sparkles, AlertCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Renders the per-stage backend choices the orchestrator made + which
 * optional SOTA packages are still missing on this machine. Lets the user
 * answer "did I actually get the 170-class CREMA chord vocab, or the
 * 24-triad fallback?" without having to read the API JSON.
 *
 * Reads from job.meta.backend_summary which the orchestrator's
 * freeze_backend_summary() writes at the end of every run.
 */
export function BackendSummaryPanel({ job }) {
  const { t } = useTranslation();
  const meta = job?.meta || {};
  const summary = meta.backend_summary;
  if (!summary) return null;
  const used = summary.backends_used || [];
  const fallbacks = summary.fallbacks || [];
  const hints = summary.install_hints || [];
  if (used.length === 0 && fallbacks.length === 0 && hints.length === 0) {
    return null;
  }

  const levelStyle = {
    sota:      { ring: "ring-emerald-400/30", label: t("backend2.level_sota"),      pill: "bg-emerald-400/15 text-emerald-300" },
    primary:   { ring: "ring-cyan/30",        label: t("backend2.level_primary"),   pill: "bg-cyan/15 text-cyan" },
    fallback:  { ring: "ring-amber-400/30",   label: t("backend2.level_fallback"),  pill: "bg-amber-400/15 text-amber-200" },
    heuristic: { ring: "ring-rose-400/30",    label: t("backend2.level_heuristic"), pill: "bg-rose-400/15 text-rose-200" },
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-6 space-y-5"
    >
      <div className="flex items-center gap-2">
        <Cpu className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("backend2.title")}</span>
        <span className="ml-auto text-[11px] text-fg-muted">
          {t("backend2.subtitle")}
        </span>
      </div>

      {used.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {used.map((u, i) => {
            const s = levelStyle[u.level] || levelStyle.primary;
            return (
              <div
                key={i}
                className={cn(
                  "rounded-xl bg-white/3 ring-1 p-3 space-y-1",
                  s.ring,
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-fg-muted mono">{u.stage}</span>
                  <span className={cn(
                    "ml-auto text-[10px] rounded px-1.5 py-0.5",
                    s.pill,
                  )}>
                    {s.label}
                  </span>
                </div>
                <div className="mono text-sm text-fg break-all">{u.backend}</div>
                {u.note ? (
                  <div className="text-[10px] text-fg-muted/80 leading-snug">{u.note}</div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {fallbacks.length > 0 && (
        <div className="rounded-xl bg-amber-400/5 ring-1 ring-amber-400/30 p-3 space-y-1.5">
          <div className="flex items-center gap-2">
            <AlertCircle className="size-3.5 text-amber-300" />
            <span className="text-[11px] text-amber-200">
              {t("backend2.fallback_notice")}
            </span>
          </div>
          <ul className="text-[11px] text-fg-muted/90 space-y-0.5">
            {fallbacks.map((f, i) => (
              <li key={i} className="mono">
                · {f.stage}: <span className="text-fg-muted">{f.missing}</span>
                {f.reason ? ` — ${f.reason}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hints.length > 0 && (
        <div className="rounded-xl bg-cyan/5 ring-1 ring-cyan/30 p-3 space-y-1.5">
          <div className="flex items-center gap-2">
            <Sparkles className="size-3.5 text-cyan" />
            <span className="text-[11px] text-cyan">{t("backend2.install_tip")}</span>
          </div>
          <ul className="text-[11px] text-fg-muted/90 space-y-1">
            {hints.map((h, i) => (
              <li key={i} className="space-y-0.5">
                <div className="mono text-fg">
                  · {h.missing} <span className="text-fg-muted">→ {h.accuracy_impact}</span>
                </div>
                <div className="mono text-[10px] text-fg-muted/70 pl-3">
                  {h.install}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-start gap-2 text-[10px] text-fg-muted/70 leading-relaxed">
        <Info className="size-3 mt-0.5 shrink-0" />
        <span>{t("backend2.footer")}</span>
      </div>
    </motion.div>
  );
}
