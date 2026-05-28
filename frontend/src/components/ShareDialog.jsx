import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Share2, Copy, Check, X, Code, Link2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Share + embed dialog. Two outputs:
 *
 *   1. Read-only link to the job result page (current origin).
 *   2. Embed snippet — a 1-line <iframe> the user can paste into a notion/
 *      blog/team channel. The iframe URL is the same link but with
 *      ?embed=1 (the Job page collapses chrome when this is set).
 *
 * No server-side share state — phase A is single-device; we just emit the
 * URL the user already has. Phase B will mint signed URLs.
 */
export function ShareDialog({ open, onClose, job }) {
  const { t } = useTranslation();
  const url = typeof window === "undefined"
    ? ""
    : `${window.location.origin}/job/${job.id}`;
  const embedUrl = `${url}?embed=1`;
  const embedSnippet =
    `<iframe src="${embedUrl}" width="100%" height="520" frameborder="0" `
    + `style="border-radius:16px;background:#0b0b13" allow="autoplay"></iframe>`;

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
            aria-label={t("share2.share_aria")}
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 8, opacity: 0 }}
            className="relative w-full max-w-lg rounded-2xl bg-bg1 ring-1 ring-white/10 p-6 space-y-5"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={onClose}
              className="absolute top-3 right-3 inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted"
              aria-label={t("share2.close_aria")}
            >
              <X className="size-4" />
            </button>

            <div className="flex items-center gap-2">
              <Share2 className="size-4 text-violet" />
              <div className="text-sm font-semibold">{t("share2.title")}</div>
            </div>

            <CopyRow icon={Link2} label={t("share2.link_label")} value={url} />
            <CopyRow icon={Code} label={t("share2.embed_label")} value={embedSnippet} multiline />

            <div className="rounded-xl bg-amber-400/5 ring-1 ring-amber-400/20 p-3 text-[11px] text-amber-100/85 leading-relaxed break-keep">
              {t("share2.phase_a_warning")}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function CopyRow({ icon: Icon, label, value, multiline = false }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* ignore */ }
  };
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
        <Icon className="size-3" /> {label}
      </div>
      <div className="flex items-stretch gap-2">
        {multiline ? (
          <textarea
            readOnly
            value={value}
            rows={3}
            className="flex-1 bg-black/30 ring-1 ring-white/10 rounded-lg px-3 py-2 mono text-[11px] text-fg-muted resize-none focus:outline-none focus:ring-violet/40"
          />
        ) : (
          <input
            readOnly
            value={value}
            className="flex-1 bg-black/30 ring-1 ring-white/10 rounded-lg px-3 py-2 mono text-[11px] text-fg focus:outline-none focus:ring-violet/40"
          />
        )}
        <button
          type="button"
          onClick={copy}
          className={cn(
            "shrink-0 inline-flex items-center gap-1.5 rounded-lg px-3 text-xs",
            copied
              ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30"
              : "bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg",
          )}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? t("share2.copied") : t("share2.copy")}
        </button>
      </div>
    </div>
  );
}
