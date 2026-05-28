import { useCallback, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Upload, File as FileIcon, X } from "lucide-react";
import { uploadFile } from "@/lib/api";
import { cn, formatBytes } from "@/lib/utils";

export function Uploader({ onUploaded, disabled }) {
  const { t } = useTranslation();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pct, setPct] = useState(0);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  const handleFile = useCallback(async (file) => {
    setError(null);
    setBusy(true);
    setPct(0);
    try {
      const info = await uploadFile(file, setPct);
      setResult(info);
      onUploaded(info);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [onUploaded]);

  return (
    <div className="space-y-3">
      <motion.div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (disabled) return;
          const f = e.dataTransfer.files?.[0];
          if (f) handleFile(f);
        }}
        onClick={() => !disabled && !busy && inputRef.current?.click()}
        whileHover={!disabled ? { y: -2 } : undefined}
        className={cn(
          "relative cursor-pointer select-none rounded-2xl p-8 glass border-dashed transition-all",
          dragging && "glow-violet scale-[1.01]",
          disabled && "opacity-50 cursor-not-allowed",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept="audio/*,video/*,.wav,.aiff,.aif,.flac,.alac,.mp3,.m4a,.aac,.ogg,.opus,.wma,.mp4,.mov,.mkv,.webm,.avi"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
          disabled={disabled || busy}
        />
        <div className="flex flex-col items-center text-center gap-2">
          <span className="inline-flex items-center justify-center size-14 rounded-2xl bg-gradient-to-br from-violet/20 to-cyan/20 text-violet">
            <Upload className="size-6" />
          </span>
          <div className="text-base font-semibold text-fg">
            {t("submit.drop_or_click")}
          </div>
          <div className="text-xs text-fg-muted">
            {t("submit.accepted_formats")}
          </div>
        </div>
      </motion.div>

      {busy && (
        <div className="rounded-xl p-4 glass">
          <div className="flex items-center justify-between text-sm">
            <span className="text-fg-muted">{t("submit.uploading")}</span>
            <span className="mono text-fg">{(pct * 100).toFixed(0)}%</span>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-white/5 overflow-hidden">
            <motion.div
              className="h-full bg-gradient-to-r from-violet to-cyan"
              animate={{ width: `${pct * 100}%` }}
              transition={{ ease: "easeOut", duration: 0.2 }}
            />
          </div>
        </div>
      )}

      {result && !busy && (
        <div className="rounded-xl p-4 glass flex items-start gap-3">
          <FileIcon className="size-5 text-cyan mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{result.filename}</div>
            <div className="text-xs text-fg-muted mono mt-1">
              {result.audio_codec} · {result.sample_rate} Hz ·{" "}
              {result.duration_sec.toFixed(1)}s · {formatBytes(result.size_bytes)}
            </div>
          </div>
          <button
            onClick={() => setResult(null)}
            className="p-1 rounded-md hover:bg-white/5 text-fg-muted"
            aria-label="clear"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-xl p-3 text-sm bg-rose-500/10 text-rose-200 border border-rose-500/20">
          {error}
        </div>
      )}
    </div>
  );
}
