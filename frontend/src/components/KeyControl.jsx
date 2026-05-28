import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Music2, Users, Minus, Plus, RotateCcw } from "lucide-react";
import { Slider } from "@/components/ui/Slider";
import { assessVocalRange, VOCAL_RANGES } from "@/lib/transpose";

const clampSt = (n) => Math.max(-12, Math.min(12, Math.round(n)));

// Interval names are universal in music notation — Korean has them too but
// short pop labels suit either UI language.
const INTERVAL_LABELS = {
  ko: ["원음","단2","장2","단3","장3","완4","트라이톤","완5","단6","장6","단7","장7","옥타브"],
  en: ["unison","m2","M2","m3","M3","P4","TT","P5","m6","M6","m7","M7","octave"],
};

export function KeyControl({ semitones, onChange, detectedKey, melodyRange }) {
  // melodyRange: {lowMidi, highMidi} — passed in when the backend has
  // analysed the vocal stem (or any monophonic part). When absent the
  // audience-range hint is hidden entirely so we don't fake numbers.
  const { t, i18n } = useTranslation();
  const [audience, setAudience] = useState("mixed");
  const range = melodyRange ? assessVocalRange(melodyRange, semitones, audience) : null;

  const sign = semitones === 0 ? "" : semitones > 0 ? "+" : "-";
  const abs = Math.abs(semitones);
  const lang = (i18n.resolvedLanguage || i18n.language || "ko").slice(0, 2);
  const intervals = INTERVAL_LABELS[lang] || INTERVAL_LABELS.ko;
  const intervalLabel = abs <= 12 ? intervals[abs] : `${abs} semitone`;

  return (
    <div className="glass rounded-2xl p-4 sm:p-5">
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        <div className="flex items-center gap-2 text-fg">
          <Music2 className="size-4 text-violet" />
          <span className="text-sm font-semibold">{t("keyctl.title", { defaultValue: "키" })}</span>
        </div>
        {detectedKey && (
          <span className="mono text-[11px] text-fg-muted">
            {t("keyctl.detected", { defaultValue: "감지" })}: <span className="text-cyan">{detectedKey}</span>
          </span>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="mono text-2xl sm:text-3xl font-semibold text-fg">
            {sign}{Number(semitones).toFixed(0)}
          </span>
          <span className="text-xs text-fg-muted truncate">semitone · {intervalLabel}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => onChange(clampSt(semitones - 1))}
            disabled={semitones <= -12}
            aria-label={t("keyctl.step_down", { defaultValue: "키 -1" })}
            className="inline-flex items-center justify-center size-9 rounded-lg bg-white/5 hover:bg-violet/15 text-fg disabled:opacity-30 disabled:hover:bg-white/5 ring-1 ring-white/10 touch-manipulation"
          >
            <Minus className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => onChange(0)}
            disabled={semitones === 0}
            aria-label={t("keyctl.reset", { defaultValue: "원래 키로" })}
            title={t("keyctl.reset", { defaultValue: "원래 키로" })}
            className="inline-flex items-center justify-center size-9 rounded-lg bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg disabled:opacity-30 ring-1 ring-white/10"
          >
            <RotateCcw className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onChange(clampSt(semitones + 1))}
            disabled={semitones >= 12}
            aria-label={t("keyctl.step_up", { defaultValue: "키 +1" })}
            className="inline-flex items-center justify-center size-9 rounded-lg bg-white/5 hover:bg-violet/15 text-fg disabled:opacity-30 disabled:hover:bg-white/5 ring-1 ring-white/10 touch-manipulation"
          >
            <Plus className="size-4" />
          </button>
        </div>
      </div>

      <Slider
        min={-12}
        max={12}
        step={1}
        value={semitones}
        onChange={(e) => onChange(Number(e.target.value))}
        accent="violet"
      />
      <div className="flex justify-between mt-2 mono text-[10px] text-fg-muted">
        <span>-12</span><span>0</span><span>+12</span>
      </div>

      {Math.abs(semitones) > 5 && (
        <div className="mt-3 text-[11px] text-amber/90 bg-amber/10 rounded-md px-2 py-1.5">
          {t("keyctl.artefact_warn", { defaultValue: "±5 semitone 이상은 약간의 아티팩트가 생길 수 있어요." })}
        </div>
      )}

      {melodyRange && range && (
        <div className="mt-3 rounded-md bg-white/[0.03] ring-1 ring-white/5 px-2.5 py-2 space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] mono uppercase tracking-[0.18em] text-fg-muted">
            <Users className="size-3" /> {t("keyctl.range_check", { defaultValue: "음역 체크" })}
          </div>
          <div className="flex flex-wrap gap-1">
            {Object.entries(VOCAL_RANGES).map(([id, r]) => (
              <button
                key={id}
                type="button"
                onClick={() => setAudience(id)}
                className={
                  audience === id
                    ? "px-2 py-0.5 rounded-full text-[10px] bg-violet/20 text-violet ring-1 ring-violet/40"
                    : "px-2 py-0.5 rounded-full text-[10px] bg-white/5 text-fg-muted hover:text-fg"
                }
                title={r.label}
              >
                {r.label.split(" ")[0]}
              </button>
            ))}
          </div>
          <div className={
            range.ok
              ? "text-[11px] text-emerald-300"
              : "text-[11px] text-amber-300"
          }>
            {range.ok ? "✓" : "⚠"} {range.advice}
          </div>
        </div>
      )}
    </div>
  );
}
