import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Music2, X, Trash2, PanelLeftClose, PanelLeft } from "lucide-react";
import { ChatPanel } from "./ChatPanel";
import { ConversationList } from "./ConversationList";
import { useChatSession } from "./useChatSession";
import { useJobContextSnapshot } from "./useJobContextSnapshot";

function shouldHide(pathname, search) {
  if (pathname.startsWith("/perform")) return true;
  const params = new URLSearchParams(search);
  if (params.get("embed") === "1") return true;
  return false;
}

function JobContextChip({ ctx }) {
  if (!ctx) return null;
  const parts = [];
  if (ctx.title) parts.push(ctx.title);
  if (ctx.key_name) parts.push(ctx.key_name);
  if (typeof ctx.bpm === "number") parts.push(`${Math.round(ctx.bpm)} BPM`);
  if (!parts.length) return null;
  return (
    <div className="inline-flex items-center gap-1.5 text-[11px] text-fg-muted">
      <span className="size-1.5 rounded-full bg-cyan-400" />
      <span className="text-fg">현재 곡:</span>
      <span className="mono truncate">{parts.join(" · ")}</span>
    </div>
  );
}

function activeTitle(conversations, activeId, t) {
  const c = conversations.find((x) => x.id === activeId);
  if (!c) return t("chat.title");
  if (c.title) return c.title;
  const preview = (c.last_preview || "").trim();
  if (preview) return preview.length > 30 ? preview.slice(0, 30) + "…" : preview;
  return t("chat.untitled_conversation");
}

export function ChatWidget() {
  const { pathname, search } = useLocation();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  const {
    conversations,
    activeId,
    messages,
    sending,
    error,
    send,
    newConversation,
    selectConversation,
    deleteConversation,
    clearActive,
    dismissError,
    pendingAttachments,
    attaching,
    attachFile,
    attachUrl,
    removeAttachment,
    transcribeVoice,
  } = useChatSession();
  const jobContext = useJobContextSnapshot();

  // Wrap the raw `send` so the current Job's context is automatically
  // attached to every turn while the user is on a Job page.
  const sendWithContext = useCallback(
    (text, opts = {}) =>
      send(text, { ...opts, jobContext: opts.jobContext ?? jobContext }),
    [send, jobContext],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (shouldHide(pathname, search)) return null;

  return (
    <>
      {/* Floating launcher — musical note icon to match the platform brand */}
      <motion.button
        type="button"
        onClick={() => setOpen((v) => !v)}
        whileHover={{ scale: 1.05, rotate: -4 }}
        whileTap={{ scale: 0.96 }}
        aria-label={open ? t("chat.close") : t("chat.open")}
        title={open ? t("chat.close") : t("chat.open")}
        className="fixed z-40 right-4 sm:right-6 size-14 rounded-full bg-gradient-to-br from-violet to-cyan text-white shadow-[0_8px_28px_rgba(139,92,246,0.45)] flex items-center justify-center"
        style={{ bottom: "calc(1rem + env(safe-area-inset-bottom, 0px))" }}
      >
        <AnimatePresence initial={false} mode="wait">
          {open ? (
            <motion.span
              key="x"
              initial={{ rotate: -90, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              exit={{ rotate: 90, opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <X className="size-5" />
            </motion.span>
          ) : (
            <motion.span
              key="note"
              initial={{ rotate: 90, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              exit={{ rotate: -90, opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <Music2 className="size-6" />
            </motion.span>
          )}
        </AnimatePresence>
      </motion.button>

      {/* Right-anchored modal panel — slides in from the right edge */}
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              key="scrim"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-30 bg-black/55 backdrop-blur-sm"
              aria-hidden
            />
            <motion.aside
              key="panel"
              initial={{ x: 820, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 820, opacity: 0 }}
              transition={{ type: "spring", stiffness: 280, damping: 30 }}
              role="dialog"
              aria-label={t("chat.title")}
              className="fixed z-40 right-0 top-0 h-full w-full sm:w-[640px] md:w-[760px] lg:w-[820px] bg-bg1/95 backdrop-blur-xl ring-1 ring-white/10 border-l border-white/5 flex flex-col"
            >
              <header className="shrink-0 h-14 px-3 sm:px-4 flex items-center gap-2 border-b border-white/5">
                <button
                  type="button"
                  onClick={() => setShowSidebar((v) => !v)}
                  title={showSidebar ? t("chat.hide_sidebar") : t("chat.show_sidebar")}
                  aria-label={showSidebar ? t("chat.hide_sidebar") : t("chat.show_sidebar")}
                  className="inline-flex items-center justify-center size-8 rounded-full text-fg-muted hover:text-fg hover:bg-white/5"
                >
                  {showSidebar ? <PanelLeftClose className="size-4" /> : <PanelLeft className="size-4" />}
                </button>
                <div className="inline-flex items-center justify-center size-7 rounded-lg bg-gradient-to-br from-violet to-cyan text-white">
                  <Music2 className="size-3.5" />
                </div>
                <h2 className="text-sm font-semibold text-fg truncate max-w-[40ch]">
                  {activeTitle(conversations, activeId, t)}
                </h2>
                <div className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    onClick={clearActive}
                    title={t("chat.clear")}
                    aria-label={t("chat.clear")}
                    className="inline-flex items-center justify-center size-8 rounded-full text-fg-muted hover:text-fg hover:bg-white/5"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    title={t("chat.close")}
                    aria-label={t("chat.close")}
                    className="inline-flex items-center justify-center size-8 rounded-full text-fg-muted hover:text-fg hover:bg-white/5"
                  >
                    <X className="size-4" />
                  </button>
                </div>
              </header>
              <div className="flex-1 min-h-0 flex">
                <AnimatePresence initial={false}>
                  {showSidebar && (
                    <motion.div
                      key="sidebar"
                      initial={{ width: 0, opacity: 0 }}
                      animate={{ width: 220, opacity: 1 }}
                      exit={{ width: 0, opacity: 0 }}
                      transition={{ duration: 0.18 }}
                      className="shrink-0 overflow-hidden border-r border-white/5 bg-bg0/40"
                    >
                      <div className="w-[220px] h-full">
                        <ConversationList
                          conversations={conversations}
                          activeId={activeId}
                          onSelect={selectConversation}
                          onNew={newConversation}
                          onDelete={deleteConversation}
                        />
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
                <div className="flex-1 min-w-0">
                  <ChatPanel
                    messages={messages}
                    sending={sending}
                    error={error}
                    onSend={sendWithContext}
                    onDismissError={dismissError}
                    jobContextChip={
                      jobContext ? <JobContextChip ctx={jobContext} /> : null
                    }
                    pendingAttachments={pendingAttachments}
                    attaching={attaching}
                    onAttachFile={attachFile}
                    onAttachUrl={attachUrl}
                    onRemoveAttachment={removeAttachment}
                    onTranscribeVoice={transcribeVoice}
                  />
                </div>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
