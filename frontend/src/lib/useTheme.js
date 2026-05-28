/**
 * Dark / light theme toggle.
 *
 * The site is designed dark-first — vivid violet/cyan/magenta gradients
 * against a deep-purple background. Light mode is a high-contrast,
 * print-friendly variant that flips bg/fg tokens and dims the gradient
 * orbs. Persists to localStorage; respects ``prefers-color-scheme`` on
 * first run if no override is set.
 */

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "rechord:theme";

function resolveInitial() {
  if (typeof window === "undefined") return "dark";
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch { /* ignore */ }
  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)")?.matches;
  return prefersLight ? "light" : "dark";
}

function applyTheme(t) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("theme-light", t === "light");
  root.classList.toggle("theme-dark", t === "dark");
  root.setAttribute("data-theme", t);
}

export function useTheme() {
  const [theme, setTheme] = useState(() => resolveInitial());

  useEffect(() => { applyTheme(theme); }, [theme]);

  const toggle = useCallback(() => {
    setTheme((cur) => {
      const next = cur === "dark" ? "light" : "dark";
      try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
      return next;
    });
  }, []);

  return { theme, toggle, isDark: theme === "dark" };
}
