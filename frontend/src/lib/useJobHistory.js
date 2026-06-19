/**
 * localStorage-backed history of jobs the user has run on this device.
 * Each entry: { id, title, mode, createdAt, lastSeenAt, setlistId? }
 *
 * Also stores `setlists` — named groupings of jobs:
 *   { id, name, jobIds[], createdAt }
 *
 * Lives entirely client-side; pairs with the server's in-memory registry.
 * If the server is restarted, entries point to no-longer-existing job IDs;
 * we mark those as "expired" in UI rather than dropping them.
 */

import { useCallback, useEffect, useState } from "react";

import {
  listSetlists,
  createSetlistServer,
  patchSetlist,
  deleteSetlistServer,
  addJobToSetlist as apiAddJobToSetlist,
  removeJobFromSetlist as apiRemoveJobFromSetlist,
} from "./api";

const HISTORY_KEY = "rechord:history:v1";
const SETLISTS_KEY = "rechord:setlists:v1";
const MAX_HISTORY = 200;
// The DOM 'storage' event only fires in OTHER tabs, so a same-tab write (e.g.
// the Job page upserting a finished job) wouldn't reach the sidebar's separate
// useJobHistory() instance until an F5. We broadcast this custom event on every
// write so all live instances re-read immediately.
const CHANGE_EVENT = "rechord:history-changed";

// Convert a server-shape setlist (snake_case + created_at unix int) into the
// client-shape we use in localStorage.
function fromServer(s) {
  return {
    id: s.id,
    name: s.name,
    jobIds: Array.isArray(s.job_ids) ? s.job_ids : [],
    createdAt: (s.created_at || 0) * 1000 || Date.now(),
  };
}

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const v = JSON.parse(raw);
    return v ?? fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    // Notify sibling instances AFTER the current React state update settles
    // (queueMicrotask avoids a setState-during-update warning), so the sidebar
    // refreshes the moment a job finishes — no manual reload.
    queueMicrotask(() => {
      try { window.dispatchEvent(new Event(CHANGE_EVENT)); } catch { /* SSR / none */ }
    });
  } catch {
    /* quota or private-mode — silently ignore */
  }
}

function nowMs() {
  return Date.now();
}

export function useJobHistory() {
  const [items, setItems] = useState(() => readJson(HISTORY_KEY, []));
  const [setlists, setSetlists] = useState(() => readJson(SETLISTS_KEY, []));

  // Keep every instance in sync — across tabs ('storage') AND within the same
  // tab (our CHANGE_EVENT), so the sidebar updates the instant a job finishes.
  useEffect(() => {
    const resync = () => {
      setItems(readJson(HISTORY_KEY, []));
      setSetlists(readJson(SETLISTS_KEY, []));
    };
    const onStorage = (e) => {
      if (e.key === HISTORY_KEY || e.key === SETLISTS_KEY) resync();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(CHANGE_EVENT, resync);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(CHANGE_EVENT, resync);
    };
  }, []);

  // Initial pull from server (best-effort). Server is authoritative when
  // reachable; localStorage is the offline fallback.
  useEffect(() => {
    let cancelled = false;
    listSetlists()
      .then((serverList) => {
        if (cancelled || !Array.isArray(serverList)) return;
        const merged = serverList.map(fromServer);
        setSetlists(merged);
        writeJson(SETLISTS_KEY, merged);
      })
      .catch(() => { /* offline → keep local */ });
    return () => { cancelled = true; };
  }, []);

  const persistItems = useCallback((next) => {
    setItems(next);
    writeJson(HISTORY_KEY, next);
  }, []);
  const persistSetlists = useCallback((next) => {
    setSetlists(next);
    writeJson(SETLISTS_KEY, next);
  }, []);

  const upsert = useCallback((entry) => {
    if (!entry?.id) return;
    setItems((prev) => {
      const filtered = prev.filter((x) => x.id !== entry.id);
      const next = [
        { ...entry, lastSeenAt: nowMs(), createdAt: entry.createdAt ?? nowMs() },
        ...filtered,
      ].slice(0, MAX_HISTORY);
      writeJson(HISTORY_KEY, next);
      return next;
    });
  }, []);

  const touch = useCallback((id) => {
    setItems((prev) => {
      const idx = prev.findIndex((x) => x.id === id);
      if (idx < 0) return prev;
      const next = [...prev];
      next[idx] = { ...next[idx], lastSeenAt: nowMs() };
      writeJson(HISTORY_KEY, next);
      return next;
    });
  }, []);

  const remove = useCallback((id) => {
    setItems((prev) => {
      const next = prev.filter((x) => x.id !== id);
      writeJson(HISTORY_KEY, next);
      return next;
    });
    setSetlists((prev) => {
      const next = prev.map((s) => ({ ...s, jobIds: s.jobIds.filter((x) => x !== id) }));
      writeJson(SETLISTS_KEY, next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    persistItems([]);
    persistSetlists([]);
  }, [persistItems, persistSetlists]);

  // ── Setlists (server-first, local cache mirror) ─────────────────────────
  const createSetlist = useCallback((name) => {
    const cleanName = name || "이름없는 셋";
    // Optimistic local insert; replace with server-shape on success.
    const tempId = `sl_local_${Math.random().toString(36).slice(2, 10)}`;
    const entry = { id: tempId, name: cleanName, jobIds: [], createdAt: nowMs() };
    setSetlists((prev) => {
      const next = [entry, ...prev];
      writeJson(SETLISTS_KEY, next);
      return next;
    });
    createSetlistServer(cleanName, []).then((srv) => {
      const real = fromServer(srv);
      setSetlists((prev) => {
        const next = prev.map((s) => (s.id === tempId ? real : s));
        writeJson(SETLISTS_KEY, next);
        return next;
      });
    }).catch(() => { /* offline → keep tempId */ });
    return tempId;
  }, []);

  const renameSetlist = useCallback((id, name) => {
    setSetlists((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, name } : s));
      writeJson(SETLISTS_KEY, next);
      return next;
    });
    patchSetlist(id, { name }).catch(() => { /* local-only ok */ });
  }, []);

  const deleteSetlist = useCallback((id) => {
    setSetlists((prev) => {
      const next = prev.filter((s) => s.id !== id);
      writeJson(SETLISTS_KEY, next);
      return next;
    });
    deleteSetlistServer(id).catch(() => { /* local-only ok */ });
  }, []);

  const addToSetlist = useCallback((setlistId, jobId) => {
    setSetlists((prev) => {
      const next = prev.map((s) =>
        s.id === setlistId && !s.jobIds.includes(jobId)
          ? { ...s, jobIds: [...s.jobIds, jobId] }
          : s,
      );
      writeJson(SETLISTS_KEY, next);
      return next;
    });
    apiAddJobToSetlist(setlistId, jobId).catch(() => { /* local-only ok */ });
  }, []);

  const removeFromSetlist = useCallback((setlistId, jobId) => {
    setSetlists((prev) => {
      const next = prev.map((s) =>
        s.id === setlistId ? { ...s, jobIds: s.jobIds.filter((x) => x !== jobId) } : s,
      );
      writeJson(SETLISTS_KEY, next);
      return next;
    });
    apiRemoveJobFromSetlist(setlistId, jobId).catch(() => { /* local-only ok */ });
  }, []);

  const reorderSetlist = useCallback((setlistId, fromIdx, toIdx) => {
    setSetlists((prev) => {
      const next = prev.map((s) => {
        if (s.id !== setlistId) return s;
        const ids = [...s.jobIds];
        if (fromIdx < 0 || fromIdx >= ids.length || toIdx < 0 || toIdx >= ids.length) return s;
        const [moved] = ids.splice(fromIdx, 1);
        ids.splice(toIdx, 0, moved);
        return { ...s, jobIds: ids };
      });
      writeJson(SETLISTS_KEY, next);
      // Propagate full ordering to server.
      const updated = next.find((s) => s.id === setlistId);
      if (updated) {
        patchSetlist(setlistId, { job_ids: updated.jobIds }).catch(() => { /* local ok */ });
      }
      return next;
    });
  }, []);

  return {
    items,
    setlists,
    upsert,
    touch,
    remove,
    clear,
    createSetlist,
    renameSetlist,
    deleteSetlist,
    addToSetlist,
    removeFromSetlist,
    reorderSetlist,
  };
}
