import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Mic2,
  Drum,
  Music,
  Guitar,
  Piano,
  Wand2,
  Download,
  Loader2,
  Layers3,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { createMixdown, downloadArtifact } from "@/lib/api";
import { cn, trackFilename } from "@/lib/utils";

// Per-stem display info. Keys must match backend stem names.
const STEM_DEF = [
  { id: "vocals", label: "Vocals",  Icon: Mic2,   color: "magenta" },
  { id: "drums",  label: "Drums",   Icon: Drum,   color: "amber"   },
  { id: "bass",   label: "Bass",    Icon: Music,  color: "violet"  },
  { id: "guitar", label: "Guitar",  Icon: Guitar, color: "cyan"    },
  { id: "piano",  label: "Piano",   Icon: Piano,  color: "violet"  },
  { id: "other",  label: "Other",   Icon: Wand2,  color: "magenta" },
];

const COLOR_RING = {
  violet:  "ring-violet/50  bg-violet/15  text-violet",
  cyan:    "ring-cyan/50    bg-cyan/15    text-cyan",
  amber:   "ring-amber/50   bg-amber/15   text-amber",
  magenta: "ring-magenta/50 bg-magenta/15 text-magenta",
};

// "Excluded" presets — which stems to leave OUT.
const PRESETS = [
  { id: "drum_play",   labelKey: "stems_mix2.preset_drum_label",   exclude: ["drums"],
    descKey: "stems_mix2.preset_drum_desc" },
  { id: "bass_play",   labelKey: "stems_mix2.preset_bass_label",   exclude: ["bass"],
    descKey: "stems_mix2.preset_bass_desc" },
  { id: "guitar_play", labelKey: "stems_mix2.preset_guitar_label", exclude: ["guitar"],
    descKey: "stems_mix2.preset_guitar_desc" },
  { id: "piano_play",  labelKey: "stems_mix2.preset_piano_label",  exclude: ["piano"],
    descKey: "stems_mix2.preset_piano_desc" },
  { id: "vocal_play",  labelKey: "stems_mix2.preset_vocal_label",  exclude: ["vocals"],
    descKey: "stems_mix2.preset_vocal_desc" },
  { id: "melody_only", labelKey: "stems_mix2.preset_melody_label", exclude: ["drums", "bass", "other"],
    descKey: "stems_mix2.preset_melody_desc" },
];

export function StemsMixer({ job }) {
  const { t } = useTranslation();
  const availableStems = useMemo(() => {
    const fromMeta = job?.meta?.available_stems;
    if (Array.isArray(fromMeta) && fromMeta.length) return fromMeta;
    return Object.keys(job?.artifacts || {})
      .filter((k) => k.startsWith("stem_"))
      .map((k) => k.replace(/^stem_/, ""));
  }, [job]);

  // Default: all stems on.
  const [included, setIncluded] = useState(() => new Set(availableStems));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]); // recent mixdowns

  if (!availableStems.length) return null;

  const toggle = (id) => {
    setIncluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const applyPreset = (excludeIds) => {
    setIncluded(new Set(availableStems.filter((s) => !excludeIds.includes(s))));
  };

  const allOn = () => setIncluded(new Set(availableStems));

  const build = async () => {
    if (busy || included.size === 0) return;
    setError(null);
    setBusy(true);
    try {
      const sel = availableStems.filter((s) => included.has(s));
      const res = await createMixdown(job.id, sel);
      setHistory((prev) => [{ ...res, at: Date.now() }, ...prev].slice(0, 6));
      const tag = sel.join("+");
      const filename = trackFilename(job, `mix_${tag}`, "wav");
      await downloadArtifact(job.id, res.artifact, filename);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const sel = availableStems.filter((s) => included.has(s));
  const excluded = availableStems.filter((s) => !included.has(s));

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-6 space-y-5 glow-amber"
    >
      <div className="flex items-center gap-2">
        <Layers3 className="size-4 text-amber" />
        <span className="text-sm font-semibold">Stems Mixer</span>
        <span className="ml-auto mono text-[11px] text-fg-muted">
          {t("stems_mix2.count_included", { sel: sel.length, total: availableStems.length })}
        </span>
      </div>

      {/* Stem toggles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
        {STEM_DEF.filter((s) => availableStems.includes(s.id)).map((s) => {
          const on = included.has(s.id);
          return (
            <motion.button
              key={s.id}
              type="button"
              onClick={() => toggle(s.id)}
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.97 }}
              className={cn(
                "rounded-xl px-3 py-3 text-left flex items-center gap-3 ring-1 transition-all",
                on
                  ? COLOR_RING[s.color]
                  : "bg-white/3 text-fg-muted/60 ring-white/5 hover:text-fg-muted",
              )}
              aria-pressed={on}
            >
              <s.Icon className="size-4 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{s.label}</div>
                <div className="text-[10px] mono opacity-70">
                  {on ? t("stems_mix2.on") : t("stems_mix2.off")}
                </div>
              </div>
            </motion.button>
          );
        })}
      </div>

      {/* Presets */}
      <div className="space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
          {t("stems_mix2.quick_presets")}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={allOn}
            className="px-3 py-1.5 rounded-full text-xs bg-white/5 text-fg-muted hover:text-fg hover:bg-white/10 transition-all"
          >
            {t("stems_mix2.all_in")}
          </button>
          {PRESETS.filter((p) =>
            p.exclude.every((id) => availableStems.includes(id)),
          ).map((p) => (
            <button
              key={p.id}
              onClick={() => applyPreset(p.exclude)}
              title={p.descKey ? t(p.descKey) : p.desc}
              className="px-3 py-1.5 rounded-full text-xs bg-white/5 text-fg-muted hover:text-fg hover:bg-white/10 transition-all"
            >
              {p.labelKey ? t(p.labelKey) : p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary + build button */}
      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="text-[11px] text-fg-muted">
          {sel.length > 0 ? (
            <>
              {t("stems_mix2.included")} <span className="text-fg">{sel.join(" + ")}</span>
              {excluded.length > 0 && (
                <span className="text-fg-muted/70">
                  {"  ·  "}{t("stems_mix2.excluded")} {excluded.join(", ")}
                </span>
              )}
            </>
          ) : (
            <span className="text-amber/80">{t("stems_mix2.pick_at_least_one")}</span>
          )}
        </div>
        <motion.button
          whileHover={!busy ? { scale: 1.03 } : undefined}
          whileTap={!busy ? { scale: 0.97 } : undefined}
          onClick={build}
          disabled={busy || sel.length === 0}
          className="inline-flex items-center gap-2 rounded-full h-10 px-5 text-sm font-medium bg-gradient-to-br from-amber via-magenta to-violet text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? (
            <>
              <Loader2 className="size-4 animate-spin" /> {t("stems_mix2.making")}
            </>
          ) : (
            <>
              <Download className="size-4" /> {t("stems_mix2.make_combo")}
            </>
          )}
        </motion.button>
      </div>

      {error && (
        <div className="rounded-lg p-2.5 text-xs bg-rose-500/10 text-rose-200 border border-rose-500/20">
          {error}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="space-y-1.5 pt-2 border-t border-white/5">
          <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
            {t("stems_mix2.recent_combos")}
          </div>
          {history.map((h) => (
            <div
              key={`${h.artifact}-${h.at}`}
              className="text-[11px] mono text-fg-muted flex items-center justify-between gap-2"
            >
              <span className="truncate">
                {h.included_stems.join(" + ")}
              </span>
              <button
                onClick={() =>
                  downloadArtifact(
                    job.id,
                    h.artifact,
                    trackFilename(job, `mix_${h.included_stems.join("+")}`, "wav"),
                  )
                }
                className="px-2 py-1 rounded-md hover:bg-white/5 text-fg-muted hover:text-fg"
              >
                {t("stems_mix2.redownload")}
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="text-[11px] text-fg-muted/70">
        {t("stems_mix2.hint")}
      </div>
    </motion.div>
  );
}
