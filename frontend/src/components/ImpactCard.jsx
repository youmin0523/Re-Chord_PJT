import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { TrendingUp, Music, Wand2, ListMusic } from "lucide-react";

import { getUsageEvents, summarizeImpact, SAVINGS_MIN } from "@/lib/usage";

/**
 * Estimated time-saved card (FDE "정량적 성과 측정"). Presentational — the
 * caller passes job-history `items` / `setlists`; we fold in the key-recommend
 * event log. Renders nothing until there's at least one action, so a fresh
 * guest never sees an empty "0 hours saved" box.
 *
 * Honesty: the number is an *estimate* built from explicit per-action
 * assumptions (SAVINGS_MIN), surfaced in the footnote — never presented as a
 * measurement.
 */
export function ImpactCard({ items, setlists, sinceDays = 30 }) {
  const { t } = useTranslation();
  const summary = useMemo(
    () => summarizeImpact({ items, setlists }, getUsageEvents(), { sinceDays }),
    [items, setlists, sinceDays],
  );

  if (!summary.songs && !summary.keyRecs && !summary.setlistSongs) return null;

  const stats = [
    { icon: Music, n: summary.songs, label: t("impact.songs", { defaultValue: "곡" }) },
    { icon: Wand2, n: summary.keyRecs, label: t("impact.keyrecs", { defaultValue: "키추천" }) },
    { icon: ListMusic, n: summary.setlistSongs, label: t("impact.setlist", { defaultValue: "셋리스트곡" }) },
  ];
  const assumptions = t("impact.assumptions", {
    defaultValue: `가정: 곡 ${SAVINGS_MIN.song_processed}분 · 키추천 ${SAVINGS_MIN.key_recommended}분 · 셋리스트곡 ${SAVINGS_MIN.setlist_song}분 절감`,
    song: SAVINGS_MIN.song_processed,
    keyrec: SAVINGS_MIN.key_recommended,
    set: SAVINGS_MIN.setlist_song,
  });

  return (
    <div className="rounded-md bg-gradient-to-br from-violet/10 to-cyan/5 ring-1 ring-violet/20 px-2.5 py-2 space-y-1.5">
      <div className="flex items-center gap-1.5 text-[10px] mono uppercase tracking-[0.18em] text-fg-muted">
        <TrendingUp className="size-3 text-violet" />
        {t("impact.title", { defaultValue: "이번 달 절감 (추정)" })}
        <span className="ml-auto mono text-[10px] text-fg-muted/70">{summary.sinceDays}d</span>
      </div>

      <div className="flex items-baseline gap-1">
        <span className="text-xl font-semibold text-fg">~{summary.hours}</span>
        <span className="text-[11px] text-fg-muted">{t("impact.hours", { defaultValue: "시간" })}</span>
      </div>

      <div className="flex flex-wrap gap-1">
        {stats.map(({ icon: Icon, n, label }) => (
          <span
            key={label}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/5 text-[10px] text-fg-muted"
            title={label}
          >
            <Icon className="size-2.5" />
            <span className="mono text-fg">{n}</span> {label}
          </span>
        ))}
      </div>

      <div className="text-[9px] text-fg-muted/60 leading-snug" title={assumptions}>
        {t("impact.disclaimer", { defaultValue: "실측 아님 · 조정 가능한 추정치" })}
      </div>
    </div>
  );
}
