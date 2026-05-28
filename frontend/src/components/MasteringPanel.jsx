import { useState } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Sliders, Loader2, Check, Download } from "lucide-react";
import { masterArtifact, artifactUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * LUFS-target loudness normalisation + 3-band EQ panel.
 *
 * Wraps the backend ``POST /jobs/{id}/master`` endpoint. Lives in the
 * "재생/비교" tab of ResultPanel so the user can master after they're
 * satisfied with the separation.
 */

// Platform labels are mostly brand names; only "custom" needs i18n.
const PLATFORM_IDS = [
  { id: "youtube",   label: "YouTube",            lufs: -14, sub: "−14 LUFS" },
  { id: "spotify",   label: "Spotify (Loud)",     lufs: -14, sub: "−14 LUFS" },
  { id: "spotify_q", label: "Spotify (Quiet)",    lufs: -19, sub: "−19 LUFS" },
  { id: "apple",     label: "Apple Music",        lufs: -16, sub: "−16 LUFS" },
  { id: "tidal",     label: "Tidal",              lufs: -14, sub: "−14 LUFS" },
  { id: "broadcast", label: "Broadcast (EBU R128)", lufs: -23, sub: "−23 LUFS" },
];

export function MasteringPanel({ job }) {
  const { t } = useTranslation();
  // Build the platform list at render so "custom" follows the locale.
  const PLATFORMS = [
    ...PLATFORM_IDS,
    { id: "custom", label: t("mastering2.label_custom"), lufs: -14, sub: "" },
  ];
  const [platform, setPlatform] = useState("spotify");
  const [customLufs, setCustomLufs] = useState(-14);
  const [low, setLow] = useState(0);
  const [mid, setMid] = useState(0);
  const [high, setHigh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [last, setLast] = useState(null);

  const apply = async () => {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      const res = await masterArtifact(job.id, {
        source: "instrumental_final",
        targetPlatform: platform,
        customLufs,
        lowDb: low, midDb: mid, highDb: high,
      });
      setLast(res);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-4"
    >
      <div className="flex items-center gap-2">
        <Sliders className="size-4 text-violet" />
        <span className="text-sm font-semibold">{t("mastering2.title")}</span>
        <span className="ml-auto text-[10px] text-fg-muted/70">{t("mastering2.subtitle")}</span>
      </div>

      {err && (
        <div className="rounded-md px-2.5 py-1.5 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
          {err}
        </div>
      )}

      <div>
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-2">{t("mastering2.platform_label")}</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
          {PLATFORMS.map((p) => {
            const on = platform === p.id;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => setPlatform(p.id)}
                className={cn(
                  "text-left rounded-lg px-2.5 py-1.5 ring-1 transition-colors",
                  on
                    ? "ring-violet/40 bg-violet/15 text-violet"
                    : "ring-white/5 bg-white/3 text-fg-muted hover:text-fg",
                )}
              >
                <div className="text-[12px] font-semibold">{p.label}</div>
                <div className="mono text-[10px]">{p.sub}</div>
              </button>
            );
          })}
        </div>
        {platform === "custom" && (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[11px] text-fg-muted">{t("mastering2.target_lufs")}</span>
            <input
              type="number"
              min={-30}
              max={-6}
              step={0.5}
              value={customLufs}
              onChange={(e) => setCustomLufs(Number(e.target.value))}
              className="w-24 bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 mono text-[12px]"
            />
          </div>
        )}
      </div>

      <div className="space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">{t("mastering2.eq_title")}</div>
        <EqSlider label="Low (200 Hz shelf)"  value={low}  onChange={setLow}  accent="violet" />
        <EqSlider label="Mid (1 kHz bell)"    value={mid}  onChange={setMid}  accent="cyan" />
        <EqSlider label="High (5 kHz shelf)"  value={high} onChange={setHigh} accent="magenta" />
        <div className="text-[10px] text-fg-muted/70 leading-relaxed">
          {t("mastering2.eq_hint")}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={apply}
          disabled={busy}
          className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full text-xs font-medium bg-gradient-to-br from-violet to-magenta text-white disabled:opacity-40"
        >
          {busy ? (
            <>
              <Loader2 className="size-3.5 animate-spin" /> {t("mastering2.processing")}
            </>
          ) : (
            <>
              <Sliders className="size-3.5" /> {t("mastering2.apply")}
            </>
          )}
        </button>
        {last && (
          <span className="mono text-[11px] text-emerald-300 inline-flex items-center gap-1.5">
            <Check className="size-3.5" />
            완료 · 측정 {last.measured_lufs?.toFixed(1)} LUFS → 목표 {last.target_lufs?.toFixed(1)} LUFS
            ({last.gain_db?.toFixed(1)} dB)
          </span>
        )}
        {last && (
          <a
            href={artifactUrl(job.id, last.artifact)}
            download
            className="ml-auto inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
          >
            <Download className="size-3.5" /> {t("mastering2.download")}
          </a>
        )}
      </div>
    </motion.div>
  );
}

function EqSlider({ label, value, onChange, accent }) {
  const tint = {
    violet:  "accent-violet",
    cyan:    "accent-cyan",
    magenta: "accent-magenta",
  }[accent];
  return (
    <div>
      <div className="flex items-center justify-between mono text-[11px] mb-1">
        <span className="text-fg-muted">{label}</span>
        <span className={
          value > 0 ? "text-emerald-300" :
          value < 0 ? "text-rose-300" :
          "text-fg-muted/60"
        }>
          {value > 0 ? "+" : ""}{value.toFixed(1)} dB
        </span>
      </div>
      <input
        type="range"
        min={-12}
        max={12}
        step={0.5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`w-full ${tint}`}
      />
    </div>
  );
}
