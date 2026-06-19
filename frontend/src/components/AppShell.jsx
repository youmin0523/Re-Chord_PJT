import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Sparkles, AudioLines, Library as LibIcon, Plus, Sun, Moon } from "lucide-react";
import { JobLibrary } from "@/components/JobLibrary";
import { LangSwitcher } from "@/components/LangSwitcher";
import { AuthMenu } from "@/components/AuthMenu";
import { ChatWidget } from "@/components/chat/ChatWidget";
import { Toaster } from "@/components/ui/Toaster";
import { useTheme } from "@/lib/useTheme";

export function AppShell({ children }) {
  const [showLib, setShowLib] = useState(false);
  const { pathname } = useLocation();
  const { t } = useTranslation();
  // Library rail makes sense on app pages, not the landing.
  const showRail = pathname !== "/";
  return (
    <div className="min-h-screen flex flex-col">
      <a href="#main-content" className="skip-link">{t("nav.skip_to_main")}</a>
      <Header onOpenLib={() => setShowLib((v) => !v)} libOpen={showLib} showRail={showRail} />
      <div className="flex-1 w-full flex">
        {showRail && (
          <aside
            aria-label={t("nav.library")}
            className={`hidden lg:block shrink-0 border-r border-white/5 bg-white/[0.01] transition-all ${showLib ? "w-72" : "w-0"} overflow-hidden`}
          >
            {showLib && (
              <div className="p-4 sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto">
                <JobLibrary />
              </div>
            )}
          </aside>
        )}
        <div id="main-content" className="flex-1 min-w-0">{children}</div>
      </div>
      <Footer />
      <ChatWidget />
      <Toaster />
    </div>
  );
}

function Brandmark() {
  const [imgOk, setImgOk] = useState(true);

  if (imgOk) {
    return (
      <Link to="/" className="inline-flex items-center gap-2 group" aria-label="Re:Chord">
        <img
          src="/logo.png"
          alt="Re:Chord"
          height={36}
          onError={() => setImgOk(false)}
          className="h-9 w-auto select-none drop-shadow-[0_4px_18px_rgba(139,92,246,0.35)]"
        />
      </Link>
    );
  }
  return (
    <Link to="/" className="inline-flex items-center gap-2 group">
      <motion.span
        whileHover={{ rotate: -8 }}
        className="inline-flex items-center justify-center size-8 rounded-lg bg-gradient-to-br from-violet to-magenta text-white"
      >
        <AudioLines className="size-4" />
      </motion.span>
      <span className="font-extrabold tracking-tight text-xl">
        <span className="gradient-text">Re:Chord</span>
      </span>
      <span className="hidden sm:inline text-[11px] mono uppercase tracking-[0.22em] text-fg-muted/70 ml-1">
        re·record · re·chord
      </span>
    </Link>
  );
}

function Header({ onOpenLib, libOpen, showRail }) {
  const { isDark, toggle: toggleTheme } = useTheme();
  const { t } = useTranslation();
  return (
    <header className="sticky top-0 z-30 backdrop-blur-xl bg-bg0/55 border-b border-white/5">
      <div className="max-w-7xl mx-auto px-3 sm:px-4 md:px-6 h-14 sm:h-16 flex items-center gap-2 sm:gap-3">
        <Brandmark />
        <div className="ml-auto flex items-center gap-1.5 sm:gap-2 text-[11px] mono text-fg-muted">
          {showRail && (
            <button
              type="button"
              onClick={onOpenLib}
              title={libOpen ? t("nav.library_close") : t("nav.library_open")}
              className={`hidden lg:inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-[11px] transition-colors ${libOpen ? "bg-violet/15 text-violet ring-1 ring-violet/30" : "bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"}`}
            >
              <LibIcon className="size-3.5" /> {t("nav.library")}
            </button>
          )}
          <Link
            to="/app"
            title={t("nav.new_job")}
            aria-label={t("nav.new_job")}
            className="inline-flex items-center justify-center sm:gap-1.5 h-8 w-8 sm:w-auto sm:px-3 rounded-full text-[11px] bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
          >
            <Plus className="size-3.5" />
            <span className="hidden sm:inline">{t("nav.new_job")}</span>
          </Link>
          <LangSwitcher />
          <button
            type="button"
            onClick={toggleTheme}
            title={isDark ? t("nav.toggle_theme_light") : t("nav.toggle_theme_dark")}
            className="inline-flex items-center justify-center size-7 rounded-full hover:bg-white/10 text-fg-muted hover:text-fg"
            aria-label={t("nav.theme_toggle_label")}
          >
            {isDark ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
          </button>
          <AuthMenu />
          <span className="hidden sm:inline-flex items-center gap-1.5">
            <span className="inline-block size-1.5 rounded-full bg-emerald-400 animate-pulseGlow" />
            local
          </span>
        </div>
      </div>
    </header>
  );
}

function Footer() {
  const { t } = useTranslation();
  return (
    <footer className="border-t border-white/5 mt-12 py-6 text-[11px] text-fg-muted">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-wrap items-center gap-3">
        <span className="inline-flex items-center gap-1.5">
          <Sparkles className="size-3 text-violet" />
          <span className="font-semibold text-fg">{t("brand.name")}</span>
          <span className="text-fg-muted hidden sm:inline">— {t("brand.tagline")}</span>
        </span>
        <span className="ml-auto inline-flex items-center gap-3">
          <span className="mono">v0.2.0</span>
        </span>
      </div>
    </footer>
  );
}
