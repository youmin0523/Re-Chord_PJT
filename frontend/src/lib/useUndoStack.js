/**
 * Generic undo/redo stack hook for editors (lyrics, chords, AUX cues, ...).
 *
 * Pattern:
 *   const { state, set, undo, redo, canUndo, canRedo, reset, dirty } =
 *     useUndoStack(initialState);
 *
 * - `set(next)` pushes a new state; old state goes onto the undo stack.
 * - `undo()` / `redo()` walk through history without further allocations.
 * - `reset(initial)` clears history and starts over (use after server save).
 * - `dirty` is true when there are unsaved local changes since the last reset.
 *
 * The hook also wires Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z when `bindKeyboard` is
 * true (default). Pass `false` if you only want programmatic control.
 */

import { useCallback, useRef, useState } from "react";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";

const MAX_DEPTH = 100;

export function useUndoStack(initial, { bindKeyboard = true } = {}) {
  const [state, setState] = useState(initial);
  const undoRef = useRef([]);
  const redoRef = useRef([]);
  const baselineRef = useRef(initial);
  const [, forceRender] = useState(0);
  const bump = () => forceRender((n) => n + 1);

  // Hard reset (after a server-side save commits the current state).
  const reset = useCallback((next) => {
    setState(next);
    undoRef.current = [];
    redoRef.current = [];
    baselineRef.current = next;
    bump();
  }, []);

  const set = useCallback((updater) => {
    setState((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      // Push prev onto undo stack, clear redo (new branch).
      undoRef.current = [...undoRef.current, prev].slice(-MAX_DEPTH);
      redoRef.current = [];
      return next;
    });
    bump();
  }, []);

  const undo = useCallback(() => {
    if (!undoRef.current.length) return;
    setState((prev) => {
      const last = undoRef.current[undoRef.current.length - 1];
      undoRef.current = undoRef.current.slice(0, -1);
      redoRef.current = [...redoRef.current, prev].slice(-MAX_DEPTH);
      return last;
    });
    bump();
  }, []);

  const redo = useCallback(() => {
    if (!redoRef.current.length) return;
    setState((prev) => {
      const next = redoRef.current[redoRef.current.length - 1];
      redoRef.current = redoRef.current.slice(0, -1);
      undoRef.current = [...undoRef.current, prev].slice(-MAX_DEPTH);
      return next;
    });
    bump();
  }, []);

  useKeyboardShortcuts(
    bindKeyboard
      ? [
          { combo: "mod+z", handler: undo, desc: "되돌리기" },
          { combo: "mod+shift+z", handler: redo, desc: "다시 실행" },
        ]
      : [],
  );

  // Best-effort "dirty" — works for primitives + arrays-of-objects by JSON.
  const dirty = useDirtyFlag(state, baselineRef.current);

  return {
    state,
    set,
    undo,
    redo,
    reset,
    canUndo: undoRef.current.length > 0,
    canRedo: redoRef.current.length > 0,
    depth: undoRef.current.length,
    dirty,
  };
}

function useDirtyFlag(current, baseline) {
  const lastRef = useRef({ json: "", dirty: false });
  let currJson = "";
  let baseJson = "";
  try {
    currJson = JSON.stringify(current);
    baseJson = JSON.stringify(baseline);
  } catch {
    return false;
  }
  if (lastRef.current.json !== currJson) {
    lastRef.current = { json: currJson, dirty: currJson !== baseJson };
  }
  return lastRef.current.dirty;
}
