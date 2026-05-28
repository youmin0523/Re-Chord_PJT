import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Mic,
  Save,
  RefreshCw,
  AlertTriangle,
  Languages,
  Plus,
  Trash2,
  Undo2,
  Redo2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { getLyrics, saveLyrics } from "@/lib/api";
import { useUndoStack } from "@/lib/useUndoStack";
import { useAutosave } from "@/lib/useAutosave";
import { ConfidenceSummary, ConfidenceUnderline } from "@/components/ui/ConfidenceBadge";
import { cn, formatDuration } from "@/lib/utils";

/**
 * Word-level lyrics editor.
 *
 *   - Each word is a chip with a confidence-colored underline.
 *   - Click a chip → inline edit (Enter to commit, Esc to cancel).
 *   - Click the timestamp → onSeek(sec) so the parent (waveform) jumps there.
 *   - Undo/redo (Cmd+Z / Cmd+Shift+Z) works locally; "save" flushes to server.
 *   - "악보 다시 만들기" PUTs the edited word list and rebuilds the vocals score.
 *
 * "AI proposes, user confirms" is the entire philosophy here.
 */
export function LyricsEditor({ job, onSeek }) {
  const { t } = useTranslation();
  const [raw, setRaw] = useState(null);     // server payload (read once)
  const initial = useMemo(() => [], []);
  const undo = useUndoStack(initial);
  const words = undo.state;
  const setWords = undo.set;

  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [activeVerse, setActiveVerse] = useState(1);
  const [lastSave, setLastSave] = useState(null);
  // Per-verse translations — optional bilingual rendering. Lives outside
  // the word undo stack because translation is a separate concern.
  const [translations, setTranslations] = useState({});

  // Initial fetch
  useEffect(() => {
    getLyrics(job.id)
      .then((d) => {
        setRaw(d);
        if (d.available && Array.isArray(d.words)) {
          const parsed = d.words.map((w) => ({
            word: String(w.word ?? ""),
            start_sec: Number(w.start_sec ?? 0),
            end_sec: Number(w.end_sec ?? 0),
            confidence: Number(w.confidence ?? 1.0),
            verse: Number(w.verse ?? 1),
          }));
          undo.reset(parsed);
        }
        if (d.translations && typeof d.translations === "object") {
          setTranslations(d.translations);
        }
      })
      .catch((e) => setErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  const wordsForVerse = useMemo(
    () => words
      .map((w, i) => ({ ...w, _i: i }))
      .filter((w) => (w.verse || 1) === activeVerse),
    [words, activeVerse],
  );
  const verses = useMemo(() => {
    const s = new Set(words.map((w) => w.verse || 1));
    if (s.size === 0) s.add(1);
    return Array.from(s).sort((a, b) => a - b);
  }, [words]);

  const avgConf = useMemo(() => {
    if (words.length === 0) return 0;
    return words.reduce((a, w) => a + (w.confidence || 0), 0) / words.length;
  }, [words]);

  const lowCount = useMemo(
    () => words.filter((w) => (w.confidence ?? 1) < 0.6).length,
    [words],
  );

  // Mutators ----------------------------------------------------------------
  const updateWord = (idx, patch) => {
    setWords((prev) => {
      const next = prev.slice();
      next[idx] = { ...next[idx], ...patch };
      return next;
    });
  };

  const removeWord = (idx) => {
    setWords((prev) => prev.filter((_, i) => i !== idx));
  };

  const addVerse = () => {
    const next = Math.max(...verses) + 1;
    const base = words.filter((w) => (w.verse || 1) === 1);
    const copy = base.map((w) => ({ ...w, verse: next, word: "" }));
    setWords((prev) => [...prev, ...copy]);
    setActiveVerse(next);
  };

  const save = async (rebuild) => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      const payload = words.map((w) => ({
        word: w.word,
        start_sec: w.start_sec,
        end_sec: w.end_sec,
        confidence: w.confidence ?? 1.0,
        verse: w.verse || 1,
      }));
      const trMap = Object.fromEntries(
        Object.entries(translations).filter(([, v]) => v && v.trim()),
      );
      const res = await saveLyrics(
        job.id, payload, rebuild,
        Object.keys(trMap).length ? trMap : null,
      );
      undo.reset(words);     // dirty=false after server commit
      setLastSave({ at: Date.now(), rebuilt: !!res.rebuilt, pages: res.pages });
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Autosave: 4s after user stops editing. Never triggers score rebuild
  // — explicit "저장 + 악보 재생성" stays a user action.
  const autosave = useAutosave({
    value: words,
    dirty: undo.dirty,
    interval: 4000,
    enabled: words.length > 0,
    onSave: async (val) => {
      const payload = val.map((w) => ({
        word: w.word, start_sec: w.start_sec, end_sec: w.end_sec,
        confidence: w.confidence ?? 1.0, verse: w.verse || 1,
      }));
      await saveLyrics(job.id, payload, false);
      undo.reset(val);
    },
  });

  // Rendering --------------------------------------------------------------
  if (err) {
    return (
      <div className="glass rounded-2xl p-4 text-xs text-rose-300">
        {t("common2.loading_failed", { label: t("common2.load_lyrics"), err })}
      </div>
    );
  }
  if (!raw) return null;
  if (!raw.available) {
    return (
      <div className="glass rounded-2xl p-6 text-center space-y-1">
        <div className="text-sm font-semibold text-fg">{t("lyrics_empty.title")}</div>
        <div className="text-[12px] text-fg-muted">
          {t("lyrics_empty.hint")}
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-4"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Mic className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("lyrics_panel2.title")}</span>
        <span className="mono text-[11px] text-fg-muted inline-flex items-center gap-2 ml-1">
          <Languages className="size-3" />
          {raw.language ?? "?"}
        </span>
        <span className="ml-auto inline-flex items-center gap-3">
          <ConfidenceSummary avg={avgConf} count={words.length} label={t("lyrics_panel2.confidence_label")} />
          <span className="inline-flex items-center gap-1 mono text-[11px] text-fg-muted">
            <button
              type="button"
              disabled={!undo.canUndo}
              onClick={undo.undo}
              title={t("common2.undo_title")}
              className="inline-flex items-center justify-center size-6 rounded hover:bg-white/5 text-fg-muted hover:text-fg disabled:opacity-30"
            >
              <Undo2 className="size-3.5" />
            </button>
            <button
              type="button"
              disabled={!undo.canRedo}
              onClick={undo.redo}
              title={t("common2.redo_title")}
              className="inline-flex items-center justify-center size-6 rounded hover:bg-white/5 text-fg-muted hover:text-fg disabled:opacity-30"
            >
              <Redo2 className="size-3.5" />
            </button>
          </span>
          {undo.dirty && autosave.status !== "saved" && (
            <span className="text-amber-300 mono text-[10px]">{t("common2.dirty")}</span>
          )}
          {autosave.status === "saving" && (
            <span className="text-cyan mono text-[10px]">{t("common2.saving")}</span>
          )}
          {autosave.status === "saved" && !undo.dirty && (
            <span className="text-emerald-300 mono text-[10px]">{t("common2.saved")}</span>
          )}
        </span>
      </div>

      {lowCount > 0 && (
        <div className="rounded-md px-2.5 py-1.5 text-[11px] text-amber-200 bg-amber-400/10 ring-1 ring-amber-400/20 inline-flex items-center gap-2">
          <AlertTriangle className="size-3.5" />
          {t("lyrics_panel2.low_count", { count: lowCount })}
        </div>
      )}

      {/* Verse tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {verses.map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setActiveVerse(v)}
            className={cn(
              "px-3 py-1 rounded-full text-xs transition-all",
              v === activeVerse
                ? "bg-cyan/20 text-cyan ring-1 ring-cyan/40"
                : "bg-white/5 text-fg-muted hover:text-fg",
            )}
          >
            {t("lyrics_panel2.verse_n", { n: v })}
          </button>
        ))}
        <button
          type="button"
          onClick={addVerse}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] text-fg-muted hover:text-fg hover:bg-white/5"
          title={t("lyrics_panel2.add_verse_title")}
        >
          <Plus className="size-3" /> {t("lyrics_panel2.add_verse")}
        </button>
      </div>

      {/* Word grid */}
      <div className="rounded-xl bg-black/20 ring-1 ring-white/5 p-3 max-h-[420px] overflow-y-auto flex flex-wrap gap-1.5">
        {wordsForVerse.length === 0 && (
          <span className="text-[11px] text-fg-muted/70">{t("lyrics_panel2.verse_empty")}</span>
        )}
        {wordsForVerse.map((w) => (
          <WordChip
            key={w._i}
            value={w.word}
            confidence={w.confidence}
            startSec={w.start_sec}
            onChange={(text) => updateWord(w._i, { word: text })}
            onRemove={() => removeWord(w._i)}
            onSeek={() => onSeek?.(w.start_sec)}
          />
        ))}
      </div>

      {/* Optional per-verse translation. Lets the user paste a Korean
          rendering of an English verse (or vice-versa) for side-by-side
          display on the chord chart / projector. */}
      <details className="rounded-md bg-white/[0.02] ring-1 ring-white/5 px-3 py-2">
        <summary className="cursor-pointer text-[11px] mono uppercase tracking-[0.18em] text-fg-muted inline-flex items-center gap-1.5">
          <Languages className="size-3" /> {t("lyrics_panel2.translation_section", { verse: activeVerse })}
        </summary>
        <textarea
          value={translations[String(activeVerse)] || ""}
          onChange={(e) =>
            setTranslations((p) => ({ ...p, [String(activeVerse)]: e.target.value }))
          }
          placeholder={t("lyrics_panel2.translation_placeholder")}
          rows={3}
          className="mt-2 w-full text-[12px] bg-black/30 rounded-md p-2 text-fg placeholder:text-fg-muted/60 ring-1 ring-white/5 focus:outline-none focus:ring-cyan/40 resize-y"
        />
      </details>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="mono text-[11px] text-fg-muted">
          {lastSave ? (
            <span className="text-emerald-300">
              {lastSave.rebuilt ? t("common2.saved_with_pages", { pages: lastSave.pages }) : t("common2.saved_simple")}
            </span>
          ) : (
            <span>{t("common2.edit_and_save_hint")}</span>
          )}
        </div>
        <div className="ml-auto inline-flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => save(false)}
            className="inline-flex items-center gap-1.5 rounded-full h-9 px-3.5 text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg disabled:opacity-40"
          >
            <Save className="size-3.5" /> {t("common2.save_lyrics_only")}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => save(true)}
            className="inline-flex items-center gap-1.5 rounded-full h-9 px-4 text-xs font-medium bg-gradient-to-br from-cyan to-violet text-white disabled:opacity-40"
          >
            {busy ? (
              <>
                <RefreshCw className="size-3.5 animate-spin" /> {t("common2.rebuilding")}
              </>
            ) : (
              <>
                <RefreshCw className="size-3.5" /> {t("common2.save_and_rebuild")}
              </>
            )}
          </button>
        </div>
      </div>

      <div className="text-[10px] text-fg-muted/70 leading-relaxed">
        {t("lyrics_panel2.hint")}
      </div>
    </motion.div>
  );
}

function WordChip({ value, confidence, startSec, onChange, onRemove, onSeek }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef(null);

  useEffect(() => { setDraft(value); }, [value]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) onChange(draft);
  };
  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  return (
    <span className="group inline-flex items-stretch rounded-md bg-white/[0.025] ring-1 ring-white/8 hover:bg-white/5 transition-colors">
      <button
        type="button"
        onClick={onSeek}
        title={t("common2.jump_to_title", { time: formatDuration(startSec) })}
        className="mono text-[10px] text-fg-muted hover:text-fg px-1.5 self-center"
      >
        {formatDuration(startSec)}
      </button>

      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); commit(); }
            else if (e.key === "Escape") { e.preventDefault(); cancel(); }
          }}
          className="bg-transparent outline-none text-sm py-1 pr-1 w-[8ch]"
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-sm py-1 pr-1.5 inline-flex items-center"
        >
          <ConfidenceUnderline value={confidence}>
            {value || <span className="text-fg-muted/60 italic">∅</span>}
          </ConfidenceUnderline>
        </button>
      )}

      <button
        type="button"
        onClick={onRemove}
        title={t("common2.delete_word_title")}
        className="hidden group-hover:inline-flex items-center justify-center px-1 text-fg-muted/60 hover:text-rose-300"
      >
        <Trash2 className="size-3" />
      </button>
    </span>
  );
}
