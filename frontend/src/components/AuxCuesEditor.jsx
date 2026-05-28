import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Piano, Plus, Trash2, Save, RefreshCw, Sparkles, Undo2, Redo2,
  Filter, AlertTriangle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { autoAuxCues, getAuxCues, saveAuxCues } from "@/lib/api";
import { useUndoStack } from "@/lib/useUndoStack";
import { useAutosave } from "@/lib/useAutosave";
import { cn } from "@/lib/utils";

// Patch labels resolve via t("aux_patches.<id>") at render so the dropdown
// follows the active locale. FX stays English (acronym, no localisation needed).
const PATCHES = [
  { id: "organ",        labelKey: "aux_patches.organ",        accent: "violet"  },
  { id: "pad",          labelKey: "aux_patches.pad",          accent: "cyan"    },
  { id: "synth_lead",   labelKey: "aux_patches.synth_lead",   accent: "magenta" },
  { id: "string",       labelKey: "aux_patches.string",       accent: "cyan"    },
  { id: "brass",        labelKey: "aux_patches.brass",        accent: "amber"   },
  { id: "bell",         labelKey: "aux_patches.bell",         accent: "amber"   },
  { id: "piano",        labelKey: "aux_patches.piano",        accent: "violet"  },
  { id: "epiano",       labelKey: "aux_patches.epiano",       accent: "violet"  },
  { id: "choir",        labelKey: "aux_patches.choir",        accent: "cyan"    },
  { id: "guitar_atmos", labelKey: "aux_patches.guitar_atmos", accent: "magenta" },
  { id: "fx",           label: "FX",                          accent: "magenta" },
  { id: "silent",       labelKey: "aux_patches.silent",       accent: "fg-muted"},
];

const ACCENT_RING = {
  violet: "ring-violet/45 bg-violet/15 text-violet",
  cyan: "ring-cyan/45 bg-cyan/15 text-cyan",
  magenta: "ring-magenta/45 bg-magenta/15 text-magenta",
  amber: "ring-amber/45 bg-amber/15 text-amber",
  "fg-muted": "ring-white/15 bg-white/5 text-fg-muted",
};

const PATCH_LOOKUP = Object.fromEntries(PATCHES.map((p) => [p.id, p]));

/**
 * AUX / 세컨건반 패치 큐 편집기.
 *   - 마디 범위 + 음색 + 메모 한 줄.
 *   - 저장 시 악보 위에 "AUX · 오르간" 같은 텍스트 어노테이션이 박힘.
 */
export function AuxCuesEditor({ job }) {
  const { t } = useTranslation();
  const initial = useMemo(() => [], []);
  const undo = useUndoStack(initial);
  const cues = undo.state;
  const setCues = undo.set;

  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lastSave, setLastSave] = useState(null);
  const [autoBusy, setAutoBusy] = useState(false);
  const [lastAuto, setLastAuto] = useState(null);
  const [showCleanupDialog, setShowCleanupDialog] = useState(false);
  const [lastCleanup, setLastCleanup] = useState(null);

  // Confidence-bucketed counts for the bulk-cleanup affordance.
  const confidenceStats = useMemo(() => {
    let high = 0, mid = 0, low = 0, unknown = 0;
    for (const c of cues) {
      const v = typeof c.confidence === "number" ? c.confidence : null;
      if (v == null) unknown++;
      else if (v >= 0.55) high++;
      else if (v >= 0.18) mid++;
      else low++;
    }
    return { high, mid, low, unknown };
  }, [cues]);
  const hasUnreliableCues = confidenceStats.low > 0 || confidenceStats.mid > 0;

  useEffect(() => {
    getAuxCues(job.id)
      .then((r) => {
        if (Array.isArray(r.cues)) {
          undo.reset(r.cues.map((c) => ({
            start_measure: Number(c.start_measure ?? 1),
            end_measure: Number(c.end_measure ?? c.start_measure ?? 1),
            patch: String(c.patch ?? "pad"),
            note: String(c.note ?? ""),
            confidence: c.confidence != null ? Number(c.confidence) : null,
            runner_up: c.runner_up != null ? String(c.runner_up) : null,
          })));
        }
      })
      .catch((e) => setErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  const update = (i, patch) =>
    setCues((prev) => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  const remove = (i) => setCues((prev) => prev.filter((_, idx) => idx !== i));
  const add = () => {
    const last = cues[cues.length - 1];
    const start = last ? last.end_measure + 1 : 1;
    setCues((prev) => [...prev, {
      start_measure: start, end_measure: start + 7,
      patch: "pad", note: "",
    }]);
  };

  /**
   * Bulk cleanup by confidence:
   *   action="drop"    — remove every cue with confidence < threshold
   *   action="silent"  — convert sub-threshold cues to the "silent" patch
   *                      (preserves measure spans so timing edits remain)
   *
   * Default threshold 0.18 matches MIN_CONFIDENCE_FOR_CUE on the backend.
   */
  const runCleanup = (action, threshold) => {
    const before = cues.length;
    let removed = 0, converted = 0;
    const after = [];
    for (const c of cues) {
      const v = typeof c.confidence === "number" ? c.confidence : null;
      const isLow = v != null && v < threshold;
      if (!isLow) {
        after.push(c);
      } else if (action === "drop") {
        removed++;
      } else {
        after.push({ ...c, patch: "silent",
                     note: `(자동 정리 · conf ${v?.toFixed(2) ?? "?"})` });
        converted++;
      }
    }
    setCues(after);
    setLastCleanup({
      at: Date.now(), action, threshold, before,
      removed, converted, kept: after.length,
    });
    setShowCleanupDialog(false);
  };

  const runAuto = async () => {
    if (autoBusy) return;
    setAutoBusy(true);
    setErr(null);
    try {
      const res = await autoAuxCues(job.id, { save: false });
      const incoming = (res.cues || []).map((c) => ({
        start_measure: Number(c.start_measure ?? 1),
        end_measure: Number(c.end_measure ?? c.start_measure ?? 1),
        patch: String(c.patch ?? "pad"),
        note: String(c.note ?? ""),
        confidence: c.confidence != null ? Number(c.confidence) : null,
        runner_up: c.runner_up != null ? String(c.runner_up) : null,
      }));
      setCues(incoming);
      setLastAuto({
        at: Date.now(),
        mode: res.mode,
        dbSize: res.db_size,
        cueCount: res.cue_count,
      });
    } catch (e) {
      setErr(e.message);
    } finally {
      setAutoBusy(false);
    }
  };

  const save = async (rebuild) => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await saveAuxCues(job.id, cues, rebuild);
      undo.reset(cues);
      setLastSave({ at: Date.now(), rebuilt: !!res.rebuilt, pages: res.pages });
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Autosave: fire 4 seconds after the user stops editing. Never triggers
  // a score rebuild (rebuild=false) — that's reserved for explicit Save.
  const autosave = useAutosave({
    value: cues,
    dirty: undo.dirty,
    interval: 4000,
    enabled: cues.length > 0,
    onSave: async (val) => { await saveAuxCues(job.id, val, false); undo.reset(val); },
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-4"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Piano className="size-4 text-violet" />
        <span className="text-sm font-semibold">{t("aux2.title")}</span>
        <span className="mono text-[11px] text-fg-muted">{cues.length}개</span>
        <span className="ml-auto inline-flex items-center gap-1">
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
          {undo.dirty && autosave.status !== "saved" && (
            <span className="text-amber-300 mono text-[10px] ml-1">{t("common2.dirty")}</span>
          )}
          {autosave.status === "saving" && (
            <span className="text-cyan mono text-[10px] ml-1">{t("common2.saving")}</span>
          )}
          {autosave.status === "saved" && !undo.dirty && (
            <span className="text-emerald-300 mono text-[10px] ml-1">{t("common2.saved")}</span>
          )}
        </span>
        <button
          type="button"
          disabled={autoBusy || busy}
          onClick={runAuto}
          title={t("aux2.estimate_tooltip")}
          className="inline-flex items-center gap-1.5 rounded-full h-7 px-3 text-[11px] ring-1 ring-violet/40 bg-violet/10 text-violet hover:bg-violet/20 disabled:opacity-40"
        >
          {autoBusy ? (
            <>
              <RefreshCw className="size-3 animate-spin" /> {t("aux2.estimating")}
            </>
          ) : (
            <>
              <Sparkles className="size-3" /> {t("aux2.ai_draft")}
            </>
          )}
        </button>
        {hasUnreliableCues && (
          <button
            type="button"
            onClick={() => setShowCleanupDialog(true)}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-full h-7 px-3 text-[11px] ring-1 ring-amber-400/40 bg-amber-400/10 text-amber-200 hover:bg-amber-400/20 disabled:opacity-40"
            title="신뢰도 낮은 큐 일괄 정리"
          >
            <Filter className="size-3" />
            저신뢰 정리 ({confidenceStats.low + confidenceStats.mid})
          </button>
        )}
      </div>

      {lastCleanup && (
        <div className="mono text-[10px] text-amber-200/90 rounded-md px-2 py-1 bg-amber-400/5 ring-1 ring-amber-400/20">
          정리 완료: {lastCleanup.before}개 →
          {" "}{lastCleanup.kept}개 유지,
          {" "}{lastCleanup.removed}개 제거,
          {" "}{lastCleanup.converted}개 silent로 변환
          {" "}(threshold {lastCleanup.threshold})
        </div>
      )}

      {showCleanupDialog && (
        <CleanupDialog
          stats={confidenceStats}
          onConfirm={runCleanup}
          onCancel={() => setShowCleanupDialog(false)}
        />
      )}

      {lastAuto && (
        <div className="mono text-[10px] text-fg-muted/80 rounded-md px-2 py-1 bg-white/[0.03] ring-1 ring-white/5">
          {t("aux2.ai_done", { count: lastAuto.cueCount })} ·{" "}
          {lastAuto.mode === "reference_db"
            ? `reference DB (${lastAuto.dbSize.toLocaleString()} vectors)`
            : "zero-shot CLAP (DB 미빌드)"}
        </div>
      )}

      {err && (
        <div className="rounded-md px-2.5 py-1.5 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
          {err}
        </div>
      )}

      {/* Cue rows */}
      <div className="space-y-2">
        {cues.length === 0 && (
          <div className="text-[12px] text-fg-muted/80 leading-relaxed rounded-lg bg-white/3 ring-1 ring-white/5 p-3">
            {t("aux2.no_cues_yet")}
          </div>
        )}
        {cues.map((c, i) => {
          const p = PATCH_LOOKUP[c.patch] || PATCHES[0];
          // Confidence visual: emerald ≥0.55, amber 0.18~0.55, rose <0.18
          const conf = typeof c.confidence === "number" ? c.confidence : null;
          const confColor = conf == null ? "" :
            conf >= 0.55 ? "text-emerald-300 bg-emerald-400/10 ring-emerald-400/30" :
            conf >= 0.18 ? "text-amber-300 bg-amber-400/10 ring-amber-400/30" :
                           "text-rose-300 bg-rose-400/10 ring-rose-400/30";
          return (
            <div
              key={i}
              className={cn(
                "rounded-xl bg-white/[0.025] ring-1 ring-white/5 p-3 grid grid-cols-12 gap-2 items-center",
                conf != null && conf < 0.18 && "ring-rose-400/20",
              )}
            >
              {conf != null && (
                <div className="col-span-12 flex items-center gap-2 -mb-1">
                  <span className={cn(
                    "mono text-[10px] px-1.5 py-0.5 rounded ring-1",
                    confColor,
                  )}>
                    conf {(conf * 100).toFixed(0)}%
                  </span>
                  {c.runner_up && conf < 0.55 && (
                    <span className="text-[10px] text-fg-muted/70">
                      차순위: <span className="mono text-fg-muted">{c.runner_up}</span>
                      <span className="opacity-60"> · 사용자 확인 권장</span>
                    </span>
                  )}
                </div>
              )}
              <div className="col-span-12 sm:col-span-3 flex items-center gap-1.5 mono text-xs">
                <span className="text-fg-muted/80">{t("aux2.bar_label")}</span>
                <input
                  type="number"
                  min="1"
                  value={c.start_measure}
                  onChange={(e) => update(i, { start_measure: Math.max(1, Number(e.target.value)) })}
                  className="w-14 bg-black/30 border border-white/10 rounded px-1.5 py-0.5 text-fg text-center"
                />
                <span className="text-fg-muted/80">{t("aux2.bar_range_to")}</span>
                <input
                  type="number"
                  min="1"
                  value={c.end_measure}
                  onChange={(e) => update(i, { end_measure: Math.max(c.start_measure, Number(e.target.value)) })}
                  className="w-14 bg-black/30 border border-white/10 rounded px-1.5 py-0.5 text-fg text-center"
                />
              </div>

              <div className="col-span-12 sm:col-span-4">
                <div className="flex flex-wrap gap-1">
                  {PATCHES.slice(0, 6).map((opt) => {
                    const on = c.patch === opt.id;
                    const label = opt.labelKey ? t(opt.labelKey) : opt.label;
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        onClick={() => update(i, { patch: opt.id })}
                        className={cn(
                          "px-2 py-0.5 rounded-full text-[11px] transition-all ring-1",
                          on ? ACCENT_RING[opt.accent] : "ring-white/5 bg-white/3 text-fg-muted hover:text-fg",
                        )}
                      >
                        {label}
                      </button>
                    );
                  })}
                  <select
                    value={PATCHES.slice(0, 6).find((x) => x.id === c.patch) ? "" : c.patch}
                    onChange={(e) => e.target.value && update(i, { patch: e.target.value })}
                    className="bg-black/30 border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-fg-muted"
                  >
                    <option value="">{t("aux2.patch_other")}</option>
                    {PATCHES.slice(6).map((opt) => (
                      <option key={opt.id} value={opt.id}>{opt.labelKey ? t(opt.labelKey) : opt.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <input
                value={c.note}
                onChange={(e) => update(i, { note: e.target.value })}
                placeholder={t("aux2.patch_placeholder")}
                className="col-span-11 sm:col-span-4 bg-black/30 border border-white/10 rounded px-2 py-1 text-[12px] text-fg placeholder:text-fg-muted/60 focus:outline-none focus:ring-1 focus:ring-violet/40"
              />

              <button
                type="button"
                onClick={() => remove(i)}
                title={t("aux2.delete_cue_title")}
                className="col-span-1 inline-flex items-center justify-center text-fg-muted hover:text-rose-300 size-7 rounded-md hover:bg-white/5"
              >
                <Trash2 className="size-3.5" />
              </button>

              <div className="col-span-12 mono text-[10px] text-fg-muted/70">
                {t("aux2.score_label")} <span className="text-fg">AUX · {(() => {
                  const pp = PATCH_LOOKUP[c.patch] || p;
                  return pp.labelKey ? t(pp.labelKey) : pp.label;
                })()}</span>
                {c.note && <span> — {c.note}</span>}
              </div>
            </div>
          );
        })}

        <button
          type="button"
          onClick={add}
          className="w-full rounded-xl py-2.5 text-xs text-fg-muted hover:text-fg ring-1 ring-dashed ring-white/10 hover:ring-violet/40 hover:bg-white/3 transition-all inline-flex items-center justify-center gap-1.5"
        >
          <Plus className="size-3.5" /> {t("aux2.add_cue")}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <div className="mono text-[11px] text-fg-muted">
          {lastSave ? (
            <span className="text-emerald-300">
              {lastSave.rebuilt ? t("common2.saved_with_pages", { pages: lastSave.pages }) : t("common2.saved_simple")}
            </span>
          ) : (
            <span>{t("common2.rebuild_score_for_vocals_hint")}</span>
          )}
        </div>
        <div className="ml-auto inline-flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => save(false)}
            className="inline-flex items-center gap-1.5 rounded-full h-9 px-3.5 text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg disabled:opacity-40"
          >
            <Save className="size-3.5" /> {t("common2.save_aux_only")}
          </button>
          <button
            type="button"
            disabled={busy || cues.length === 0}
            onClick={() => save(true)}
            className="inline-flex items-center gap-1.5 rounded-full h-9 px-4 text-xs font-medium bg-gradient-to-br from-violet to-magenta text-white disabled:opacity-40"
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
        {t("aux2.hint")}
      </div>
    </motion.div>
  );
}


/**
 * Modal dialog for bulk confidence cleanup. Lets the user choose a
 * threshold (0.18 / 0.35 / 0.55 — backend bands) and an action (drop
 * or convert-to-silent). Two-step confirmation so the user can't lose
 * cues accidentally.
 */
function CleanupDialog({ stats, onConfirm, onCancel }) {
  const [threshold, setThreshold] = useState(0.18);
  const [action, setAction] = useState("silent");

  // Preview: how many cues each option would affect.
  const previewCount = () => {
    if (threshold <= 0.18) return stats.low;
    if (threshold <= 0.35) return stats.low + Math.round(stats.mid * 0.5);
    if (threshold <= 0.55) return stats.low + stats.mid;
    return stats.low + stats.mid + stats.high;       // shouldn't reach here
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onCancel}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={(e) => e.stopPropagation()}
        className="glass rounded-2xl p-6 max-w-md w-full space-y-4 ring-1 ring-amber-400/30 bg-amber-400/5"
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="size-4 text-amber-300" />
          <span className="text-sm font-semibold">저신뢰 큐 일괄 정리</span>
        </div>

        <div className="text-[11px] text-fg-muted/90 leading-relaxed">
          AUX 큐 중 신뢰도가 낮은 항목을 한 번에 정리합니다.
          현재 분포 — 높음 <span className="mono text-emerald-300">{stats.high}</span>
          {" "}· 중간 <span className="mono text-amber-300">{stats.mid}</span>
          {" "}· 낮음 <span className="mono text-rose-300">{stats.low}</span>
          {" "}· 측정 없음 <span className="mono text-fg-muted">{stats.unknown}</span>
        </div>

        <div className="space-y-2">
          <div className="text-[11px] text-fg-muted">신뢰도 임계값</div>
          <div className="flex gap-1.5">
            {[
              { v: 0.18, label: "엄격 0.18", hint: "백엔드 기본값" },
              { v: 0.35, label: "표준 0.35", hint: "권장" },
              { v: 0.55, label: "강함 0.55", hint: "확신 큐만 유지" },
            ].map(({ v, label, hint }) => (
              <button
                key={v}
                type="button"
                onClick={() => setThreshold(v)}
                className={cn(
                  "flex-1 rounded-md px-2 py-1.5 text-[11px] ring-1 transition-colors",
                  threshold === v
                    ? "ring-amber-300/60 bg-amber-400/20 text-amber-100"
                    : "ring-white/10 bg-white/3 text-fg-muted hover:text-fg",
                )}
                title={hint}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <div className="text-[11px] text-fg-muted">작업 방식</div>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => setAction("silent")}
              className={cn(
                "flex-1 rounded-md px-2 py-1.5 text-[11px] ring-1 transition-colors",
                action === "silent"
                  ? "ring-cyan/60 bg-cyan/15 text-cyan"
                  : "ring-white/10 bg-white/3 text-fg-muted hover:text-fg",
              )}
            >
              silent로 변환
            </button>
            <button
              type="button"
              onClick={() => setAction("drop")}
              className={cn(
                "flex-1 rounded-md px-2 py-1.5 text-[11px] ring-1 transition-colors",
                action === "drop"
                  ? "ring-rose-400/60 bg-rose-400/15 text-rose-200"
                  : "ring-white/10 bg-white/3 text-fg-muted hover:text-fg",
              )}
            >
              완전 제거
            </button>
          </div>
          <div className="text-[10px] text-fg-muted/70 leading-relaxed">
            {action === "silent"
              ? "마디 범위는 유지하되 \"silent\" 패치로 표시합니다. "
                + "이후 사용자가 수동으로 음색을 지정할 수 있습니다."
              : "큐를 완전히 삭제합니다. 마디 범위도 함께 사라집니다."}
          </div>
        </div>

        <div className="rounded-md bg-black/30 px-3 py-2 text-[11px] text-fg-muted/90">
          영향받는 큐 약 <span className="mono text-amber-200">{previewCount()}</span>개
        </div>

        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md h-8 px-3 text-[11px] ring-1 ring-white/10 text-fg-muted hover:text-fg hover:bg-white/5"
          >
            취소
          </button>
          <button
            type="button"
            onClick={() => onConfirm(action, threshold)}
            className="rounded-md h-8 px-3 text-[11px] ring-1 ring-amber-300/60 bg-amber-400/20 text-amber-100 hover:bg-amber-400/30"
          >
            정리 실행
          </button>
        </div>
      </motion.div>
    </div>
  );
}
