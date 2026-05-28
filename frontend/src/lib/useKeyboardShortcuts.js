/**
 * Global + scoped keyboard shortcut hook.
 *
 *   useKeyboardShortcuts([
 *     { combo: "mod+s",  handler: save,  desc: "저장" },
 *     { combo: "space",  handler: togglePlay, desc: "재생/일시정지" },
 *     { combo: "?",      handler: openHelp, desc: "단축키 도움말" },
 *   ]);
 *
 * combo grammar:
 *   - "mod"  → Ctrl on Win/Linux, Cmd on macOS
 *   - chord with "+": "mod+shift+z"
 *   - single keys: "space", "esc", "?", "/", "k", "1", "ArrowLeft"
 *
 * Shortcuts are ignored while focus is on an <input>, <textarea> or
 * contenteditable, unless `allowInForm: true` is set on the binding.
 */

import { useEffect, useMemo, useState } from "react";

function isMac() {
  return /Mac|iPhone|iPad/.test(navigator.platform);
}

function normalizeKey(k) {
  if (!k) return "";
  const lower = k.toLowerCase();
  if (lower === " ") return "space";
  if (lower === "escape") return "esc";
  return lower;
}

function eventMatches(e, combo) {
  const parts = combo.toLowerCase().split("+").map((p) => p.trim());
  const wantsMod = parts.includes("mod");
  const wantsShift = parts.includes("shift");
  const wantsAlt = parts.includes("alt");
  const key = parts.filter((p) => !["mod", "shift", "alt", "ctrl", "cmd"].includes(p)).pop();

  const evKey = normalizeKey(e.key);
  if (evKey !== key) return false;
  const modPressed = isMac() ? e.metaKey : e.ctrlKey;
  if (wantsMod !== modPressed) return false;
  if (wantsShift !== e.shiftKey) return false;
  if (wantsAlt !== e.altKey) return false;
  return true;
}

function isInForm(target) {
  const tag = (target?.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target?.isContentEditable) return true;
  return false;
}

export function useKeyboardShortcuts(bindings) {
  useEffect(() => {
    if (!bindings?.length) return undefined;
    const onKey = (e) => {
      for (const b of bindings) {
        if (!b?.combo || !b?.handler) continue;
        if (!eventMatches(e, b.combo)) continue;
        if (isInForm(e.target) && !b.allowInForm) continue;
        e.preventDefault();
        b.handler(e);
        return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [bindings]);
}

/**
 * Lightweight modal manager for the "?" shortcut help cheatsheet.
 */
export function useShortcutsHelp(bindings) {
  const [open, setOpen] = useState(false);
  useKeyboardShortcuts(
    useMemo(
      () => [
        { combo: "?", handler: () => setOpen((v) => !v), desc: "단축키 보기" },
        { combo: "esc", handler: () => setOpen(false), desc: "닫기" },
        ...(bindings || []),
      ],
      [bindings],
    ),
  );
  return { open, setOpen };
}

/** Pretty-printer for the cheatsheet UI. */
export function prettyCombo(combo) {
  return combo
    .split("+")
    .map((p) => p.trim())
    .map((p) => {
      if (p === "mod") return isMac() ? "⌘" : "Ctrl";
      if (p === "shift") return isMac() ? "⇧" : "Shift";
      if (p === "alt") return isMac() ? "⌥" : "Alt";
      if (p === "space") return "Space";
      if (p === "esc") return "Esc";
      if (p.startsWith("arrow")) return { arrowleft: "←", arrowright: "→", arrowup: "↑", arrowdown: "↓" }[p];
      return p.length === 1 ? p.toUpperCase() : p;
    })
    .join(isMac() ? "" : " + ");
}
