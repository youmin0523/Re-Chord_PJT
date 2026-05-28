import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Send, Loader2, Paperclip, Link2, X as XIcon, FileMusic, Mic, MicOff,
} from "lucide-react";
import { MessageBubble } from "./MessageBubble";

const URL_RE = /^https?:\/\/\S+$/i;

function AttachmentChip({ attachment, onRemove }) {
  const { t } = useTranslation();
  const qa = attachment.quick_analysis || {};
  const name =
    attachment.filename ||
    attachment.url ||
    (attachment.path ? attachment.path.split(/[\\/]/).pop() : "attachment");
  const meta = [];
  if (qa.key_name) meta.push(qa.key_name);
  if (qa.bpm) meta.push(`${Math.round(qa.bpm)} BPM`);
  return (
    <div className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-cyan-500/10 ring-1 ring-cyan-400/30 text-[11px] text-fg">
      <FileMusic className="size-3 text-cyan-300" />
      <span className="truncate max-w-[180px]" title={name}>{name}</span>
      {meta.length > 0 && (
        <span className="text-fg-muted mono">· {meta.join(" · ")}</span>
      )}
      <button
        type="button"
        onClick={() => onRemove(attachment.id)}
        title={t("chat.remove_attachment")}
        aria-label={t("chat.remove_attachment")}
        className="ml-0.5 inline-flex items-center justify-center size-4 rounded-full text-fg-muted/70 hover:text-rose-300"
      >
        <XIcon className="size-3" />
      </button>
    </div>
  );
}

function RateLimitNotice({ initialSeconds, onExpire }) {
  const [remaining, setRemaining] = useState(() =>
    Math.max(1, Math.ceil(Number(initialSeconds) || 1)),
  );
  const { t } = useTranslation();
  useEffect(() => {
    if (remaining <= 0) {
      onExpire?.();
      return undefined;
    }
    const id = setInterval(() => {
      setRemaining((s) => {
        if (s <= 1) {
          clearInterval(id);
          onExpire?.();
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [remaining, onExpire]);
  if (remaining <= 0) return null;
  return (
    <div className="text-amber-300 text-xs px-2 py-1.5 rounded-md bg-amber-500/10 ring-1 ring-amber-400/30">
      {t("chat.rate_limited", { retry_after: remaining })}
    </div>
  );
}

export function ChatPanel({
  messages,
  sending,
  error,
  onSend,
  jobContextChip = null,
  onDismissError = null,
  // M5 attachment props
  pendingAttachments = [],
  attaching = false,
  onAttachFile = null,
  onAttachUrl = null,
  onRemoveAttachment = null,
  // M7 voice props
  onTranscribeVoice = null,
}) {
  const { t, i18n } = useTranslation();
  const [draft, setDraft] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const scrollRef = useRef(null);
  const taRef = useRef(null);
  const fileInputRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const submit = (e) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    // If the entire message is a URL and the user didn't already attach
    // it explicitly, route the URL to /attach/url so the assistant gets
    // the key/BPM analysis without us doing an OpenAI round-trip first.
    if (
      onAttachUrl &&
      URL_RE.test(text) &&
      !pendingAttachments.some((a) => a.url === text)
    ) {
      onAttachUrl(text);
      setDraft("");
      if (taRef.current) taRef.current.style.height = "auto";
      return;
    }
    setDraft("");
    onSend(text, { locale: i18n.language?.startsWith("en") ? "en" : "ko" });
    if (taRef.current) taRef.current.style.height = "auto";
  };

  const onPickFile = (e) => {
    const f = e.target.files?.[0];
    if (f && onAttachFile) onAttachFile(f);
    e.target.value = ""; // allow re-picking the same file
  };

  const startRecording = async () => {
    if (recording || transcribing || !onTranscribeVoice) return;
    if (typeof navigator?.mediaDevices?.getUserMedia !== "function") {
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      return; // user denied permission
    }
    streamRef.current = stream;
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    const mr = new MediaRecorder(stream, { mimeType: mime });
    chunksRef.current = [];
    mr.ondataavailable = (ev) => {
      if (ev.data && ev.data.size) chunksRef.current.push(ev.data);
    };
    mr.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: mime });
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setRecording(false);
      if (blob.size < 256) return; // ignored — too short to transcribe
      setTranscribing(true);
      try {
        const locale = i18n.language?.startsWith("en") ? "en" : "ko";
        const res = await onTranscribeVoice(blob, locale);
        if (res?.text) {
          setDraft((prev) => (prev ? prev + " " : "") + res.text);
          // Auto-grow the textarea to the new content.
          if (taRef.current) {
            taRef.current.style.height = "auto";
            taRef.current.style.height = `${Math.min(taRef.current.scrollHeight, 160)}px`;
            taRef.current.focus();
          }
        }
      } finally {
        setTranscribing(false);
      }
    };
    mr.start();
    recorderRef.current = mr;
    setRecording(true);
  };

  const stopRecording = () => {
    if (!recording) return;
    try {
      recorderRef.current?.stop();
    } catch {
      // already stopped
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      submit(e);
    }
  };

  const onInput = (e) => {
    setDraft(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  // Normalize error: legacy string and structured object both supported.
  let errorView = null;
  if (error) {
    if (typeof error === "string") {
      errorView = (
        <div className="text-rose-300 text-xs px-2 py-1.5 rounded-md bg-rose-500/10 ring-1 ring-rose-400/30">
          {error}
        </div>
      );
    } else if (error.kind === "rate_limited") {
      errorView = (
        <RateLimitNotice
          initialSeconds={error.retryAfter}
          onExpire={onDismissError}
        />
      );
    } else {
      errorView = (
        <div className="text-rose-300 text-xs px-2 py-1.5 rounded-md bg-rose-500/10 ring-1 ring-rose-400/30">
          {error.message || t("chat.error_generic")}
        </div>
      );
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {jobContextChip && (
        <div className="px-3 pt-2 pb-1 border-b border-white/5">{jobContextChip}</div>
      )}
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-2.5"
        role="log"
        aria-live="polite"
      >
        {messages.length === 0 && (
          <div className="text-center text-fg-muted text-xs py-8 px-4">
            {t("chat.empty_hint")}
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {sending && !messages.some((m) => m.streaming) && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-md px-3 py-2 glass text-fg-muted text-xs inline-flex items-center gap-2">
              <Loader2 className="size-3 animate-spin" />
              {t("chat.thinking")}
            </div>
          </div>
        )}
        {errorView}
      </div>
      <form
        onSubmit={submit}
        className="border-t border-white/5 p-2.5 bg-bg1/50 backdrop-blur-md"
      >
        {(pendingAttachments.length > 0 || attaching) && (
          <div className="flex flex-wrap items-center gap-1.5 pb-2">
            {pendingAttachments.map((a) => (
              <AttachmentChip
                key={a.id}
                attachment={a}
                onRemove={onRemoveAttachment || (() => {})}
              />
            ))}
            {attaching && (
              <span className="inline-flex items-center gap-1 text-[11px] text-fg-muted">
                <Loader2 className="size-3 animate-spin" />
                {t("chat.attaching")}
              </span>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          {onAttachFile && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*,video/*,.wav,.aiff,.flac,.mp3,.m4a,.ogg,.opus,.wma,.mp4,.mov,.mkv,.webm"
                className="hidden"
                onChange={onPickFile}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={attaching || sending}
                title={t("chat.attach_file")}
                aria-label={t("chat.attach_file")}
                className="inline-flex items-center justify-center size-9 rounded-xl bg-white/5 ring-1 ring-white/10 text-fg-muted hover:text-fg hover:bg-white/10 disabled:opacity-40 transition"
              >
                <Paperclip className="size-4" />
              </button>
            </>
          )}
          {onTranscribeVoice && (
            <button
              type="button"
              onClick={recording ? stopRecording : startRecording}
              disabled={sending || transcribing}
              title={recording ? t("chat.voice_recording") : t("chat.voice_record")}
              aria-label={recording ? t("chat.voice_recording") : t("chat.voice_record")}
              className={`inline-flex items-center justify-center size-9 rounded-xl ring-1 transition ${
                recording
                  ? "bg-rose-500/20 ring-rose-400/40 text-rose-300 animate-pulse"
                  : transcribing
                    ? "bg-white/5 ring-white/10 text-fg-muted/60"
                    : "bg-white/5 ring-white/10 text-fg-muted hover:text-fg hover:bg-white/10"
              } disabled:opacity-40`}
            >
              {transcribing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : recording ? (
                <MicOff className="size-4" />
              ) : (
                <Mic className="size-4" />
              )}
            </button>
          )}
          <textarea
            ref={taRef}
            value={draft}
            onChange={onInput}
            onKeyDown={onKeyDown}
            placeholder={t("chat.placeholder")}
            rows={1}
            className="flex-1 resize-none rounded-xl bg-white/5 ring-1 ring-white/10 px-3 py-2 text-sm text-fg placeholder:text-fg-muted/60 focus:outline-none focus:ring-violet/50"
            aria-label={t("chat.placeholder")}
          />
          <button
            type="submit"
            disabled={!draft.trim() || sending}
            title={
              URL_RE.test(draft.trim()) ? t("chat.attach_url") : t("chat.send")
            }
            aria-label={t("chat.send")}
            className="inline-flex items-center justify-center size-9 rounded-xl bg-gradient-to-br from-violet to-cyan text-white disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition"
          >
            {URL_RE.test(draft.trim()) ? (
              <Link2 className="size-4" />
            ) : (
              <Send className="size-4" />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
