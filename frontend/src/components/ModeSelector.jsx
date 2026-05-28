import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Wand2, Mic2, Layers3, Sliders } from "lucide-react";
import { cn } from "@/lib/utils";

const MODES_META = [
  { id: "quick_mr", key: "quick",   glow: "violet",  icon: Wand2,    badge: "~1×" },
  { id: "karaoke",  key: "karaoke", glow: "violet",  icon: Mic2,     badge: "~1.5×" },
  { id: "stems",    key: "stems",   glow: "amber",   icon: Layers3,  badge: "~2×" },
  { id: "pro",      key: "pro",     glow: "magenta", icon: Sliders,  badge: "~3×" },
];

const GLOW_CLASSES = {
  violet: "glow-violet",
  cyan: "glow-cyan",
  amber: "glow-amber",
  magenta: "glow-magenta",
};

const ACCENT_BG = {
  violet: "bg-violet/20 text-violet",
  cyan: "bg-cyan/20 text-cyan",
  amber: "bg-amber/20 text-amber",
  magenta: "bg-magenta/20 text-magenta",
};

export function ModeSelector({ value, onChange }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5 sm:gap-3">
      {MODES_META.map((m) => {
        const Icon = m.icon;
        const active = value === m.id;
        return (
          <motion.button
            key={m.id}
            type="button"
            onClick={() => onChange(m.id)}
            whileHover={{ y: -3 }}
            whileTap={{ scale: 0.98 }}
            className={cn(
              "relative text-left p-4 sm:p-5 rounded-2xl transition-all glass",
              active && GLOW_CLASSES[m.glow],
              !active && "opacity-80 hover:opacity-100",
            )}
            aria-pressed={active}
          >
            <div className="flex items-start justify-between mb-2 sm:mb-3">
              <span
                className={cn(
                  "inline-flex items-center justify-center rounded-xl size-9 sm:size-10",
                  active ? ACCENT_BG[m.glow] : "bg-white/5 text-fg-muted",
                )}
              >
                <Icon className="size-5" />
              </span>
              <span className="mono text-[10px] text-fg-muted tracking-wider">
                {m.badge}
              </span>
            </div>
            <div className="text-sm sm:text-base font-semibold text-fg">{t(`mode.${m.key}_label`)}</div>
            <div className="mt-1 text-xs text-fg-muted leading-relaxed">{t(`mode.${m.key}_desc`)}</div>
            {active && (
              <span className="absolute left-5 right-5 -bottom-px h-px bg-gradient-to-r from-violet via-cyan to-magenta" />
            )}
          </motion.button>
        );
      })}
    </div>
  );
}
