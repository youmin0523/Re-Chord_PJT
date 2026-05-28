import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "react-i18next";
import {
  Library,
  Plus,
  Music,
  Search,
  Trash2,
  Folder,
  Edit3,
  ChevronDown,
  ChevronRight,
  Play,
  GripVertical,
} from "lucide-react";
import { useJobHistory } from "@/lib/useJobHistory";
import { EmptyState } from "@/components/ui/EmptyState";
import { SetlistWarnings } from "@/components/SetlistWarnings";
import { cn } from "@/lib/utils";

/**
 * Persistent sidebar listing past jobs + setlists.
 *
 * - Lives in localStorage, so no auth needed for Phase A.
 * - Jobs that no longer exist on the in-memory server are shown but marked
 *   "expired" — the user can still see they did them, just not re-open.
 * - Setlists group jobs (예: "예배 2026-05-25"); reorderable later.
 *
 * Renders inside <AppShell> as a collapsible right rail on lg+ screens;
 * collapses to an icon-only column on md, hides on sm (use /library route).
 */
export function JobLibrary({ compact = false }) {
  const { t } = useTranslation();
  const {
    items, setlists,
    remove, createSetlist, renameSetlist, deleteSetlist,
    addToSetlist, removeFromSetlist, reorderSetlist,
  } = useJobHistory();
  // Drag-reorder tracking. We hold (setlistId, dragFromIdx) in state so the
  // drop handler knows what to move.
  const [drag, setDrag] = useState(null);
  const [q, setQ] = useState("");
  const [openSetlists, setOpenSetlists] = useState({});

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return items;
    return items.filter((it) =>
      (it.title || "").toLowerCase().includes(term)
      || (it.id || "").toLowerCase().includes(term),
    );
  }, [items, q]);

  return (
    <aside className={cn("space-y-3", compact && "w-16")}>
      <div className="flex items-center gap-2">
        <Library className="size-4 text-violet" />
        {!compact && <span className="text-sm font-semibold">{t("library.title")}</span>}
        {!compact && <span className="ml-auto mono text-[10px] text-fg-muted">{items.length}</span>}
      </div>

      {!compact && (
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-fg-muted/60 pointer-events-none" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("library.search_placeholder")}
            className="w-full pl-7 pr-2 py-1.5 rounded-md bg-white/[0.03] ring-1 ring-white/5 text-[12px] focus:outline-none focus:ring-violet/40"
          />
        </div>
      )}

      {/* Setlists */}
      {!compact && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <Folder className="size-3 text-fg-muted" />
            <span className="text-[10px] mono uppercase tracking-[0.18em] text-fg-muted">{t("library.setlists")}</span>
            <button
              type="button"
              onClick={() => {
                const name = window.prompt(t("library.setlist_name_prompt"));
                if (name?.trim()) createSetlist(name.trim());
              }}
              title={t("library.new_setlist")}
              className="ml-auto inline-flex items-center justify-center size-5 rounded hover:bg-white/5 text-fg-muted hover:text-fg"
            >
              <Plus className="size-3" />
            </button>
          </div>
          {setlists.length === 0 && (
            <div className="text-[11px] text-fg-muted/70 px-1 leading-relaxed">
              {t("library.setlists_empty")}
            </div>
          )}
          {setlists.map((s) => {
            const open = openSetlists[s.id];
            const jobsInSet = s.jobIds
              .map((jid) => items.find((x) => x.id === jid))
              .filter(Boolean);
            return (
              <div key={s.id} className="rounded-md bg-white/[0.02] ring-1 ring-white/5 px-2 py-1.5">
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setOpenSetlists((p) => ({ ...p, [s.id]: !open }))}
                    className="text-fg-muted hover:text-fg"
                  >
                    {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
                  </button>
                  <span className="text-[12px] truncate flex-1" title={s.name}>{s.name}</span>
                  <span className="mono text-[10px] text-fg-muted">{s.jobIds.length}</span>
                  {s.jobIds.length > 0 && (
                    <Link
                      to={`/perform/setlist/${s.id}`}
                      title={t("library.perform_with_setlist")}
                      className="inline-flex items-center justify-center size-5 rounded hover:bg-violet/15 text-fg-muted hover:text-violet"
                    >
                      <Play className="size-3" />
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      const next = window.prompt(t("library.rename_prompt"), s.name);
                      if (next?.trim()) renameSetlist(s.id, next.trim());
                    }}
                    title={t("library.rename_setlist")}
                    className="inline-flex items-center justify-center size-5 rounded hover:bg-white/5 text-fg-muted hover:text-fg"
                  >
                    <Edit3 className="size-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(t("library.delete_setlist_confirm", { name: s.name }))) deleteSetlist(s.id);
                    }}
                    title={t("library.delete")}
                    className="inline-flex items-center justify-center size-5 rounded hover:bg-rose-500/10 text-fg-muted hover:text-rose-300"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>
                <AnimatePresence initial={false}>
                  {open && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="pt-2 pl-4 space-y-0.5">
                        {jobsInSet.length === 0 && (
                          <div className="text-[10px] text-fg-muted/60 italic">{t("library.no_songs")}</div>
                        )}
                        {jobsInSet.map((it, idx) => {
                          const isDragSource = drag?.setlistId === s.id && drag?.from === idx;
                          return (
                            <div
                              key={it.id}
                              draggable
                              onDragStart={(e) => {
                                setDrag({ setlistId: s.id, from: idx });
                                e.dataTransfer.effectAllowed = "move";
                              }}
                              onDragOver={(e) => {
                                if (drag?.setlistId === s.id) {
                                  e.preventDefault();
                                  e.dataTransfer.dropEffect = "move";
                                }
                              }}
                              onDrop={(e) => {
                                e.preventDefault();
                                if (drag?.setlistId === s.id && drag.from !== idx) {
                                  reorderSetlist(s.id, drag.from, idx);
                                }
                                setDrag(null);
                              }}
                              onDragEnd={() => setDrag(null)}
                              className={cn(
                                "flex items-center gap-0.5 group",
                                isDragSource && "opacity-40",
                              )}
                            >
                              <GripVertical
                                className="size-3 text-fg-muted/40 group-hover:text-fg-muted cursor-grab active:cursor-grabbing shrink-0"
                                aria-label={t("library.drag_to_reorder")}
                              />
                              <JobRow
                                item={it}
                                onRemove={() => removeFromSetlist(s.id, it.id)}
                                removeLabel={t("library.remove_from_set")}
                              />
                            </div>
                          );
                        })}
                        {jobsInSet.length >= 2 && (
                          <div className="pt-2 mt-2 border-t border-white/5">
                            <SetlistWarnings setlist={s} />
                          </div>
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      )}

      {/* Recent jobs */}
      {!compact && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <Music className="size-3 text-fg-muted" />
            <span className="text-[10px] mono uppercase tracking-[0.18em] text-fg-muted">{t("library.recent")}</span>
          </div>
          {filtered.length === 0 ? (
            <EmptyState
              size="sm"
              illustration="library"
              title={t("library.history_empty_title")}
              hint={t("library.history_empty_hint")}
              className="!p-3"
            />
          ) : (
            <div className="space-y-0.5 max-h-[58vh] overflow-y-auto pr-1">
              {filtered.map((it) => (
                <JobRow
                  key={it.id}
                  item={it}
                  onRemove={() => remove(it.id)}
                  removeLabel={t("library.remove_from_history")}
                  setlists={setlists}
                  onAddToSetlist={(sid) => addToSetlist(sid, it.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

function JobRow({ item, onRemove, removeLabel, setlists, onAddToSetlist }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const date = new Date(item.createdAt || Date.now());
  const dateStr = `${date.getMonth() + 1}/${date.getDate()}`;
  const title = item.title || item.id;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => navigate(`/job/${item.id}`)}
      onKeyDown={(e) => { if (e.key === "Enter") navigate(`/job/${item.id}`); }}
      className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-white/[0.04] cursor-pointer"
    >
      <div className="min-w-0 flex-1">
        <div className="text-[12px] text-fg truncate" title={title}>{title}</div>
        <div className="text-[10px] mono text-fg-muted/70">
          {dateStr} · {item.mode || "—"}
        </div>
      </div>
      {setlists && setlists.length > 0 && (
        <div className="hidden group-hover:block">
          <details className="text-[10px]">
            <summary
              onClick={(e) => e.stopPropagation()}
              className="cursor-pointer mono text-fg-muted hover:text-fg list-none"
            >
              {t("library.add_to_set")}
            </summary>
            <div className="absolute mt-1 z-10 bg-bg1 ring-1 ring-white/10 rounded-md p-1 min-w-[140px]">
              {setlists.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onAddToSetlist(s.id);
                  }}
                  className="w-full text-left px-2 py-1 rounded text-[11px] text-fg-muted hover:bg-white/5 hover:text-fg"
                >
                  + {s.name}
                </button>
              ))}
            </div>
          </details>
        </div>
      )}
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onRemove(); }}
        title={removeLabel}
        className="opacity-0 group-hover:opacity-100 inline-flex items-center justify-center size-5 rounded hover:bg-rose-500/10 text-fg-muted hover:text-rose-300"
      >
        <Trash2 className="size-3" />
      </button>
    </div>
  );
}
