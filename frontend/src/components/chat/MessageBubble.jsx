import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import rehypeHighlight from "rehype-highlight";
import { Sparkles } from "lucide-react";
import { parseChatActions, dispatchChatAction } from "@/lib/chatActions";

// Strip the <confidence>...</confidence> token from rendered text so it
// doesn't leak into the visible output. Confidence is rendered separately
// in the footer when present.
const CONFIDENCE_RE = /<confidence>\s*([01]?\.\d+|[01](?:\.0)?)\s*<\/confidence>/i;

// Strip <ai-trans>...</ai-trans> wrapping so the assistant text reads
// cleanly. The "AI 참고용" warning is rendered separately by the bubble.
const AI_TRANS_RE = /<ai-trans>([\s\S]*?)<\/ai-trans>/gi;

function parseAssistant(raw) {
  const text = raw ?? "";
  const cm = CONFIDENCE_RE.exec(text);
  const confidence = cm ? Math.max(0, Math.min(1, parseFloat(cm[1]))) : null;
  let cleaned = text.replace(CONFIDENCE_RE, "");
  const aiTransBlocks = [];
  cleaned = cleaned.replace(AI_TRANS_RE, (_match, inner) => {
    aiTransBlocks.push(inner.trim());
    return inner.trim();
  });
  // Strip <action> JSON blocks before rendering — they become buttons
  // below. Action parsing is forgiving: malformed JSON falls through and
  // the raw block stays in the cleaned text so the user sees the failure.
  const { actions, cleaned: textWithoutActions } = parseChatActions(cleaned);
  return { cleaned: textWithoutActions, confidence, aiTransBlocks, actions };
}

function ConfidencePill({ value }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  const tier = value >= 0.75 ? "high" : value >= 0.5 ? "mid" : "low";
  const styles = {
    high: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30",
    mid: "bg-amber-500/15 text-amber-300 ring-amber-400/30",
    low: "bg-rose-500/15 text-rose-300 ring-rose-400/30",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] mono ring-1 ${styles[tier]}`}
      title={`Confidence ${pct}%`}
    >
      <span className="size-1.5 rounded-full bg-current opacity-70" />
      {pct}%
    </span>
  );
}

const MD_COMPONENTS = {
  // Tight defaults so chat bubbles stay compact.
  p: (props) => <p className="my-1 leading-relaxed" {...props} />,
  ul: (props) => <ul className="list-disc pl-5 my-1 space-y-0.5" {...props} />,
  ol: (props) => <ol className="list-decimal pl-5 my-1 space-y-0.5" {...props} />,
  li: (props) => <li className="leading-relaxed" {...props} />,
  a: (props) => (
    <a
      {...props}
      target="_blank"
      rel="noopener noreferrer"
      className="text-cyan-300 underline-offset-2 hover:underline"
    />
  ),
  code: ({ inline, className, children, ...rest }) =>
    inline ? (
      <code
        className="px-1 py-0.5 rounded bg-white/10 text-[0.9em] mono"
        {...rest}
      >
        {children}
      </code>
    ) : (
      <code className={`${className || ""} block`} {...rest}>{children}</code>
    ),
  pre: (props) => (
    <pre
      className="my-1.5 p-2 rounded-md bg-black/35 ring-1 ring-white/10 overflow-x-auto text-[12px] mono"
      {...props}
    />
  ),
  table: (props) => (
    <div className="my-1.5 overflow-x-auto">
      <table className="text-xs border-collapse" {...props} />
    </div>
  ),
  th: (props) => (
    <th className="border border-white/10 px-2 py-1 text-left font-semibold" {...props} />
  ),
  td: (props) => <td className="border border-white/10 px-2 py-1" {...props} />,
  blockquote: (props) => (
    <blockquote
      className="border-l-2 border-violet/40 pl-2 my-1 text-fg-muted italic"
      {...props}
    />
  ),
};

export function MessageBubble({ message }) {
  const { t } = useTranslation();
  const isUser = message.role === "user";

  const { cleaned, confidence, aiTransBlocks, actions } = useMemo(() => {
    if (isUser) {
      return { cleaned: message.content, confidence: null, aiTransBlocks: [], actions: [] };
    }
    return parseAssistant(message.content);
  }, [message.content, isUser]);

  const explicitConfidence = message.confidence ?? confidence;

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md px-3.5 py-2 bg-violet/15 ring-1 ring-violet/30 text-fg text-sm whitespace-pre-wrap break-words">
          {cleaned}
        </div>
      </div>
    );
  }

  const isStreaming = message.streaming;
  const showEmptyHint = !cleaned && !isStreaming;

  return (
    <div className="flex justify-start">
      <div className="max-w-[88%] rounded-2xl rounded-bl-md px-3.5 py-2 glass text-fg text-sm break-words">
        {showEmptyHint ? (
          <span className="text-fg-muted italic">{t("chat.error_generic")}</span>
        ) : (
          <div className="text-sm leading-relaxed">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeSanitize, rehypeHighlight]}
              components={MD_COMPONENTS}
            >
              {cleaned || " "}
            </ReactMarkdown>
            {isStreaming && (
              <span
                aria-hidden
                className="inline-block w-1.5 h-3.5 ml-0.5 align-text-bottom bg-cyan-300/80 animate-pulse"
              />
            )}
          </div>
        )}
        {actions && actions.length > 0 && !isStreaming && (
          <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label={t("chat.actions_label", { defaultValue: "추천 액션" })}>
            {actions.map((a, idx) => (
              <button
                key={`${a.type}-${idx}`}
                type="button"
                onClick={() => dispatchChatAction(a)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gradient-to-r from-violet/25 to-cyan/15 ring-1 ring-violet/40 text-[11px] text-fg hover:from-violet/35 hover:to-cyan/25 transition-colors"
                title={a.type}
              >
                <Sparkles className="size-3" aria-hidden="true" />
                {a.label}
              </button>
            ))}
          </div>
        )}
        {aiTransBlocks.length > 0 && (
          <div className="mt-1.5 text-[10px] text-amber-300 inline-flex items-center gap-1 ring-1 ring-amber-400/30 bg-amber-500/10 rounded-full px-2 py-0.5">
            {t("chat.translation_warning")}
          </div>
        )}
        {explicitConfidence != null && (
          <div className="mt-1.5 flex items-center gap-1.5">
            <ConfidencePill value={explicitConfidence} />
          </div>
        )}
      </div>
    </div>
  );
}
