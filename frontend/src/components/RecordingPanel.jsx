import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Mic, Square, Download, Trash2, Play, Pause, Award, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { gradePerformance } from "@/lib/api";
import { cn, formatDuration } from "@/lib/utils";

/**
 * Browser-side recording overlay for the practice/result page.
 *
 * Uses MediaRecorder (always available in modern Chromium/Firefox) to
 * capture the user's mic *while* an MR is playing through their speakers
 * or in-ears. We can't easily mix the MR + mic in-browser without WebRTC
 * loopback, so for now we just record the mic stream — the user plays
 * along to the existing audio in the room, and the recording is theirs
 * to use however they want (review, share, send to a teacher, etc.).
 *
 * All data lives in the browser. We never upload the recording.
 */
export function RecordingPanel({ job, onRecorded }) {
  const { t } = useTranslation();
  const [supported, setSupported] = useState(true);
  const [permission, setPermission] = useState("prompt");
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [blob, setBlob] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [grading, setGrading] = useState(false);
  const [grade, setGrade] = useState(null);
  const [gradeErr, setGradeErr] = useState(null);

  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const tickRef = useRef(null);
  const previewRef = useRef(null);

  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia
        || typeof MediaRecorder === "undefined") {
      setSupported(false);
    }
  }, []);

  useEffect(() => () => stopAll(), []);     // cleanup on unmount

  const stopAll = () => {
    try { recorderRef.current?.stop(); } catch { /* ignore */ }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (tickRef.current) clearInterval(tickRef.current);
  };

  const start = async () => {
    setBlob(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, sampleRate: 48000 },
        video: false,
      });
      streamRef.current = stream;
      setPermission("granted");
      const rec = new MediaRecorder(stream, { mimeType: _preferredMimeType() });
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = () => {
        const mime = rec.mimeType || "audio/webm";
        const b = new Blob(chunksRef.current, { type: mime });
        const url = URL.createObjectURL(b);
        setBlob(b);
        setPreviewUrl(url);
        onRecorded?.(b, url);
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
      setElapsed(0);
      tickRef.current = setInterval(() => setElapsed((t) => t + 1), 1000);
    } catch (e) {
      setPermission("denied");
      setSupported(false);
      console.warn("mic permission denied", e);
    }
  };

  const stop = () => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (tickRef.current) clearInterval(tickRef.current);
    setRecording(false);
  };

  const togglePreview = () => {
    const el = previewRef.current;
    if (!el) return;
    if (el.paused) { el.play(); setPreviewing(true); }
    else { el.pause(); setPreviewing(false); }
  };

  const reset = () => {
    setBlob(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setGrade(null);
    setGradeErr(null);
  };

  const submitGrade = async () => {
    if (!blob || !job?.id || grading) return;
    setGrading(true); setGradeErr(null); setGrade(null);
    try {
      const res = await gradePerformance(job.id, blob);
      setGrade(res);
    } catch (e) {
      setGradeErr(e.message);
    } finally {
      setGrading(false);
    }
  };

  const download = () => {
    if (!blob || !previewUrl) return;
    const ext = (blob.type.split("/")[1] || "webm").split(";")[0];
    const a = document.createElement("a");
    a.href = previewUrl;
    a.download = `rechord_recording_${Date.now()}.${ext}`;
    a.click();
  };

  if (!supported) {
    return (
      <div className="glass rounded-2xl p-4 text-[12px] text-fg-muted">
        {t("recording2.unsupported")}
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-4 space-y-3"
    >
      <div className="flex items-center gap-2">
        <Mic className="size-4 text-magenta" />
        <span className="text-sm font-semibold">{t("recording2.title")}</span>
        {recording && (
          <span className="mono text-[11px] text-rose-300 inline-flex items-center gap-1">
            <span className="size-1.5 rounded-full bg-rose-400 animate-pulse" />
            REC {formatDuration(elapsed)}
          </span>
        )}
        <span className="ml-auto text-[10px] text-fg-muted/70">{t("recording2.local_only")}</span>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {!recording ? (
          <button
            type="button"
            onClick={start}
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full text-xs bg-gradient-to-br from-magenta to-violet text-white hover:shadow-[0_10px_30px_-12px_rgba(236,72,153,0.6)]"
          >
            <Mic className="size-3.5" /> {t("recording2.start")}
          </button>
        ) : (
          <button
            type="button"
            onClick={stop}
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full text-xs bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 ring-1 ring-rose-500/30"
          >
            <Square className="size-3.5" /> {t("recording2.stop")}
          </button>
        )}

        {previewUrl && (
          <>
            <audio
              ref={previewRef}
              src={previewUrl}
              onEnded={() => setPreviewing(false)}
            />
            <button
              type="button"
              onClick={togglePreview}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
            >
              {previewing ? <Pause className="size-3.5" /> : <Play className="size-3.5 ml-0.5" />}
              {t("recording2.preview")}
            </button>
            <button
              type="button"
              onClick={download}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-full text-xs bg-violet/15 hover:bg-violet/25 text-violet ring-1 ring-violet/30"
            >
              <Download className="size-3.5" /> {t("recording2.save")}
            </button>
            {job && (
              <button
                type="button"
                onClick={submitGrade}
                disabled={grading}
                title={t("recording2.score_title")}
                className="inline-flex items-center gap-1.5 h-9 px-3 rounded-full text-xs bg-violet/15 hover:bg-violet/25 text-violet ring-1 ring-violet/30 disabled:opacity-40"
              >
                {grading ? <Loader2 className="size-3.5 animate-spin" /> : <Award className="size-3.5" />}
                {t("recording2.score")}
              </button>
            )}
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-full text-xs text-fg-muted hover:text-rose-300 hover:bg-rose-500/10"
            >
              <Trash2 className="size-3.5" /> {t("recording2.discard")}
            </button>
          </>
        )}
      </div>

      {gradeErr && (
        <div className="rounded-md px-2.5 py-1.5 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
          {t("recording2.score_failed", { err: gradeErr })}
        </div>
      )}

      {grade && (
        <div className="rounded-xl bg-gradient-to-br from-violet/10 to-magenta/10 ring-1 ring-violet/20 p-3 space-y-2">
          <div className="flex items-center gap-3">
            <div className="text-3xl font-bold gradient-text mono">{grade.overall_score}</div>
            <div className="flex-1 mono text-[11px] text-fg-muted">
              <div>{t("recording2.score_pitch")} · <span className="text-fg">{Math.round(grade.pitch_accuracy * 100)}%</span></div>
              <div>{t("recording2.score_timing")} · <span className="text-fg">{Math.round(grade.timing_offset_ms)} ms</span></div>
            </div>
          </div>
          {grade.notes?.length > 0 && (
            <ul className="text-[11px] text-fg/85 space-y-0.5 ml-1">
              {grade.notes.map((n, i) => (
                <li key={i} className="flex gap-1.5"><span className="text-violet shrink-0">•</span>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className={cn(
        "text-[10px] leading-relaxed",
        permission === "denied" ? "text-rose-300" : "text-fg-muted/70",
      )}>
        {t("recording2.hint")}
      </div>
    </motion.div>
  );
}

function _preferredMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", ""];
  for (const m of candidates) {
    if (!m || MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}
