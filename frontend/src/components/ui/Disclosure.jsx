import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Minimal collapsible / disclosure panel.
 * Use it to hide advanced options behind a clean default surface.
 *
 *   <Disclosure title="고급 옵션" hint="평소엔 안 봐도 됨">
 *     ...controls...
 *   </Disclosure>
 */
export function Disclosure({
  title,
  hint,
  icon,
  defaultOpen = false,
  rightSlot,
  children,
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="hairline rounded-2xl overflow-hidden bg-white/[0.015]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "w-full flex items-center gap-3 px-5 py-3.5 text-left",
          "transition-colors hover:bg-white/[0.025]",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-violet/40",
        )}
        aria-expanded={open}
      >
        {icon && (
          <span className="inline-flex size-7 items-center justify-center rounded-md bg-white/5 text-fg-muted shrink-0">
            {icon}
          </span>
        )}
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-semibold text-fg leading-tight">
            {title}
          </span>
          {hint && (
            <span className="block text-[11px] text-fg-muted mt-0.5">{hint}</span>
          )}
        </span>
        {rightSlot && (
          <span className="mr-2 text-[11px] text-fg-muted">{rightSlot}</span>
        )}
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="text-fg-muted"
        >
          <ChevronDown className="size-4" />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 pt-1">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
