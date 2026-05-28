import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Loader2, AlertCircle, Cpu, Clock, X, WifiOff, RefreshCw } from "lucide-react";
import { openProgressSocket, cancelJob } from "@/lib/api";
import { useEta } from "@/lib/useEta";
import { cn } from "@/lib/utils";

// Stage IDs are stable backend identifiers; label/hint resolve via t().
const STAGES = [
  { id: "ingest",    labelKey: "progress.stage_ingest_label",    hintKey: "progress.stage_ingest_hint" },
  { id: "decode",    labelKey: "progress.stage_decode_label",    hintKey: "progress.stage_decode_hint" },
  { id: "separate",  labelKey: "progress.stage_separate_label",  hintKey: "progress.stage_separate_hint" },
  { id: "ensemble",  labelKey: "progress.stage_ensemble_label",  hintKey: "progress.stage_ensemble_hint" },
  { id: "karaoke",   labelKey: "progress.stage_karaoke_label",   hintKey: "progress.stage_karaoke_hint" },
  { id: "analyze",   labelKey: "progress.stage_analyze_label",   hintKey: "progress.stage_analyze_hint" },
  { id: "transform", labelKey: "progress.stage_transform_label", hintKey: "progress.stage_transform_hint" },
  { id: "monitor",   labelKey: "progress.stage_monitor_label",   hintKey: "progress.stage_monitor_hint" },
  { id: "lyrics",    labelKey: "progress.stage_lyrics_label",    hintKey: "progress.stage_lyrics_hint" },
  { id: "score",     labelKey: "progress.stage_score_label",     hintKey: "progress.stage_score_hint" },
  { id: "encode",    labelKey: "progress.stage_encode_label",    hintKey: "progress.stage_encode_hint" },
];

/**
 * Stage-aware progress card. Three big improvements over v0:
 *   - ETA: stage-weighted remaining time, learns from observed durations.
 *   - Stage tooltips: hover any stage chip to see what it does.
 *   - Animated pulse on the active stage with an icon, not just a colour.
 *
 * Cancel button is a placeholder until backend exposes DELETE /jobs/{id}.
 */
export function ProgressPanel({ job, onDone }) {
  const { t } = useTranslation();
  const [progress, setProgress] = useState(job.progress);
  const [stage, setStage] = useState(job.stage);
  const [message, setMessage] = useState(job.message);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(job.status);
  const [wsState, setWsState] = useState({ state: "connecting", attempt: 0, maxAttempts: 6 });
  const logRef = useRef(null);

  useEffect(() => {
    if (job.status === "done" || job.status === "error") {
      setStatus(job.status);
      return;
    }
    const ws = openProgressSocket(
      job.id,
      (ev) => {
        if (ev.type === "ping") return;
        setStage(ev.stage);
        setProgress(ev.progress);
        setMessage(ev.message);
        setLogs((prev) => [...prev, ev].slice(-200));
        if (ev.type === "done") {
          setStatus("done");
          onDone?.();
        } else if (ev.type === "error") {
          setStatus("error");
        }
      },
      null,
      (state, detail) => setWsState({ state, ...(detail || {}) }),
    );
    return () => ws.close();
  }, [job.id, job.status, onDone]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const reachedIdx = STAGES.findIndex((s) => s.id === stage);
  const done = status === "done";
  const err = status === "error";

  const liveJob = useMemo(
    () => ({ ...job, stage, progress, status }),
    [job, stage, progress, status],
  );
  const { elapsedText, remainingText } = useEta(liveJob, logs);

  return (
    <div className="glass rounded-2xl p-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {done ? (
            <CheckCircle2 className="size-5 text-emerald-400 shrink-0" />
          ) : err ? (
            <AlertCircle className="size-5 text-rose-400 shrink-0" />
          ) : (
            <Loader2 className="size-5 text-violet animate-spin shrink-0" />
          )}
          <div className="min-w-0">
            <div className="text-sm font-semibold">
              {done ? t("progress.status_done") : err ? t("progress.status_error") : t("progress.status_running")}
            </div>
            <div className="text-[11px] text-fg-muted truncate" title={message}>
              {message || t("progress.status_ready")}
            </div>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="mono text-2xl text-fg leading-none">
            {Math.round(progress * 100)}%
          </div>
          {!done && !err && (
            <div className="mono text-[10px] text-fg-muted mt-0.5 inline-flex items-center gap-1">
              <Clock className="size-2.5" />
              <span>{t("progress.elapsed")} {elapsedText}</span>
              <span className="text-fg-muted/60">·</span>
              <span>{t("progress.remaining")} ~{remainingText}</span>
            </div>
          )}
        </div>
        {!done && !err && (
          <button
            type="button"
            onClick={async () => {
              if (!confirm(t("progress.cancel_confirm"))) return;
              try { await cancelJob(job.id); } catch { /* ignore */ }
            }}
            title={t("progress.cancel_title")}
            className="inline-flex items-center justify-center size-8 rounded-full hover:bg-rose-500/15 text-fg-muted hover:text-rose-300"
            aria-label={t("progress.cancel_title")}
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      {!done && !err && (wsState.state === "reconnecting" || wsState.state === "failed") && (
        <div
          role="status"
          aria-live="polite"
          className={cn(
            "flex items-center gap-2 px-3 py-2 rounded-lg text-[11px]",
            wsState.state === "failed"
              ? "bg-rose-500/10 text-rose-300 ring-1 ring-rose-500/30"
              : "bg-amber-400/10 text-amber-200 ring-1 ring-amber-400/30",
          )}
        >
          {wsState.state === "failed" ? (
            <WifiOff className="size-3.5 shrink-0" />
          ) : (
            <RefreshCw className="size-3.5 shrink-0 animate-spin" />
          )}
          <span className="flex-1">
            {wsState.state === "failed"
              ? t("progress.ws_failed")
              : t("progress.ws_reconnecting", {
                  attempt: wsState.attempt || 1,
                  max: wsState.maxAttempts || 6,
                })}
          </span>
          {wsState.state === "failed" && (
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-2 py-0.5 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-100 text-[10px]"
            >
              {t("progress.ws_reload")}
            </button>
          )}
        </div>
      )}

      <div className="h-2 rounded-full bg-white/5 overflow-hidden">
        <motion.div
          className={cn(
            "h-full bg-gradient-to-r",
            done ? "from-emerald-400 to-cyan"
              : err ? "from-rose-500 to-magenta"
              : "from-violet via-cyan to-magenta",
          )}
          animate={{ width: `${progress * 100}%` }}
          transition={{ ease: "easeOut", duration: 0.35 }}
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {STAGES.map((s, idx) => {
          const isActive = s.id === stage && !done && !err;
          const isReached = idx <= reachedIdx || done;
          return (
            <span
              key={s.id}
              title={t(s.hintKey)}
              className={cn(
                "px-2.5 py-1 rounded-full text-[11px] transition-all flex items-center gap-1.5 cursor-help",
                isActive && "bg-violet/20 text-violet ring-1 ring-violet/40 animate-pulseGlow",
                !isActive && isReached && "bg-white/10 text-fg",
                !isActive && !isReached && "bg-white/5 text-fg-muted/60",
              )}
            >
              {isActive && <Cpu className="size-3" />}
              {!isActive && isReached && (
                <span className="size-1.5 rounded-full bg-emerald-400" />
              )}
              {t(s.labelKey)}
            </span>
          );
        })}
      </div>

      <div
        ref={logRef}
        className="h-32 overflow-y-auto rounded-xl bg-black/30 border border-white/5 p-3 mono text-[11px] leading-relaxed text-fg-muted"
      >
        <AnimatePresence initial={false}>
          {logs.length === 0 && (
            <div className="text-fg-muted/40 italic">{t("progress.waiting")}</div>
          )}
          {logs.filter((l) => l.type !== "ping").slice(-50).map((l, i) => (
            <motion.div
              key={`${l.ts}-${i}`}
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex gap-2"
            >
              <span className="text-violet/70 shrink-0">[{l.stage}]</span>
              <span className="truncate">{l.message}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
