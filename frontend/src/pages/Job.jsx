import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Share2, Keyboard, Play } from "lucide-react";

import { ProgressPanel } from "@/components/ProgressPanel";
import { ResultPanel } from "@/components/ResultPanel";
import { ErrorCard } from "@/components/ErrorCard";
import { ShareDialog } from "@/components/ShareDialog";
import { ShortcutsHelp } from "@/components/ShortcutsHelp";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { getJob } from "@/lib/api";
import { useJobHistory } from "@/lib/useJobHistory";
import { useShortcutsHelp } from "@/lib/useKeyboardShortcuts";

export default function Job() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [params] = useSearchParams();
  const embed = params.get("embed") === "1";
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);
  const [shareOpen, setShareOpen] = useState(false);
  const { upsert, touch } = useJobHistory();

  const refreshFinal = async () => {
    try {
      const next = await getJob(id);
      setJob(next);
      upsert({
        id: next.id,
        title: next.meta?.source_title || next.input,
        mode: next.options?.mode,
        createdAt: (next.created_at || 0) * 1000 || Date.now(),
      });
    } catch { /* ignore */ }
  };

  useEffect(() => {
    let cancelled = false;
    getJob(id)
      .then((j) => {
        if (cancelled) return;
        setJob(j);
        upsert({
          id: j.id,
          title: j.meta?.source_title || j.input,
          mode: j.options?.mode,
          createdAt: (j.created_at || 0) * 1000 || Date.now(),
        });
        touch(j.id);
      })
      .catch((e) => !cancelled && setErr(e.message));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Keyboard shortcuts (cheatsheet via ?)
  const helpBindings = [
    { group: t("job.shortcut_group_nav"),   combo: "g h",         desc: t("job.shortcut_home_long") },
    { group: t("job.shortcut_group_share"), combo: "mod+shift+c", desc: t("job.shortcut_share_link"), handler: () => setShareOpen(true) },
    { group: t("job.shortcut_group_edit"),  combo: "mod+z",       desc: t("job.shortcut_undo") },
    { group: t("job.shortcut_group_edit"),  combo: "mod+shift+z", desc: t("job.shortcut_redo") },
  ];
  const help = useShortcutsHelp(
    helpBindings.filter((b) => b.handler),
  );

  // When embedded (iframe), strip chrome so the host page controls layout.
  const wrapClass = embed
    ? "min-h-screen max-w-3xl mx-auto px-3 sm:px-4 py-3 sm:py-4 space-y-4"
    : "min-h-screen max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10 lg:py-16 space-y-5 sm:space-y-6";

  return (
    <main className={wrapClass}>
      {!embed && (
        <div className="flex items-center gap-2">
          <Link
            to="/app"
            className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg transition-colors"
          >
            <ArrowLeft className="size-3.5" /> {t("job.back_to_new")}
          </Link>
          <span className="ml-auto inline-flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => help.setOpen(true)}
              className="inline-flex items-center justify-center size-8 rounded-full hover:bg-white/5 text-fg-muted hover:text-fg"
              title={t("job.shortcuts_title")}
              aria-label={t("job.shortcuts_aria")}
            >
              <Keyboard className="size-4" />
            </button>
            <Link
              to={`/perform/job/${id}`}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-gradient-to-br from-violet/20 to-magenta/20 hover:from-violet/30 hover:to-magenta/30 text-violet ring-1 ring-violet/25"
              title={t("job.perform_title")}
            >
              <Play className="size-3.5" /> {t("job.perform_label")}
            </Link>
            <button
              type="button"
              onClick={() => setShareOpen(true)}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
            >
              <Share2 className="size-3.5" /> {t("job.share")}
            </button>
          </span>
        </div>
      )}

      {!embed && (
        <motion.h1
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-2xl sm:text-3xl font-bold tracking-tight"
        >
          <span className="text-fg-muted">JOB </span>
          <span className="gradient-text mono">{id}</span>
          {job?.meta?.source_title && (
            <span className="block text-sm font-normal text-fg-muted mt-1 break-keep">
              {job.meta.source_title}
            </span>
          )}
        </motion.h1>
      )}

      {err && (
        <ErrorCard
          error={err}
          onRetry={() => { setErr(null); refreshFinal(); }}
        />
      )}

      {!job && !err && <SkeletonCard />}

      {job && (
        <>
          <ProgressPanel job={job} onDone={refreshFinal} />
          {job.status === "done" && <ResultPanel job={job} />}
          {job.status === "error" && (
            <ErrorCard
              error={job.error || "Unknown error"}
              jobInput={job.input}
              onRetry={refreshFinal}
            />
          )}
        </>
      )}

      {job && (
        <>
          <ShareDialog open={shareOpen} onClose={() => setShareOpen(false)} job={job} />
          <ShortcutsHelp
            open={help.open}
            onClose={() => help.setOpen(false)}
            bindings={helpBindings}
          />
        </>
      )}
    </main>
  );
}
