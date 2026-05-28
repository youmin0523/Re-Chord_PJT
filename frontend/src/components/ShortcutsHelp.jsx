import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Keyboard, X } from "lucide-react";
import { prettyCombo } from "@/lib/useKeyboardShortcuts";

/**
 * Cheatsheet modal for the global "?" shortcut. Group bindings by scope so
 * users can scan quickly. The bindings array is shape-compatible with
 * useKeyboardShortcuts entries plus an optional `group` field.
 */
export function ShortcutsHelp({ open, onClose, bindings }) {
  const { t } = useTranslation();
  // Group bindings by their .group field; ungrouped → "기본".
  const defaultGroup = t("shortcuts2.default_group");
  const groups = bindings.reduce((acc, b) => {
    const g = b.group || defaultGroup;
    (acc[g] = acc[g] || []).push(b);
    return acc;
  }, {});

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/55 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-label={t("shortcuts2.open_aria")}
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 8, opacity: 0 }}
            className="relative w-full max-w-lg rounded-2xl bg-bg1 ring-1 ring-white/10 p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={onClose}
              className="absolute top-3 right-3 inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted"
              aria-label={t("shortcuts2.close_aria")}
            >
              <X className="size-4" />
            </button>

            <div className="flex items-center gap-2">
              <Keyboard className="size-4 text-violet" />
              <div className="text-sm font-semibold">{t("shortcuts2.title")}</div>
              <span className="ml-auto mono text-[10px] text-fg-muted">esc · ?</span>
            </div>

            <div className="space-y-3">
              {Object.entries(groups).map(([g, list]) => (
                <div key={g} className="space-y-1">
                  <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
                    {g}
                  </div>
                  <div className="space-y-1">
                    {list.map((b) => (
                      <div
                        key={b.combo}
                        className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-white/[0.03]"
                      >
                        <span className="text-[12px] text-fg/90">{b.desc}</span>
                        <kbd className="mono text-[10px] px-2 py-0.5 rounded bg-white/8 ring-1 ring-white/10 text-fg">
                          {prettyCombo(b.combo)}
                        </kbd>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="text-[10px] text-fg-muted/70 leading-relaxed">
              {t("shortcuts2.hint")}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
