import { cn } from "@/lib/utils";

/**
 * Confidence visualisation primitives — one piece of UX language used
 * everywhere a model output is shown to the user (key/BPM/chord/lyrics/AUX).
 *
 * Three forms:
 *   <ConfidenceBadge value={0.86} />          // colored pill: "86%"
 *   <ConfidenceBar value={0.86} />            // 4-bar signal-strength style
 *   <ConfidenceDot value={0.86} />            // 6px dot only — for dense lists
 *
 * Every tooltip carries CONFIDENCE_DISCLAIMER so a high % is never read
 * as "guaranteed correct" — honesty memo: AI outputs need an explicit
 * "사람의 검토 권장" hint, especially for users who skim numbers.
 */

export const CONFIDENCE_DISCLAIMER = "AI 추정치 · 정확하지 않을 수 있어요. 중요한 사용 전 사람의 확인 권장.";

function titleFor(value, tierLabel) {
  const pct = Math.round((Number.isFinite(value) ? value : 0) * 100);
  return `AI 신뢰도 ${pct}% · ${tierLabel}\n${CONFIDENCE_DISCLAIMER}`;
}

function bucket(value) {
  // Map a 0..1 confidence to a label + tailwind class set.
  const v = Number.isFinite(value) ? value : 0;
  if (v >= 0.85) {
    return {
      tier: "high",
      label: "높음",
      ring: "ring-emerald-400/40",
      bg:   "bg-emerald-400/15",
      text: "text-emerald-300",
      dot:  "bg-emerald-400",
      bar:  "from-emerald-400 to-cyan",
    };
  }
  if (v >= 0.65) {
    return {
      tier: "mid",
      label: "보통",
      ring: "ring-amber-400/40",
      bg:   "bg-amber-400/15",
      text: "text-amber-300",
      dot:  "bg-amber-400",
      bar:  "from-amber-400 to-rose-400",
    };
  }
  return {
    tier: "low",
    label: "낮음 — 직접 검토 권장",
    ring: "ring-rose-500/40",
    bg:   "bg-rose-500/15",
    text: "text-rose-300",
    dot:  "bg-rose-400",
    bar:  "from-rose-500 to-rose-400",
  };
}

export function ConfidenceBadge({ value, showPct = true, className = "" }) {
  const b = bucket(value);
  const pct = Math.round((value || 0) * 100);
  return (
    <span
      title={titleFor(value, b.label)}
      aria-label={`AI 신뢰도 ${pct}퍼센트, ${b.label}. ${CONFIDENCE_DISCLAIMER}`}
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] mono ring-1",
        b.ring, b.bg, b.text,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", b.dot)} />
      {showPct ? `${pct}%` : b.label}
    </span>
  );
}

export function ConfidenceBar({ value, className = "" }) {
  const v = Math.max(0, Math.min(1, value || 0));
  const b = bucket(v);
  return (
    <div
      title={titleFor(v, b.label)}
      role="img"
      aria-label={`AI 신뢰도 ${Math.round(v * 100)}퍼센트, ${b.label}. ${CONFIDENCE_DISCLAIMER}`}
      className={cn("inline-block w-12 h-1.5 rounded-full bg-white/8 overflow-hidden", className)}
    >
      <div
        className={cn("h-full rounded-full bg-gradient-to-r transition-all", b.bar)}
        style={{ width: `${v * 100}%` }}
      />
    </div>
  );
}

export function ConfidenceDot({ value, className = "" }) {
  const b = bucket(value);
  return (
    <span
      title={titleFor(value, b.label)}
      aria-label={`AI 신뢰도 ${Math.round((value || 0) * 100)}퍼센트, ${b.label}. ${CONFIDENCE_DISCLAIMER}`}
      className={cn("inline-block size-1.5 rounded-full", b.dot, className)}
    />
  );
}

/**
 * Wraps content in a colored underline whose hue tracks confidence.
 * Used for word-level lyric chips.
 */
export function ConfidenceUnderline({ value, children, className = "" }) {
  const v = Math.max(0, Math.min(1, value || 0));
  const b = bucket(v);
  return (
    <span
      title={titleFor(v, b.label)}
      className={cn(
        "inline-block border-b-2 transition-colors",
        b.tier === "high" && "border-emerald-400/70",
        b.tier === "mid" && "border-amber-400/70",
        b.tier === "low" && "border-rose-500/70",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Compact aggregate label: "평균 87% · 단어 142개" */
export function ConfidenceSummary({ avg, count, label = "신뢰도" }) {
  const b = bucket(avg);
  return (
    <span className={cn("inline-flex items-center gap-1.5 mono text-[11px]", b.text)}>
      <span className={cn("size-1.5 rounded-full", b.dot)} />
      {label} 평균 {Math.round((avg || 0) * 100)}% · {count}개
    </span>
  );
}
