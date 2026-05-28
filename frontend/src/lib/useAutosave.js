/**
 * Debounced autosave hook for editor panels (lyrics / aux cues / notes).
 *
 * Pattern:
 *
 *   const autosave = useAutosave({
 *     value: cues,                       // anything JSON-serialisable
 *     dirty: undo.dirty,                  // only fire when there are changes
 *     interval: 4000,                     // ms between saves
 *     onSave: async (val) => saveAuxCues(job.id, val, false),
 *   });
 *
 *   // optional UI:
 *   autosave.status   // "idle" | "pending" | "saving" | "saved" | "error"
 *   autosave.savedAt  // unix ms of last successful save
 *
 * Behaviour:
 *   - First save fires `interval` ms after the user stops editing.
 *   - Subsequent edits reset the timer.
 *   - On unmount the timer is cleared (no orphan saves).
 *   - On window beforeunload we attempt a synchronous final save via
 *     `navigator.sendBeacon`-style logic — but the consumer's onSave is
 *     async, so we fall back to telling the user to save manually if a
 *     dirty save is still queued.
 */

import { useCallback, useEffect, useRef, useState } from "react";


export function useAutosave({
  value,
  dirty,
  interval = 4000,
  onSave,
  enabled = true,
}) {
  const [status, setStatus] = useState("idle");
  const [savedAt, setSavedAt] = useState(0);
  const [lastError, setLastError] = useState(null);

  const timerRef = useRef(null);
  const inflightRef = useRef(false);
  const queuedValueRef = useRef(null);

  const flush = useCallback(async () => {
    if (!enabled || !onSave) return;
    const v = queuedValueRef.current;
    if (v == null) return;
    queuedValueRef.current = null;
    inflightRef.current = true;
    setStatus("saving");
    setLastError(null);
    try {
      await onSave(v);
      setStatus("saved");
      setSavedAt(Date.now());
    } catch (e) {
      setStatus("error");
      setLastError(e?.message || String(e));
    } finally {
      inflightRef.current = false;
      // If a new value queued up while we were saving, save it too.
      if (queuedValueRef.current != null) {
        // Re-queue via the debounce timer to coalesce rapid edits.
        scheduleSave();
      }
    }
  }, [enabled, onSave]);

  const scheduleSave = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(flush, interval);
    setStatus("pending");
  }, [flush, interval]);

  // Watch ``value`` for changes when dirty.
  useEffect(() => {
    if (!enabled) return undefined;
    if (!dirty) return undefined;
    queuedValueRef.current = value;
    scheduleSave();
    return undefined;
  }, [value, dirty, enabled, scheduleSave]);

  // Warn the user on tab close if a save is still pending.
  useEffect(() => {
    if (!enabled) return undefined;
    const handler = (e) => {
      if (queuedValueRef.current != null || inflightRef.current) {
        e.preventDefault();
        e.returnValue = "";
        return "";
      }
      return undefined;
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [enabled]);

  // Cleanup on unmount.
  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const saveNow = useCallback(async () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (queuedValueRef.current == null) queuedValueRef.current = value;
    await flush();
  }, [flush, value]);

  return { status, savedAt, lastError, saveNow };
}
