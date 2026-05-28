import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Sparkles, Link as LinkIcon, Music2, Wand2, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * First-run inline coach-marks. Shows once per browser (localStorage flag),
 * walks through 3 short steps over the existing Home layout, dimmed
 * background, anchored speech bubbles.
 *
 * Trigger manually with <OnboardingTour force /> for demo. The dismiss
 * button writes the "seen" flag so it never reappears.
 */
const SEEN_KEY = "rechord:onboarding:seen:v1";

// Step IDs are static; titles/bodies resolve via t() so EN switching works.
const STEPS = [
  { icon: LinkIcon, key: "step1" },
  { icon: Music2,   key: "step2" },
  { icon: Wand2,    key: "step3" },
];

export function OnboardingTour({ force = false, onClose }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(0);

  // Open the tour AND rewind to step 1 every time we open — otherwise
  // a re-open from the "guide" button would still show whatever step
  // the user last closed on.
  useEffect(() => {
    if (force) {
      setIdx(0);
      setOpen(true);
      return;
    }
    try {
      if (!localStorage.getItem(SEEN_KEY)) {
        setIdx(0);
        setOpen(true);
      }
    } catch { /* ignore */ }
  }, [force]);

  const dismiss = () => {
    try { localStorage.setItem(SEEN_KEY, "1"); } catch { /* ignore */ }
    setOpen(false);
    setIdx(0);          // reset so the next open starts at step 1
    onClose?.();
  };

  const next = () => {
    if (idx >= STEPS.length - 1) {
      dismiss();
    } else {
      setIdx(idx + 1);
    }
  };

  const step = STEPS[idx];
  const Icon = step.icon;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-40 flex items-end sm:items-center justify-center p-4 bg-black/55 backdrop-blur-sm"
        >
          <motion.div
            initial={{ y: 16, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 12, opacity: 0 }}
            className="relative w-full max-w-md rounded-2xl bg-bg1 ring-1 ring-white/10 p-6 space-y-4"
          >
            <button
              type="button"
              onClick={dismiss}
              className="absolute top-3 right-3 inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted"
              aria-label={t("onboarding2.close_aria")}
            >
              <X className="size-4" />
            </button>

            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-violet" />
              <span className="text-[11px] mono uppercase tracking-[0.22em] text-fg-muted">
                {t("onboarding2.title")}
              </span>
            </div>

            <div className="flex items-start gap-3">
              <div className="inline-flex items-center justify-center size-10 rounded-xl bg-gradient-to-br from-violet/30 to-magenta/20 ring-1 ring-white/10 text-violet shrink-0">
                <Icon className="size-5" />
              </div>
              <div className="space-y-1.5 min-w-0">
                <div className="text-sm font-semibold text-fg">{t(`onboarding2.${step.key}_title`)}</div>
                <div className="text-[12px] text-fg-muted leading-relaxed break-keep">
                  {t(`onboarding2.${step.key}_body`)}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex gap-1">
                {STEPS.map((_, i) => (
                  <span
                    key={i}
                    className={cn(
                      "size-1.5 rounded-full",
                      i === idx ? "bg-violet" : "bg-white/15",
                    )}
                  />
                ))}
              </div>
              <button
                type="button"
                onClick={dismiss}
                className="ml-auto text-[11px] text-fg-muted hover:text-fg px-2 py-1"
              >
                {t("onboarding2.skip")}
              </button>
              <button
                type="button"
                onClick={next}
                className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full text-xs font-medium bg-gradient-to-br from-violet to-magenta text-white hover:shadow-[0_10px_30px_-12px_rgba(139,92,246,0.7)]"
              >
                {idx >= STEPS.length - 1 ? t("onboarding2.start") : t("onboarding2.next")}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
