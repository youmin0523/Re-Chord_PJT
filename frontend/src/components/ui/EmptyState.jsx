import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * Standardised "nothing here yet" card.
 *
 *   - icon:         lucide-react component (legacy / fallback)
 *   - illustration: one of "waveform" | "score" | "stems" | "library" |
 *                   "performance" | "quality" — picks a custom inline SVG
 *   - cta:          optional call-to-action button
 */
export function EmptyState({
  icon: Icon,
  illustration,
  title,
  hint,
  cta,
  className = "",
  size = "md",
}) {
  const pad = size === "sm" ? "p-5" : "p-8";
  const iconSize = size === "sm" ? "size-9" : "size-12";
  const iconGlyph = size === "sm" ? "size-4" : "size-5";
  const Illustration = ILLUSTRATIONS[illustration];

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("glass rounded-2xl text-center", pad, className)}
    >
      {Illustration ? (
        <div className="mx-auto mb-2" style={{ maxWidth: size === "sm" ? 120 : 180 }}>
          <Illustration />
        </div>
      ) : Icon ? (
        <div
          className={cn(
            "inline-flex items-center justify-center rounded-2xl bg-white/5 text-fg-muted mx-auto mb-2",
            iconSize,
          )}
        >
          <Icon className={iconGlyph} />
        </div>
      ) : null}
      {title && <div className="text-sm font-semibold text-fg">{title}</div>}
      {hint && (
        <div className="text-[12px] text-fg-muted max-w-sm mx-auto leading-relaxed mt-1.5 break-keep">
          {hint}
        </div>
      )}
      {cta && <div className="pt-3">{cta}</div>}
    </motion.div>
  );
}


// ── inline SVG illustrations ────────────────────────────────────────────
// Drawn in our brand palette (violet / cyan / magenta gradients) so they
// blend with the dark theme. Each illustration is ~180×120 viewBox.

const ILLUSTRATIONS = {
  waveform: WaveformIllustration,
  score:    ScoreIllustration,
  stems:    StemsIllustration,
  library:  LibraryIllustration,
  performance: PerformanceIllustration,
  quality:  QualityIllustration,
};


function _Defs({ id }) {
  return (
    <defs>
      <linearGradient id={`es-${id}-grad`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%"  stopColor="#c4b5fd" />
        <stop offset="50%" stopColor="#67e8f9" />
        <stop offset="100%" stopColor="#f9a8d4" />
      </linearGradient>
    </defs>
  );
}

function WaveformIllustration() {
  return (
    <svg viewBox="0 0 180 120" role="img" aria-hidden="true">
      <_Defs id="wave" />
      <g fill="url(#es-wave-grad)" opacity="0.85">
        {[18, 38, 28, 64, 46, 82, 54, 96, 62, 88, 50, 70, 42, 56, 30, 44, 22]
          .map((h, i) => (
            <rect key={i} x={6 + i * 10} y={60 - h / 2} width="6" height={h} rx="3" />
          ))}
      </g>
      <line x1="0" y1="60" x2="180" y2="60" stroke="rgba(255,255,255,0.08)" strokeDasharray="3 4" />
    </svg>
  );
}

function ScoreIllustration() {
  return (
    <svg viewBox="0 0 180 120" role="img" aria-hidden="true">
      <_Defs id="score" />
      <g stroke="rgba(255,255,255,0.18)" strokeWidth="1">
        {[40, 50, 60, 70, 80].map((y) => (
          <line key={y} x1="14" y1={y} x2="166" y2={y} />
        ))}
      </g>
      <path d="M22 32 Q14 50 26 58 Q40 70 28 88 Q14 96 28 92" fill="none"
            stroke="url(#es-score-grad)" strokeWidth="2.4" strokeLinecap="round" />
      {[
        { cx: 60,  cy: 60, sx: 60,  sy: 30 },
        { cx: 96,  cy: 50, sx: 96,  sy: 22 },
        { cx: 132, cy: 70, sx: 132, sy: 40 },
      ].map((n, i) => (
        <g key={i} fill="url(#es-score-grad)">
          <ellipse cx={n.cx} cy={n.cy} rx="6" ry="4.5" transform={`rotate(-18 ${n.cx} ${n.cy})`} />
          <rect x={n.cx + 4} y={n.sy} width="1.6" height={n.cy - n.sy} />
        </g>
      ))}
    </svg>
  );
}

function StemsIllustration() {
  return (
    <svg viewBox="0 0 180 120" role="img" aria-hidden="true">
      <_Defs id="stems" />
      <g>
        {[
          { y: 14, color: "#c4b5fd" },
          { y: 30, color: "#67e8f9" },
          { y: 46, color: "#f9a8d4" },
          { y: 62, color: "#a78bfa" },
          { y: 78, color: "#06b6d4" },
          { y: 94, color: "#ec4899" },
        ].map((row, i) => (
          <g key={i} opacity="0.85">
            <rect x="10" y={row.y} width="160" height="11" rx="3"
                  fill="rgba(255,255,255,0.05)" />
            {Array.from({ length: 28 }).map((_, j) => {
              const h = 3 + ((Math.sin(j + i * 1.7) + 1) * 4);
              return (
                <rect
                  key={j}
                  x={12 + j * 5.6}
                  y={row.y + 5.5 - h / 2}
                  width="3" height={h} rx="1"
                  fill={row.color}
                />
              );
            })}
          </g>
        ))}
      </g>
    </svg>
  );
}

function LibraryIllustration() {
  return (
    <svg viewBox="0 0 180 120" role="img" aria-hidden="true">
      <_Defs id="lib" />
      {[
        { y: 24, w: 144, x: 18, color: "rgba(196,181,253,0.20)", stroke: "#c4b5fd" },
        { y: 50, w: 152, x: 14, color: "rgba(103,232,249,0.20)", stroke: "#67e8f9" },
        { y: 76, w: 160, x: 10, color: "rgba(249,168,212,0.22)", stroke: "#f9a8d4" },
      ].map((c, i) => (
        <g key={i}>
          <rect x={c.x} y={c.y} width={c.w} height="20" rx="6"
                fill={c.color} stroke={c.stroke} strokeWidth="1" />
          <circle cx={c.x + 12} cy={c.y + 10} r="5" fill="url(#es-lib-grad)" opacity="0.8" />
          <rect x={c.x + 24} y={c.y + 6} width={c.w * 0.55} height="3" rx="1.5"
                fill="rgba(255,255,255,0.35)" />
          <rect x={c.x + 24} y={c.y + 12} width={c.w * 0.30} height="3" rx="1.5"
                fill="rgba(255,255,255,0.18)" />
        </g>
      ))}
    </svg>
  );
}

function PerformanceIllustration() {
  return (
    <svg viewBox="0 0 180 120" role="img" aria-hidden="true">
      <_Defs id="perf" />
      <text x="90" y="76" textAnchor="middle"
            fontFamily="Inter, sans-serif" fontWeight="800" fontSize="46"
            fill="url(#es-perf-grad)">Am7</text>
      <text x="90" y="98" textAnchor="middle"
            fontFamily="JetBrains Mono, monospace" fontSize="9"
            fill="rgba(255,255,255,0.45)" letterSpacing="2">NEXT · Dm7</text>
      <g transform="translate(20 18)" stroke="url(#es-perf-grad)" strokeWidth="1.5" fill="none">
        <rect x="0" y="0" width="8" height="14" rx="4" />
        <path d="M-3 9 a7 7 0 0 0 14 0" />
        <line x1="4" y1="16" x2="4" y2="22" />
      </g>
    </svg>
  );
}

function QualityIllustration() {
  return (
    <svg viewBox="0 0 180 120" role="img" aria-hidden="true">
      <_Defs id="qual" />
      {[
        { x: 22, h: 64, label: "SI-SDR" },
        { x: 56, h: 80, label: "Recon" },
        { x: 90, h: 48, label: "Leak" },
        { x: 124, h: 70, label: "MOS" },
      ].map((bar, i) => (
        <g key={i}>
          <rect x={bar.x} y={108 - bar.h} width="20" height={bar.h} rx="3"
                fill="url(#es-qual-grad)" opacity="0.85" />
          <text x={bar.x + 10} y="118" textAnchor="middle"
                fontFamily="JetBrains Mono, monospace" fontSize="7"
                fill="rgba(255,255,255,0.5)">{bar.label}</text>
        </g>
      ))}
      <line x1="10" y1="108" x2="170" y2="108" stroke="rgba(255,255,255,0.18)" />
    </svg>
  );
}
