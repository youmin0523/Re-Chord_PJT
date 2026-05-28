import { useTranslation } from "react-i18next";
import { Languages } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Compact ko/en switcher. Persists to localStorage via i18next's detector.
 * Lives in the AppShell header so it's discoverable on every page.
 */
const LANGS = [
  { id: "ko", label: "한국어" },
  { id: "en", label: "EN" },
];

export function LangSwitcher({ className = "" }) {
  const { i18n } = useTranslation();
  const current = (i18n.resolvedLanguage || i18n.language || "ko").slice(0, 2);
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <Languages className="size-3 text-fg-muted/70" />
      {LANGS.map((l) => (
        <button
          key={l.id}
          type="button"
          onClick={() => i18n.changeLanguage(l.id)}
          className={
            current === l.id
              ? "px-1.5 py-0.5 rounded text-[10px] mono bg-violet/15 text-violet ring-1 ring-violet/30 lang-active-pill"
              : "px-1.5 py-0.5 rounded text-[10px] mono text-fg-muted hover:text-fg"
          }
          aria-pressed={current === l.id}
        >
          {l.label}
        </button>
      ))}
    </span>
  );
}
