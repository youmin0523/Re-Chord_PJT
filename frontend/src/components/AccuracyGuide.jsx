import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Sparkles, X, Check, Copy, Info } from "lucide-react";
import { getInstallHints } from "@/lib/api";
import { cn } from "@/lib/utils";

const DISMISS_KEY = "rechord.accuracy_guide.dismissed.v1";

/**
 * Pre-job onboarding card: pulls /ops/install_hints, shows the user which
 * optional SOTA packages would lift their per-stage accuracy. Dismissible
 * (persisted in localStorage); always reopen-able from Settings → "정확도
 * 향상 가이드". Inline copy-to-clipboard for each install command.
 *
 * Why pre-job: when a user is about to submit a 6-minute worship track
 * for separation+score+chord detection, the right moment to surface
 * "uv pip install crema for 170-class chord vocab" is *before* they see
 * a 24-class chord result and lose confidence in the product.
 */
export function AccuracyGuide({ onClose, alwaysVisible = false }) {
  const { t } = useTranslation();
  const [hints, setHints] = useState(null);
  const [err, setErr] = useState(null);
  const [copied, setCopied] = useState("");
  const [dismissed, setDismissed] = useState(() => {
    try {
      return !alwaysVisible && localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (dismissed && !alwaysVisible) return;
    getInstallHints()
      .then((r) => setHints(r))
      .catch((e) => setErr(e.message));
  }, [dismissed, alwaysVisible]);

  if (dismissed && !alwaysVisible) return null;

  const handleDismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, "1"); } catch { /* ignore */ }
    setDismissed(true);
    onClose?.();
  };

  const handleCopy = async (cmd) => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(cmd);
      setTimeout(() => setCopied(""), 1800);
    } catch { /* ignore */ }
  };

  if (err) return null;
  if (!hints) return null;
  if (hints.all_installed) {
    return alwaysVisible ? (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="glass rounded-2xl p-5 ring-1 ring-emerald-400/30 bg-emerald-400/5"
      >
        <div className="flex items-center gap-2">
          <Check className="size-4 text-emerald-300" />
          <span className="text-sm font-semibold">
            {t("accuracy_guide.all_installed")}
          </span>
        </div>
        <div className="text-[11px] text-fg-muted/80 mt-2 leading-relaxed">
          {t("accuracy_guide.all_installed_detail")}
        </div>
      </motion.div>
    ) : null;
  }

  const missing = hints.missing || [];
  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 8 }}
        className="glass rounded-2xl p-5 ring-1 ring-cyan/30 bg-cyan/5 space-y-3 relative"
      >
        {!alwaysVisible && (
          <button
            type="button"
            onClick={handleDismiss}
            className="absolute right-3 top-3 text-fg-muted hover:text-fg"
            aria-label={t("accuracy_guide.close")}
          >
            <X className="size-4" />
          </button>
        )}
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-cyan" />
          <span className="text-sm font-semibold">{t("accuracy_guide.title")}</span>
          <span className="mono text-[10px] text-cyan/80">
            {t("accuracy_guide.missing_count", { count: missing.length })}
          </span>
        </div>

        <div className="text-[11px] text-fg-muted/90 leading-relaxed">
          {t("accuracy_guide.intro")}
        </div>

        <ul className="space-y-2">
          {missing.map((m, i) => (
            <li
              key={i}
              className="rounded-xl bg-white/[0.03] ring-1 ring-white/5 p-3 space-y-1"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="mono text-[11px] text-fg-muted">{m.stage}</span>
                <span className="text-sm text-fg font-medium">{m.package}</span>
              </div>
              <div className="text-[11px] text-fg-muted/85">
                → {m.accuracy_impact}
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 mono text-[11px] text-cyan/90 bg-black/30 rounded px-2 py-1 overflow-x-auto whitespace-nowrap">
                  {m.install}
                </code>
                <button
                  type="button"
                  onClick={() => handleCopy(m.install)}
                  className={cn(
                    "shrink-0 inline-flex items-center gap-1 rounded-md h-7 px-2",
                    "text-[10px] ring-1 transition-colors",
                    copied === m.install
                      ? "ring-emerald-400/40 text-emerald-300 bg-emerald-400/10"
                      : "ring-white/10 text-fg-muted hover:text-fg hover:bg-white/5",
                  )}
                >
                  {copied === m.install ? (
                    <><Check className="size-3" />{t("accuracy_guide.copied")}</>
                  ) : (
                    <><Copy className="size-3" />{t("accuracy_guide.copy")}</>
                  )}
                </button>
              </div>
            </li>
          ))}
        </ul>

        <div className="flex items-start gap-2 text-[10px] text-fg-muted/70 leading-relaxed">
          <Info className="size-3 mt-0.5 shrink-0" />
          <span>{t("accuracy_guide.footer")}</span>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
