import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  StickyNote, Plus, Trash2, AlertTriangle, MapPin, X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { createNote, deleteNote, listNotes, patchNote } from "@/lib/api";
import { formatDuration, cn } from "@/lib/utils";

/**
 * Per-song rehearsal / arrangement notes editor.
 *
 *   - Free-text or timeline-attached (clicking the time chip jumps to it
 *     when ``onSeek`` is provided by the parent waveform).
 *   - 4 kinds with semantic color: note / cue / warning / skip.
 *   - All mutations hit ``/jobs/{id}/notes`` so they persist across
 *     server restarts.
 *
 * Mounts in both the Job results page (full editing) and the PerformanceView
 * (read-only, time-anchored notes rendered as ribbon markers).
 */
const KIND_PRESETS = [
  { id: "note",    labelKey: "notes2.kind_note",    icon: StickyNote,    color: "violet" },
  { id: "cue",     labelKey: "notes2.kind_cue",     icon: MapPin,        color: "cyan" },
  { id: "warning", labelKey: "notes2.kind_warning", icon: AlertTriangle, color: "amber" },
  { id: "skip",    labelKey: "notes2.kind_skip",    icon: X,             color: "magenta" },
];

const KIND = Object.fromEntries(KIND_PRESETS.map((k) => [k.id, k]));
const COLOR_RING = {
  violet:  "ring-violet/40 bg-violet/10 text-violet",
  cyan:    "ring-cyan/40 bg-cyan/10 text-cyan",
  amber:   "ring-amber-400/40 bg-amber-400/10 text-amber-300",
  magenta: "ring-magenta/40 bg-magenta/10 text-magenta",
};

export function NotesEditor({ job, onSeek, readOnly = false }) {
  const { t } = useTranslation();
  const [notes, setNotes] = useState([]);
  const [draft, setDraft] = useState({ text: "", kind: "note", start_sec: null, end_sec: null });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listNotes(job.id).then((d) => setNotes(d.notes || [])).catch((e) => setErr(e.message));
  }, [job.id]);

  const addNote = async () => {
    if (!draft.text.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      const created = await createNote(job.id, {
        text: draft.text.trim(),
        kind: draft.kind,
        start_sec: draft.start_sec,
        end_sec: draft.end_sec,
      });
      setNotes((prev) => [...prev, created]);
      setDraft({ text: "", kind: draft.kind, start_sec: null, end_sec: null });
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const updateNote = async (id, patch) => {
    const cur = notes.find((n) => n.id === id);
    if (!cur) return;
    const merged = { ...cur, ...patch };
    setNotes((prev) => prev.map((n) => (n.id === id ? merged : n)));
    try {
      await patchNote(job.id, id, {
        text: merged.text,
        kind: merged.kind,
        start_sec: merged.start_sec,
        end_sec: merged.end_sec,
      });
    } catch (e) {
      setErr(e.message);
    }
  };

  const removeNote = async (id) => {
    setNotes((prev) => prev.filter((n) => n.id !== id));
    try { await deleteNote(job.id, id); } catch (e) { setErr(e.message); }
  };

  if (readOnly && notes.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-3"
    >
      <div className="flex items-center gap-2">
        <StickyNote className="size-4 text-violet" />
        <span className="text-sm font-semibold">{t("notes2.title")}</span>
        <span className="ml-auto mono text-[11px] text-fg-muted">{notes.length}개</span>
      </div>

      {err && (
        <div className="rounded-md px-2.5 py-1.5 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
          {err}
        </div>
      )}

      <ul className="space-y-1.5">
        <AnimatePresence initial={false}>
          {notes.map((n) => {
            const k = KIND[n.kind] || KIND.note;
            const Icon = k.icon;
            return (
              <motion.li
                key={n.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 8 }}
                className="flex items-center gap-2 rounded-md bg-white/[0.03] ring-1 ring-white/5 px-2.5 py-1.5 group"
              >
                <span className={cn(
                  "inline-flex items-center justify-center size-6 rounded-md ring-1",
                  COLOR_RING[k.color],
                )}>
                  <Icon className="size-3" />
                </span>
                {n.start_sec != null && (
                  <button
                    type="button"
                    onClick={() => onSeek?.(n.start_sec)}
                    title={t("notes2.jump_to_title")}
                    className="mono text-[10px] text-fg-muted hover:text-fg shrink-0"
                  >
                    {formatDuration(n.start_sec)}
                  </button>
                )}
                {readOnly ? (
                  <span className="text-[12px] text-fg flex-1 truncate" title={n.text}>{n.text}</span>
                ) : (
                  <input
                    value={n.text}
                    onChange={(e) => updateNote(n.id, { text: e.target.value })}
                    className="flex-1 bg-transparent text-[12px] text-fg focus:outline-none"
                  />
                )}
                {!readOnly && (
                  <>
                    <select
                      value={n.kind}
                      onChange={(e) => updateNote(n.id, { kind: e.target.value })}
                      className="bg-black/30 ring-1 ring-white/10 rounded text-[10px] mono py-0.5 px-1 text-fg-muted opacity-0 group-hover:opacity-100"
                    >
                      {KIND_PRESETS.map((k) => (
                        <option key={k.id} value={k.id}>{k.labelKey ? t(k.labelKey) : k.label}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => removeNote(n.id)}
                      title={t("notes2.delete_title")}
                      className="opacity-0 group-hover:opacity-100 inline-flex items-center justify-center size-5 rounded hover:bg-rose-500/10 text-fg-muted hover:text-rose-300"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  </>
                )}
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>

      {!readOnly && (
        <div className="rounded-lg bg-white/[0.025] ring-1 ring-white/5 p-2.5 space-y-2">
          <div className="flex flex-wrap items-center gap-1">
            {KIND_PRESETS.map((k) => {
              const on = draft.kind === k.id;
              const Icon = k.icon;
              return (
                <button
                  key={k.id}
                  type="button"
                  onClick={() => setDraft((d) => ({ ...d, kind: k.id }))}
                  className={cn(
                    "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] ring-1 transition-colors",
                    on ? COLOR_RING[k.color] : "ring-white/8 bg-white/3 text-fg-muted hover:text-fg",
                  )}
                >
                  <Icon className="size-3" /> {k.labelKey ? t(k.labelKey) : k.label}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-2">
            <input
              value={draft.text}
              onChange={(e) => setDraft((d) => ({ ...d, text: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter") addNote(); }}
              placeholder={t("notes2.placeholder")}
              className="flex-1 bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 text-[12px] text-fg placeholder:text-fg-muted/60 focus:outline-none focus:ring-violet/40"
            />
            <button
              type="button"
              disabled={!draft.text.trim() || busy}
              onClick={addNote}
              className="inline-flex items-center gap-1.5 rounded-full h-8 px-3 text-xs bg-violet/15 hover:bg-violet/25 text-violet ring-1 ring-violet/30 disabled:opacity-40"
            >
              <Plus className="size-3.5" /> {t("notes2.add")}
            </button>
          </div>
        </div>
      )}
    </motion.div>
  );
}
