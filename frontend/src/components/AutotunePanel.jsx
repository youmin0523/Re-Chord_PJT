import { useState } from "react";
import { motion } from "framer-motion";
import { Mic, Loader2, Check, Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { autotuneArtifact, artifactUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Gentle vocal pitch correction (auto-tune lite) — CREPE + WORLD.
 *
 * Defaults to detected key+scale from job.meta. The "correction strength"
 * slider is the most important control: 0.5 nudges, 1.0 snaps.
 */

const SCALES = [
  { id: "major", label: "Major" },
  { id: "minor", label: "Minor" },
  { id: "dorian", label: "Dorian" },
  { id: "mixo", label: "Mixolydian" },
  { id: "chromatic", labelKey: "autotune2.scale_chromatic" },
];

const PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export function AutotunePanel({ job }) {
  const { t } = useTranslation();
  const detectedRoot = job.meta?.key_root || "C";
  const detectedMode = (job.meta?.key_mode || "major").startsWith("min") ? "minor" : "major";

  const [root, setRoot] = useState(detectedRoot);
  const [scale, setScale] = useState(detectedMode);
  const [strength, setStrength] = useState(0.65);
  const [snap, setSnap] = useState(50);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [last, setLast] = useState(null);

  const apply = async () => {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      const res = await autotuneArtifact(job.id, {
        source: "vocals_final",
        keyRoot: root, scale,
        strength, snapCents: snap,
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
        <Mic className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("autotune2.title")}</span>
        <span className="ml-auto text-[10px] text-fg-muted/70">{t("autotune2.subtitle")}</span>
      </div>

      {err && (
        <div className="rounded-md px-2.5 py-1.5 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
          {err}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-1.5">Root</div>
          <div className="flex flex-wrap gap-1">
            {PITCH_CLASSES.map((pc) => (
              <button
                key={pc}
                type="button"
                onClick={() => setRoot(pc)}
                className={cn(
                  "size-7 rounded-md mono text-[10px] transition-colors",
                  root === pc
                    ? "bg-cyan/20 text-cyan ring-1 ring-cyan/40"
                    : "bg-white/5 text-fg-muted hover:text-fg",
                )}
              >
                {pc}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted mb-1.5">Scale</div>
          <div className="space-y-1">
            {SCALES.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setScale(s.id)}
                className={cn(
                  "block w-full text-left text-[11px] rounded px-2 py-1 ring-1 transition-colors",
                  scale === s.id
                    ? "ring-cyan/40 bg-cyan/15 text-cyan"
                    : "ring-white/5 bg-white/3 text-fg-muted hover:text-fg",
                )}
              >
                {s.labelKey ? t(s.labelKey) : s.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <Slider label={t("autotune2.strength_label")} value={strength} min={0} max={1} step={0.05}
                onChange={setStrength} format={(v) => `${Math.round(v * 100)}%`}
                hint={t("autotune2.strength_hint")}
                accent="cyan" />
        <Slider label={t("autotune2.window_label")} value={snap} min={10} max={100} step={5}
                onChange={setSnap} format={(v) => `±${v}¢`}
                hint={t("autotune2.window_hint")}
                accent="cyan" />
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={apply}
          disabled={busy}
          className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full text-xs font-medium bg-gradient-to-br from-cyan to-violet text-white disabled:opacity-40"
        >
          {busy ? (
            <>
              <Loader2 className="size-3.5 animate-spin" /> {t("autotune2.applying")}
            </>
          ) : (
            <>
              <Mic className="size-3.5" /> {t("autotune2.apply")}
            </>
          )}
        </button>
        {last && (
          <span className="mono text-[11px] text-emerald-300 inline-flex items-center gap-1.5">
            <Check className="size-3.5" /> {last.frames_corrected}{t("autotune2.frame_correct")} · {last.elapsed_sec?.toFixed(1)}초
          </span>
        )}
        {last && (
          <a
            href={artifactUrl(job.id, last.artifact)}
            download
            className="ml-auto inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
          >
            <Download className="size-3.5" /> {t("autotune2.download")}
          </a>
        )}
      </div>

      <div className="text-[10px] text-fg-muted/70 leading-relaxed">
        {t("autotune2.hint")}
      </div>
    </motion.div>
  );
}

function Slider({ label, value, min, max, step, onChange, format, hint, accent }) {
  const tint = { violet: "accent-violet", cyan: "accent-cyan", magenta: "accent-magenta" }[accent];
  return (
    <div>
      <div className="flex items-center justify-between mono text-[11px] mb-1">
        <span className="text-fg-muted">{label}</span>
        <span className="text-cyan">{format(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`w-full ${tint}`}
      />
      {hint && <div className="text-[10px] text-fg-muted/60 mt-0.5">{hint}</div>}
    </div>
  );
}
