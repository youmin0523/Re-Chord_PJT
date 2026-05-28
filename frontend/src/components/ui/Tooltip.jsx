import { useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * Lightweight tooltip + glossary primitive.
 *
 * Two use modes:
 *
 *   <Tooltip content="What MR means">
 *     <button>?</button>
 *   </Tooltip>
 *
 *   <Glossary term="MR">반주만 남긴 트랙</Glossary>   // dotted-underline term
 *
 * The glossary variant shows the term inline with a dotted underline and
 * reveals the definition on hover / focus. Korean-friendly: text doesn't
 * break mid-word and the bubble width is constrained so phrases wrap cleanly.
 */
export function Tooltip({ content, children, side = "top", align = "center" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const show = () => setOpen(true);
  const hide = () => setOpen(false);

  const placement = {
    top:    "bottom-full mb-2",
    bottom: "top-full mt-2",
    left:   "right-full mr-2 top-1/2 -translate-y-1/2",
    right:  "left-full ml-2 top-1/2 -translate-y-1/2",
  }[side];

  const justify = {
    start:  "left-0",
    center: "left-1/2 -translate-x-1/2",
    end:    "right-0",
  }[align];

  return (
    <span
      ref={ref}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      className="relative inline-flex items-center"
    >
      {children}
      <AnimatePresence>
        {open && content && (
          <motion.span
            initial={{ opacity: 0, y: 2 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 2 }}
            transition={{ duration: 0.12 }}
            role="tooltip"
            className={cn(
              "absolute z-50 pointer-events-none",
              "px-2.5 py-1.5 rounded-lg text-[11px] leading-snug",
              "bg-bg1/95 backdrop-blur-md ring-1 ring-white/10 text-fg",
              "shadow-[0_8px_28px_-10px_rgba(0,0,0,0.6)]",
              "max-w-[240px] whitespace-normal break-keep",
              placement,
              ["top", "bottom"].includes(side) ? justify : "",
            )}
          >
            {content}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

/**
 * Inline glossary term. Use for jargon: MR / stem / AUX / LUFS / etc.
 * The term shows a dotted underline; hover reveals the 1-sentence definition.
 */
export function Glossary({ term, children }) {
  return (
    <Tooltip content={children}>
      <span
        tabIndex={0}
        className="underline decoration-dotted decoration-fg-muted/60 underline-offset-4 cursor-help"
      >
        {term}
      </span>
    </Tooltip>
  );
}

/** Help icon — pair with technical terms in dense UI rows. */
export function HelpHint({ children, className = "" }) {
  return (
    <Tooltip content={children}>
      <span
        tabIndex={0}
        className={cn(
          "inline-flex items-center justify-center size-4 rounded-full",
          "bg-white/5 text-fg-muted hover:text-fg text-[9px] mono cursor-help",
          className,
        )}
        aria-label="help"
      >
        ?
      </span>
    </Tooltip>
  );
}
