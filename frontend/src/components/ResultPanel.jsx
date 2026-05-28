import { lazy, Suspense } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  Download,
  Music,
  Mic,
  Sparkles,
  Play,
  Layers3,
  ListMusic,
  Activity,
  Headphones,
  Sliders,
  RotateCw,
} from "lucide-react";
import { downloadArtifact } from "@/lib/api";
import { trackFilename } from "@/lib/utils";
import { Tabs } from "@/components/ui/Tabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { ConfidenceBadge } from "@/components/ui/ConfidenceBadge";
import { Tooltip } from "@/components/ui/Tooltip";
import { SkeletonCard } from "@/components/ui/Skeleton";

// Light, always-shown panels — keep eager.
import { ABCompare } from "@/components/ABCompare";
import { NotesEditor } from "@/components/NotesEditor";

// Heavy / per-tab panels — split into separate chunks so the initial Job
// page bundle stays small. Each chunk loads only when its tab is opened.
const StemsMixer          = lazy(() => import("@/components/StemsMixer").then((m) => ({ default: m.StemsMixer })));
const PracticePanel       = lazy(() => import("@/components/PracticePanel").then((m) => ({ default: m.PracticePanel })));
const ScorePanel          = lazy(() => import("@/components/ScorePanel").then((m) => ({ default: m.ScorePanel })));
const MonitorPanel        = lazy(() => import("@/components/MonitorPanel").then((m) => ({ default: m.MonitorPanel })));
const WaveformPanel       = lazy(() => import("@/components/WaveformPanel").then((m) => ({ default: m.WaveformPanel })));
const QualityPanel        = lazy(() => import("@/components/QualityPanel").then((m) => ({ default: m.QualityPanel })));
const BackendSummaryPanel = lazy(() => import("@/components/BackendSummaryPanel").then((m) => ({ default: m.BackendSummaryPanel })));
const FeedbackPanel       = lazy(() => import("@/components/FeedbackPanel").then((m) => ({ default: m.FeedbackPanel })));
const LyricsEditor        = lazy(() => import("@/components/LyricsEditor").then((m) => ({ default: m.LyricsEditor })));
const AuxCuesEditor       = lazy(() => import("@/components/AuxCuesEditor").then((m) => ({ default: m.AuxCuesEditor })));
const RecordingPanel      = lazy(() => import("@/components/RecordingPanel").then((m) => ({ default: m.RecordingPanel })));
const MasteringPanel      = lazy(() => import("@/components/MasteringPanel").then((m) => ({ default: m.MasteringPanel })));
const AutotunePanel       = lazy(() => import("@/components/AutotunePanel").then((m) => ({ default: m.AutotunePanel })));
const WorshipPanel        = lazy(() => import("@/components/WorshipPanel").then((m) => ({ default: m.WorshipPanel })));
const AdvancedExportPanel = lazy(() => import("@/components/AdvancedExportPanel").then((m) => ({ default: m.AdvancedExportPanel })));

/** Tab-specific skeletons — preview the layout that's about to appear so
 * the user doesn't see a generic shimmer card while a panel chunk loads. */
function PanelFallback({ kind = "default" }) {
  const Item = ({ h = "h-9" }) => <div className={`bg-white/[0.04] ${h} rounded-md animate-pulse`} />;
  if (kind === "play") {
    return (
      <div className="space-y-4">
        <div className="glass rounded-2xl p-4 space-y-3">
          <Item h="h-3" />
          <div className="flex gap-1.5">
            <Item h="h-8" /><Item h="h-8" /><Item h="h-8" />
          </div>
          <Item h="h-16" />
        </div>
        <SkeletonCard className="opacity-60" />
      </div>
    );
  }
  if (kind === "score") {
    return (
      <div className="space-y-4">
        <div className="glass rounded-2xl p-5 space-y-2">
          <Item h="h-3" />
          <div className="space-y-2 pt-2">
            {[1, 2, 3, 4, 5].map((y) => <Item key={y} h="h-px bg-white/8" />)}
          </div>
          <Item h="h-64" />
        </div>
      </div>
    );
  }
  if (kind === "master") {
    return (
      <div className="space-y-4">
        <SkeletonCard className="opacity-60" />
        <SkeletonCard className="opacity-50" />
      </div>
    );
  }
  return <SkeletonCard className="opacity-70" />;
}

export function ResultPanel({ job }) {
  const { t } = useTranslation();
  if (job.status !== "done") return null;

  const isStems = job.options?.mode === "stems";
  const hasScore = Object.keys(job.artifacts || {}).some((k) => k.startsWith("score_"));
  const hasMonitor = !!job.artifacts?.monitor_track || !!job.artifacts?.click_track;
  const hasPlayable = !!job.artifacts?.instrumental_final
    || !!job.artifacts?.vocals_final
    || !!job.artifacts?.monitor_track;
  const hasQuality = job.meta?.quality_grade != null;
  const hasLyrics = !!job.artifacts?.lyrics_json;

  return (
    <div className="space-y-5">
      <SummaryCard job={job} />

      <Tabs
        tabs={[
          {
            id: "play",
            label: t("result.tab_play"),
            icon: <Play className="size-3.5" />,
            content: (
              <Suspense fallback={<PanelFallback kind="play" />}>
                <div className="space-y-5">
                  {hasPlayable && <ABCompare job={job} />}
                  {hasMonitor && <MonitorPanel job={job} />}
                  {hasPlayable && <WaveformPanel job={job} />}
                  <PracticePanel job={job} />
                  <RecordingPanel job={job} />
                  <NotesEditor job={job} />
                  {!hasPlayable && (
                    <EmptyState
                      illustration="waveform"
                      title={t("result.empty_playable_title")}
                      hint={t("result.empty_playable_hint")}
                    />
                  )}
                </div>
              </Suspense>
            ),
          },
          {
            id: "stems",
            label: t("result.tab_stems"),
            icon: <Layers3 className="size-3.5" />,
            badge: isStems ? "6" : null,
            content: (
              <Suspense fallback={<PanelFallback kind="default" />}>
                <div className="space-y-5">
                  {isStems ? (
                    <StemsMixer job={job} />
                  ) : (
                    <EmptyState
                      illustration="stems"
                      title={t("result.empty_stems_title")}
                      hint={t("result.empty_stems_hint")}
                    />
                  )}
                </div>
              </Suspense>
            ),
          },
          {
            id: "score",
            label: t("result.tab_score"),
            icon: <ListMusic className="size-3.5" />,
            badge: hasLyrics ? t("result.score_badge_lyrics") : null,
            content: (
              <Suspense fallback={<PanelFallback kind="score" />}>
                <div className="space-y-5">
                  {hasLyrics && <LyricsEditor job={job} />}
                  {hasScore && <AuxCuesEditor job={job} />}
                  {hasScore ? (
                    <ScorePanel job={job} />
                  ) : (
                    <EmptyState
                      illustration="score"
                      title={t("result.empty_score_title")}
                      hint={t("result.empty_score_hint")}
                    />
                  )}
                </div>
              </Suspense>
            ),
          },
          {
            id: "master",
            label: t("result.tab_master"),
            icon: <Sliders className="size-3.5" />,
            content: (
              <Suspense fallback={<PanelFallback kind="master" />}>
                <div className="space-y-5">
                  {hasPlayable ? (
                    <>
                      <MasteringPanel job={job} />
                      <AutotunePanel job={job} />
                      <WorshipPanel job={job} />
                      <AdvancedExportPanel job={job} />
                    </>
                  ) : (
                    <EmptyState
                      icon={Sliders}
                      title={t("result.empty_master_title")}
                      hint={t("result.empty_master_hint")}
                    />
                  )}
                </div>
              </Suspense>
            ),
          },
          {
            id: "quality",
            label: t("result.tab_quality"),
            icon: <Activity className="size-3.5" />,
            badge: hasQuality ? job.meta.quality_grade : null,
            content: (
              <Suspense fallback={<PanelFallback kind="default" />}>
                <div className="space-y-5">
                  {hasQuality ? <QualityPanel job={job} /> : (
                    <EmptyState
                      illustration="quality"
                      title={t("result.empty_quality_title")}
                      hint={t("result.empty_quality_hint")}
                    />
                  )}
                  <BackendSummaryPanel job={job} />
                  <FeedbackPanel job={job} />
                  <MetadataCard job={job} />
                </div>
              </Suspense>
            ),
          },
        ]}
        defaultTab="play"
        mobileLayout="accordion"
      />
    </div>
  );
}

function SummaryCard({ job }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const meta = job.meta || {};
  const opts = job.options || {};
  const ext = opts.format;
  const instPath = job.artifacts["instrumental_final"];
  const vocPath = job.artifacts["vocals_final"];

  const regenerate = () => {
    navigate("/app", {
      state: {
        regenerateFrom: {
          options: opts,
          sourceTitle: meta.source_title || meta.title || null,
        },
      },
    });
  };

  const download = async (kind, role) => {
    const realExt = ext === "aac" ? "m4a" : ext === "aiff" ? "aif" : ext;
    const filename = trackFilename(job, role, realExt);
    await downloadArtifact(job.id, kind, filename);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-4 sm:p-6 space-y-4 sm:space-y-5 glow-violet"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-violet shrink-0" />
        <span className="text-sm font-semibold">{t("result.summary_complete")}</span>
        <button
          type="button"
          onClick={regenerate}
          className="ml-auto inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-violet/10 hover:bg-violet/20 text-violet text-[11px] ring-1 ring-violet/30 hover:ring-violet/50 transition-colors"
          title={t("result.regenerate_tooltip", { defaultValue: "이 곡의 설정을 가져와서 다른 옵션으로 다시 변환" })}
        >
          <RotateCw className="size-3" />
          {t("result.regenerate", { defaultValue: "다시 변환" })}
        </button>
        <span className="mono text-[10px] sm:text-[11px] text-fg-muted truncate hidden sm:inline" title={job.id}>{job.id}</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3 mono text-[11px]">
        {meta.key_name && (
          <Stat
            label={t("result.stat_key")}
            value={meta.key_name}
            confidence={meta.key_confidence}
            tooltip={t("result.key_tooltip")}
          />
        )}
        {meta.bpm && (
          <Stat
            label={t("result.stat_bpm")}
            value={meta.bpm.toFixed(1)}
            confidence={meta.bpm_confidence}
            tooltip={t("result.bpm_tooltip")}
          />
        )}
        <Stat label={t("result.stat_format")} value={opts.format?.toUpperCase() || "—"}
              sub={`${(opts.sample_rate ?? 0) / 1000} kHz · ${opts.bit_depth}-bit`} />
        {meta.source_duration && (
          <Stat label={t("result.stat_duration")} value={`${(meta.source_duration / 60).toFixed(2)} ${t("result.minutes_suffix")}`} />
        )}
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        {instPath && (
          <DownloadCard
            onClick={() => download("instrumental_final", "MR")}
            icon={Music}
            title="Instrumental (MR)"
            useCase={t("result.dl_mr_use_case")}
            color="violet"
          />
        )}
        {vocPath && (
          <DownloadCard
            onClick={() => download("vocals_final", "vocals")}
            icon={Mic}
            title="Vocals"
            useCase={t("result.dl_voc_use_case")}
            color="magenta"
          />
        )}
      </div>

      <div className="flex items-center gap-2 text-[11px] text-fg-muted/80">
        <Headphones className="size-3" />
        {t("result.dl_tip")}
      </div>
    </motion.div>
  );
}

function Stat({ label, value, sub, confidence, tooltip }) {
  const inner = (
    <div className="rounded-lg bg-white/5 p-2.5">
      <div className="flex items-center justify-between gap-1">
        <span className="text-fg-muted">{label}</span>
        {confidence != null && (
          <ConfidenceBadge value={confidence} showPct className="!text-[9px]" />
        )}
      </div>
      <div className="text-fg text-sm">{value}</div>
      {sub && <div className="text-fg-muted/60 text-[10px]">{sub}</div>}
    </div>
  );
  if (tooltip) return <Tooltip content={tooltip}>{inner}</Tooltip>;
  return inner;
}

function DownloadCard({ onClick, icon: Icon, title, useCase, color }) {
  const { t } = useTranslation();
  const map = {
    violet:  "from-violet/15 to-cyan/10  ring-violet/30  hover:ring-violet/50  text-violet",
    magenta: "from-magenta/15 to-amber/10 ring-magenta/30 hover:ring-magenta/50 text-magenta",
  };
  return (
    <motion.button
      whileHover={{ y: -2 }}
      onClick={onClick}
      className={`rounded-2xl p-4 text-left bg-gradient-to-br ring-1 transition-all ${map[color]}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon className="size-4" />
        <span className="text-sm font-semibold text-fg">{title}</span>
      </div>
      {useCase && (
        <div className="text-[11px] text-fg-muted mb-2">{useCase}</div>
      )}
      <div className="inline-flex items-center gap-1.5 text-xs">
        <Download className="size-3.5" /> {t("result.dl_pick_folder")}
      </div>
    </motion.button>
  );
}

function MetadataCard({ job }) {
  const { t } = useTranslation();
  const meta = job.meta || {};
  const opts = job.options || {};
  const modelsCount = (opts.models ?? []).length;
  const countSuffix = t("result.meta_models_count_suffix");
  return (
    <div className="glass rounded-2xl p-5 space-y-3">
      <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
        {t("result.meta_title")}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mono text-[11px]">
        <Stat label={t("result.meta_mode")} value={opts.mode ?? "—"} />
        <Stat label={t("result.meta_ensemble")} value={opts.ensemble_method ?? "—"} />
        <Stat label={t("result.meta_src_sr")} value={meta.source_sr ? `${meta.source_sr} Hz` : "—"} />
        <Stat label={t("result.meta_src_codec")} value={meta.source_codec ?? "—"} />
        <Stat label={t("result.meta_work_sr")} value={meta.work_sr ? `${meta.work_sr} Hz` : "—"} />
        <Stat label={t("result.meta_models")} value={`${modelsCount}${countSuffix}`} />
      </div>
    </div>
  );
}
