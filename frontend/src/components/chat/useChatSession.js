import { useCallback, useEffect, useRef, useState } from "react";
import {
  attachChatFile,
  attachChatUrl,
  createChatSession,
  deleteChatSession,
  listChatSessions,
  streamChatMessage,
  patchChatSession,
  transcribeChatVoice,
} from "@/lib/api";

// localStorage keys
const ACTIVE_KEY = "rechord.chat.active_sid";
const INDEX_KEY = "rechord.chat.sessions_index";
const HIST_KEY = (sid) => `rechord.chat.history.${sid}`;
const LEGACY_SID_KEY = "rechord.chat.session_id"; // pre-multi-conversation
const HIST_LIMIT = 50;

function genSid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `sess_${crypto.randomUUID().replace(/-/g, "").slice(0, 24)}`;
  }
  return `sess_${Math.random().toString(36).slice(2, 14)}${Date.now().toString(36)}`;
}

function safeLoad(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function safeSave(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota / private mode */
  }
}

function loadHistory(sid) {
  const arr = safeLoad(HIST_KEY(sid), []);
  return Array.isArray(arr) ? arr.slice(-HIST_LIMIT) : [];
}

function persistHistory(sid, msgs) {
  safeSave(HIST_KEY(sid), (msgs || []).slice(-HIST_LIMIT));
}

function previewOf(msgs) {
  if (!msgs || !msgs.length) return null;
  for (let i = msgs.length - 1; i >= 0; i--) {
    const c = (msgs[i]?.content || "").trim();
    if (c) return c.length > 80 ? c.slice(0, 80) + "…" : c;
  }
  return null;
}

function ensureFreshIndex() {
  let idx = safeLoad(INDEX_KEY, null);
  if (Array.isArray(idx)) return idx;
  // One-time migration from M1's single-session model.
  const legacy = (() => {
    try {
      return localStorage.getItem(LEGACY_SID_KEY);
    } catch {
      return null;
    }
  })();
  if (legacy) {
    const msgs = loadHistory(legacy);
    const seed = [{
      id: legacy,
      title: null,
      updated_at: Date.now() / 1000,
      last_preview: previewOf(msgs),
    }];
    safeSave(INDEX_KEY, seed);
    try { localStorage.removeItem(LEGACY_SID_KEY); } catch { /* noop */ }
    return seed;
  }
  return [];
}

/** Multi-conversation chat state hook.
 *  All persistence is browser-local (localStorage); the backend session
 *  registry is a mirror that we sync after sends so the auto-title
 *  generator's output flows back into our index.
 */
export function useChatSession() {
  const [conversations, setConversations] = useState(ensureFreshIndex);
  const [activeId, setActiveId] = useState(() => {
    const stored = (() => {
      try { return localStorage.getItem(ACTIVE_KEY); } catch { return null; }
    })();
    const idx = ensureFreshIndex();
    if (stored && idx.some((c) => c.id === stored)) return stored;
    if (idx.length) return idx[0].id;
    return null;
  });
  const [messages, setMessages] = useState(() => (activeId ? loadHistory(activeId) : []));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  // Attachments staged for the NEXT send. Cleared after each successful send.
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const [attaching, setAttaching] = useState(false);
  const refreshTimerRef = useRef(null);

  // Persist active id whenever it changes.
  useEffect(() => {
    if (activeId) {
      try { localStorage.setItem(ACTIVE_KEY, activeId); } catch { /* noop */ }
    }
  }, [activeId]);

  // Persist conversations index whenever it changes.
  useEffect(() => {
    safeSave(INDEX_KEY, conversations);
  }, [conversations]);

  // Whenever the active id changes, load that conversation's history.
  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    setMessages(loadHistory(activeId));
  }, [activeId]);

  // Persist history of the active conversation whenever messages change.
  useEffect(() => {
    if (!activeId) return;
    persistHistory(activeId, messages);
  }, [activeId, messages]);

  // If there are no conversations yet, lazily create one and register it
  // server-side. We don't wait — the server creates lazily on POST too.
  useEffect(() => {
    if (activeId || conversations.length) return;
    const sid = genSid();
    setConversations([{
      id: sid,
      title: null,
      updated_at: Date.now() / 1000,
      last_preview: null,
    }]);
    setActiveId(sid);
    createChatSession(sid).catch(() => {});
  }, [activeId, conversations.length]);

  // Sync server-side titles into the local index. Called after a send so
  // the auto-title generator's background result becomes visible without
  // a manual reload.
  const syncFromServer = useCallback(async () => {
    try {
      const serverList = await listChatSessions();
      if (!Array.isArray(serverList)) return;
      setConversations((prev) => {
        const byId = new Map(serverList.map((s) => [s.id, s]));
        // Update titles + last_preview on entries we already know about.
        const merged = prev.map((c) => {
          const s = byId.get(c.id);
          if (!s) return c;
          return {
            ...c,
            title: s.title ?? c.title,
            updated_at: s.updated_at ?? c.updated_at,
            last_preview: s.last_message_preview ?? c.last_preview,
          };
        });
        // Add any server-side sessions we don't have locally (e.g.
        // another tab created one — rare in Phase A but cheap to handle).
        const knownIds = new Set(merged.map((c) => c.id));
        for (const s of serverList) {
          if (!knownIds.has(s.id)) {
            merged.push({
              id: s.id,
              title: s.title,
              updated_at: s.updated_at,
              last_preview: s.last_message_preview,
            });
          }
        }
        return merged.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
      });
    } catch {
      /* offline / disabled — non-fatal */
    }
  }, []);

  const scheduleTitleSync = useCallback(() => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    // Backend kicks off auto-title generation as a background task; give
    // it a couple of seconds to land before polling.
    refreshTimerRef.current = setTimeout(() => { syncFromServer(); }, 3500);
  }, [syncFromServer]);

  const send = useCallback(
    async (text, opts = {}) => {
      const trimmed = (text ?? "").trim();
      if (!trimmed || sending || !activeId) return;
      setError(null);
      setSending(true);
      const userMsg = {
        id: `local_user_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        role: "user",
        content: trimmed,
        created_at: Date.now() / 1000,
      };
      const placeholderId = `local_asst_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const placeholder = {
        id: placeholderId,
        role: "assistant",
        content: "",
        created_at: Date.now() / 1000,
        streaming: true,
      };
      setMessages((prev) => [...prev, userMsg, placeholder]);

      let bufferedConfidence = null;
      let finalMessage = null;
      let streamErrorDetail = null;

      try {
        await streamChatMessage(
          activeId,
          {
            text: trimmed,
            locale: opts.locale ?? "ko",
            job_context: opts.jobContext ?? null,
            attachment_ids:
              opts.attachmentIds ?? pendingAttachments.map((a) => a.id),
          },
          (ev) => {
            if (ev.type === "delta") {
              setMessages((prev) => {
                const next = [...prev];
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].id === placeholderId) {
                    next[i] = {
                      ...next[i],
                      content: (next[i].content || "") + (ev.text || ""),
                    };
                    break;
                  }
                }
                return next;
              });
            } else if (ev.type === "confidence") {
              bufferedConfidence = ev.value;
            } else if (ev.type === "message") {
              finalMessage = ev.message;
            } else if (ev.type === "error") {
              streamErrorDetail = ev.detail || "stream error";
            }
            // 'done' is just a terminator — nothing to do.
          },
        );
      } catch (e) {
        if (e?.status === 429) {
          const ra = e.retryAfter ?? 1;
          setError({ kind: "rate_limited", retryAfter: ra });
        } else if (e?.name === "AbortError") {
          /* cancelled by user — leave a soft notice */
          setError(null);
        } else {
          setError({ kind: "generic", message: e?.message || String(e) });
        }
        // Remove the assistant placeholder; keep the user message so the
        // user can re-send by editing it (we just dropped it server-side
        // too via the rollback path).
        setMessages((prev) => prev.filter((m) => m.id !== placeholderId));
        setSending(false);
        return;
      }

      // Replace the placeholder with the persisted assistant message and
      // bump the conversation's index entry.
      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].id === placeholderId) {
            if (finalMessage) {
              next[i] = {
                ...finalMessage,
                confidence: bufferedConfidence,
              };
            } else {
              // Stream ended without a final 'message' frame — keep the
              // streamed content but drop the streaming flag.
              next[i] = { ...next[i], streaming: false };
            }
            break;
          }
        }
        setConversations((cs) => {
          const now = Date.now() / 1000;
          return cs
            .map((c) =>
              c.id === activeId
                ? { ...c, updated_at: now, last_preview: previewOf(next) }
                : c,
            )
            .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
        });
        return next;
      });

      if (streamErrorDetail) {
        setError({ kind: "generic", message: streamErrorDetail });
      }
      // Successful send → clear the staged attachments so the next turn
      // doesn't accidentally re-attach the same files.
      setPendingAttachments([]);
      scheduleTitleSync();
      setSending(false);
    },
    [activeId, sending, scheduleTitleSync, pendingAttachments],
  );

  const attachFile = useCallback(async (file) => {
    if (!file || !activeId || attaching) return null;
    setError(null);
    setAttaching(true);
    try {
      const att = await attachChatFile(activeId, file);
      setPendingAttachments((prev) => [...prev, att]);
      return att;
    } catch (e) {
      setError({ kind: "generic", message: e?.message || String(e) });
      return null;
    } finally {
      setAttaching(false);
    }
  }, [activeId, attaching]);

  const attachUrl = useCallback(async (url) => {
    if (!url || !activeId || attaching) return null;
    setError(null);
    setAttaching(true);
    try {
      const att = await attachChatUrl(activeId, url);
      setPendingAttachments((prev) => [...prev, att]);
      return att;
    } catch (e) {
      setError({ kind: "generic", message: e?.message || String(e) });
      return null;
    } finally {
      setAttaching(false);
    }
  }, [activeId, attaching]);

  const removeAttachment = useCallback((attachmentId) => {
    setPendingAttachments((prev) => prev.filter((a) => a.id !== attachmentId));
  }, []);

  const transcribeVoice = useCallback(
    async (blob, locale = "ko") => {
      if (!activeId || !blob) return null;
      try {
        return await transcribeChatVoice(activeId, blob, locale);
      } catch (e) {
        setError({ kind: "generic", message: e?.message || String(e) });
        return null;
      }
    },
    [activeId],
  );

  const newConversation = useCallback(() => {
    const sid = genSid();
    setConversations((cs) => [
      { id: sid, title: null, updated_at: Date.now() / 1000, last_preview: null },
      ...cs,
    ]);
    setActiveId(sid);
    setMessages([]);
    createChatSession(sid).catch(() => {});
  }, []);

  const selectConversation = useCallback((id) => {
    if (!id) return;
    setActiveId(id);
  }, []);

  const deleteConversation = useCallback((id) => {
    if (!id) return;
    setConversations((cs) => {
      const next = cs.filter((c) => c.id !== id);
      // If we removed the active one, pick the most recent remaining (or
      // leave it null so the lazy-create effect spins up a new one).
      if (id === activeId) {
        setActiveId(next.length ? next[0].id : null);
        setMessages(next.length ? loadHistory(next[0].id) : []);
      }
      return next;
    });
    try { localStorage.removeItem(HIST_KEY(id)); } catch { /* noop */ }
    deleteChatSession(id).catch(() => {});
  }, [activeId]);

  const renameConversation = useCallback(async (id, title) => {
    setConversations((cs) =>
      cs.map((c) => (c.id === id ? { ...c, title } : c)),
    );
    try {
      await patchChatSession(id, { title });
    } catch {
      /* server may be down — local rename still visible until next sync */
    }
  }, []);

  const clearActive = useCallback(() => {
    if (!activeId) return;
    setMessages([]);
    persistHistory(activeId, []);
    deleteChatSession(activeId).catch(() => {});
    // Reset title so auto-title can re-run on the next send.
    setConversations((cs) =>
      cs.map((c) =>
        c.id === activeId ? { ...c, title: null, last_preview: null } : c,
      ),
    );
  }, [activeId]);

  const dismissError = useCallback(() => setError(null), []);

  // One-time sync on mount so users see titles created during a previous
  // session (in case the backend kept the registry across reload).
  useEffect(() => {
    syncFromServer();
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    conversations,
    activeId,
    messages,
    sending,
    error,
    send,
    newConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
    clearActive,
    syncFromServer,
    dismissError,
    // M5 — attachments staged for the next send.
    pendingAttachments,
    attaching,
    attachFile,
    attachUrl,
    removeAttachment,
    // M7 — voice transcription (local faster-whisper, audio never leaves
    // the local backend, no OpenAI Whisper call).
    transcribeVoice,
  };
}
