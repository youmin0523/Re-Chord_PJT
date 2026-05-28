import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/lib/useMediaQuery";

/**
 * Tabs container with an optional mobile-accordion layout.
 *
 *   tabs:         [{ id, label, icon?, badge?, content }]
 *   defaultTab:   id of the tab to open first
 *   mobileLayout: "tabs" (default) | "accordion"
 *                 When "accordion" AND the viewport is below ``sm``, the
 *                 tab bar is replaced with a stacked accordion. The
 *                 first tab is expanded by default; users can open more
 *                 sections without losing context. Lazy-loaded panel
 *                 content stays gated by Suspense — content only mounts
 *                 when its section is open.
 */
export function Tabs({ tabs, defaultTab, mobileLayout = "tabs" }) {
  const isMobile = useMediaQuery("(max-width: 639px)");
  const useAccordion = mobileLayout === "accordion" && isMobile;

  if (useAccordion) {
    return <AccordionTabs tabs={tabs} defaultTab={defaultTab} />;
  }
  return <HorizontalTabs tabs={tabs} defaultTab={defaultTab} />;
}

function HorizontalTabs({ tabs, defaultTab }) {
  const initial = defaultTab || tabs[0]?.id;
  const [active, setActive] = useState(initial);
  const current = tabs.find((t) => t.id === active) || tabs[0];

  return (
    <div className="space-y-4">
      {/* Tab bar: horizontal scroll on phones (no wrap), wraps freely on
          tablets+ so all tabs are reachable without losing the active
          pill animation. */}
      <div
        role="tablist"
        className="flex sm:flex-wrap items-center gap-1 p-1 glass rounded-xl overflow-x-auto sm:overflow-visible whitespace-nowrap snap-x snap-mandatory -mx-1 px-1"
      >
        {tabs.map((t) => {
          const isOn = t.id === active;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={isOn}
              onClick={() => setActive(t.id)}
              className={cn(
                "relative inline-flex items-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs sm:text-sm transition-all snap-start shrink-0",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/60",
                isOn
                  ? "text-fg"
                  : "text-fg-muted hover:text-fg hover:bg-white/3",
              )}
            >
              {isOn && (
                <motion.span
                  layoutId="tab-active-pill"
                  className="absolute inset-0 rounded-lg bg-gradient-to-br from-violet/25 to-magenta/15 ring-1 ring-violet/40 -z-0"
                  transition={{ type: "spring", stiffness: 400, damping: 32 }}
                />
              )}
              <span className="relative z-10 inline-flex items-center gap-1.5 sm:gap-2">
                {t.icon}
                {t.label}
                {t.badge != null && (
                  <span className="ml-1 mono text-[10px] px-1.5 rounded-full bg-white/10 text-fg-muted">
                    {t.badge}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <motion.div
        key={active}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="space-y-5"
      >
        {current?.content}
      </motion.div>
    </div>
  );
}

function AccordionTabs({ tabs, defaultTab }) {
  // On mobile, the first tab (or the explicitly-defaulted one) is open;
  // other sections can be expanded simultaneously so the user can scan
  // multiple panels without losing scroll position to a tab switch.
  const initial = defaultTab || tabs[0]?.id;
  const [open, setOpen] = useState(() => ({ [initial]: true }));

  return (
    <div className="space-y-3" role="region" aria-label="결과 패널">
      {tabs.map((t) => {
        const isOpen = !!open[t.id];
        return (
          <section
            key={t.id}
            className="hairline rounded-2xl overflow-hidden bg-white/[0.015]"
          >
            <button
              type="button"
              onClick={() => setOpen((cur) => ({ ...cur, [t.id]: !cur[t.id] }))}
              className={cn(
                "w-full flex items-center gap-3 px-4 py-3 text-left transition-colors",
                "hover:bg-white/[0.025] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-violet/40",
              )}
              aria-expanded={isOpen}
              aria-controls={`section-${t.id}`}
            >
              {t.icon && (
                <span className="inline-flex size-7 items-center justify-center rounded-md bg-white/5 text-fg-muted shrink-0">
                  {t.icon}
                </span>
              )}
              <span className="flex-1 min-w-0 text-sm font-semibold text-fg">
                {t.label}
              </span>
              {t.badge != null && (
                <span className="mono text-[10px] px-1.5 py-0.5 rounded-full bg-white/10 text-fg-muted shrink-0">
                  {t.badge}
                </span>
              )}
              <motion.span
                animate={{ rotate: isOpen ? 180 : 0 }}
                transition={{ duration: 0.2 }}
                className="text-fg-muted shrink-0"
              >
                <ChevronDown className="size-4" />
              </motion.span>
            </button>

            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  id={`section-${t.id}`}
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.22, ease: "easeOut" }}
                  className="overflow-hidden"
                >
                  <div className="px-3 pb-4 pt-1 space-y-5">{t.content}</div>
                </motion.div>
              )}
            </AnimatePresence>
          </section>
        );
      })}
    </div>
  );
}
