import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "react-i18next";
import { MessageSquare, Star, Send, Check, X } from "lucide-react";
import { submitFeedback } from "@/lib/api";
import { cn } from "@/lib/utils";


// Category ids map to i18n keys feedback2.cat_<id> / feedback2.cat_<id>_hint.
const CATEGORY_IDS = ["separation", "score", "chords", "lyrics", "timing", "overall"];


function StarRow({ value, onChange, name, t }) {
  return (
    <div className="flex items-center gap-1.5">
      {[1, 2, 3, 4, 5].map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v === value ? 0 : v)}
          className={cn(
            "p-1 rounded transition-colors",
            v <= value
              ? "text-amber-300 hover:text-amber-200"
              : "text-fg-muted/40 hover:text-fg-muted",
          )}
          aria-label={t("feedback2.star_aria", { name, value: v })}
        >
          <Star
            className="size-4"
            fill={v <= value ? "currentColor" : "none"}
            strokeWidth={1.5}
          />
        </button>
      ))}
    </div>
  );
}


/**
 * Per-job feedback panel. Renders ratings + free-text + optional
 * contact field, POSTs to /feedback, shows confirmation. Used in the
 * Quality tab of ResultPanel.
 */
export function FeedbackPanel({ job }) {
  const { t } = useTranslation();
  const categories = CATEGORY_IDS.map((id) => ({
    id,
    label: t(`feedback2.cat_${id}`),
    hint: t(`feedback2.cat_${id}_hint`),
  }));
  const [ratings, setRatings] = useState({});
  const [notes, setNotes] = useState("");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState(null);

  const setRating = (cat, v) =>
    setRatings((prev) => ({ ...prev, [cat]: v || undefined }));

  const totalSet = Object.values(ratings).filter((v) => v > 0).length;
  const canSubmit = (totalSet > 0 || notes.trim().length > 0) && !busy && !done;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true); setErr(null);
    try {
      const cleaned = Object.fromEntries(
        Object.entries(ratings).filter(([, v]) => v > 0),
      );
      const meta = {
        ua: navigator.userAgent,
        screen: `${window.screen.width}x${window.screen.height}`,
        locale: navigator.language,
        ts: new Date().toISOString(),
      };
      await submitFeedback({
        job_id: job.id, ratings: cleaned,
        notes: notes.trim(), contact: contact.trim(),
        client_meta: meta,
      });
      setDone(true);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="glass rounded-2xl p-5 ring-1 ring-emerald-400/30 bg-emerald-400/5"
      >
        <div className="flex items-center gap-2">
          <Check className="size-4 text-emerald-300" />
          <span className="text-sm font-semibold text-emerald-200">
            {t("feedback2.thank_you")}
          </span>
        </div>
        <div className="text-[11px] text-fg-muted/85 mt-2 leading-relaxed">
          {t("feedback2.thank_you_detail")}
        </div>
        <button
          type="button"
          onClick={() => { setDone(false); setRatings({}); setNotes(""); setContact(""); }}
          className="mt-3 text-[11px] text-fg-muted hover:text-fg underline-offset-2 hover:underline"
        >
          {t("feedback2.write_new")}
        </button>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-4"
    >
      <div className="flex items-center gap-2">
        <MessageSquare className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("feedback2.title")}</span>
        <span className="ml-auto text-[10px] text-fg-muted">
          {t("feedback2.subtitle")}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {categories.map((c) => (
          <div
            key={c.id}
            className="rounded-xl bg-white/[0.025] ring-1 ring-white/5 p-3 space-y-1.5"
          >
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-fg">{c.label}</span>
              <StarRow
                value={ratings[c.id] || 0}
                onChange={(v) => setRating(c.id, v)}
                name={c.label}
                t={t}
              />
            </div>
            <div className="text-[10px] text-fg-muted/70 leading-snug">
              {c.hint}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] text-fg-muted">{t("feedback2.notes_label")}</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value.slice(0, 2000))}
          placeholder={t("feedback2.notes_placeholder")}
          rows={3}
          className="w-full bg-black/30 border border-white/10 rounded-md px-2.5 py-1.5 text-[12px] text-fg placeholder:text-fg-muted/60 focus:outline-none focus:ring-1 focus:ring-cyan/40"
        />
        <div className="text-[10px] text-fg-muted/60 text-right mono">
          {notes.length}/2000
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] text-fg-muted">
          {t("feedback2.contact_label")}
        </label>
        <input
          type="text"
          value={contact}
          onChange={(e) => setContact(e.target.value.slice(0, 200))}
          placeholder={t("feedback2.contact_placeholder")}
          className="w-full bg-black/30 border border-white/10 rounded-md px-2.5 py-1.5 text-[12px] text-fg placeholder:text-fg-muted/60 focus:outline-none focus:ring-1 focus:ring-cyan/40"
        />
      </div>

      <AnimatePresence>
        {err && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="rounded-md px-2.5 py-1.5 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20 flex items-center gap-2"
          >
            <X className="size-3.5" /> {err}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center gap-2 justify-end">
        <span className="text-[10px] text-fg-muted/70 mr-auto">
          {totalSet > 0
            ? t("feedback2.rated_count", { count: totalSet })
            : t("feedback2.need_input")}
        </span>
        <button
          type="button"
          disabled={!canSubmit}
          onClick={submit}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md h-8 px-3 text-[11px]",
            "ring-1 transition-colors",
            canSubmit
              ? "ring-cyan/40 bg-cyan/10 text-cyan hover:bg-cyan/20"
              : "ring-white/10 text-fg-muted/60 cursor-not-allowed",
          )}
        >
          <Send className="size-3" /> {t("feedback2.send")}
        </button>
      </div>
    </motion.div>
  );
}
