import { useTranslation } from "react-i18next";
import { Gauge, Minus, Plus, RotateCcw } from "lucide-react";
import { Slider } from "@/components/ui/Slider";

const clampPct = (n) => Math.max(50, Math.min(200, Math.round(n)));

export function TempoControl({ ratio, onChangeRatio, detectedBpm }) {
  const { t } = useTranslation();
  const pct = Math.round(ratio * 100);
  const targetBpm = detectedBpm ? detectedBpm * ratio : null;
  const setPct = (next) => onChangeRatio(clampPct(next) / 100);

  return (
    <div className="glass rounded-2xl p-4 sm:p-5">
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        <div className="flex items-center gap-2 text-fg">
          <Gauge className="size-4 text-cyan" />
          <span className="text-sm font-semibold">{t("tempo.title")}</span>
        </div>
        {detectedBpm && (
          <span className="mono text-[11px] text-fg-muted">
            {t("keyctl.detected")}: <span className="text-cyan">{detectedBpm.toFixed(1)} BPM</span>
          </span>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="mono text-2xl sm:text-3xl font-semibold text-fg">{pct}</span>
          <span className="text-xs text-fg-muted truncate">{t("tempo.pct_of_original", { defaultValue: "% of original" })}</span>
          {targetBpm && (
            <span className="mono text-xs text-cyan ml-2 shrink-0">
              ≈ {targetBpm.toFixed(1)} BPM
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => setPct(pct - 5)}
            disabled={pct <= 50}
            aria-label={t("tempo.step_down", { defaultValue: "템포 -5%" })}
            className="inline-flex items-center justify-center size-9 rounded-lg bg-white/5 hover:bg-cyan/15 text-fg disabled:opacity-30 disabled:hover:bg-white/5 ring-1 ring-white/10 touch-manipulation"
          >
            <Minus className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => onChangeRatio(1)}
            disabled={pct === 100}
            aria-label={t("tempo.reset", { defaultValue: "원래 템포로" })}
            title={t("tempo.reset", { defaultValue: "원래 템포로" })}
            className="inline-flex items-center justify-center size-9 rounded-lg bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg disabled:opacity-30 ring-1 ring-white/10"
          >
            <RotateCcw className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setPct(pct + 5)}
            disabled={pct >= 200}
            aria-label={t("tempo.step_up", { defaultValue: "템포 +5%" })}
            className="inline-flex items-center justify-center size-9 rounded-lg bg-white/5 hover:bg-cyan/15 text-fg disabled:opacity-30 disabled:hover:bg-white/5 ring-1 ring-white/10 touch-manipulation"
          >
            <Plus className="size-4" />
          </button>
        </div>
      </div>

      <Slider
        min={50}
        max={200}
        step={1}
        value={pct}
        onChange={(e) => onChangeRatio(Number(e.target.value) / 100)}
        accent="cyan"
      />
      <div className="flex justify-between mt-2 mono text-[10px] text-fg-muted">
        <span>50%</span><span>100%</span><span>200%</span>
      </div>

      {(pct < 75 || pct > 130) && (
        <div className="mt-3 text-[11px] text-amber/90 bg-amber/10 rounded-md px-2 py-1.5">
          {t("tempo.warn", { defaultValue: "±25% 이상 변경 시 transient/공간감에 약간의 변화가 발생할 수 있어요." })}
        </div>
      )}
    </div>
  );
}
