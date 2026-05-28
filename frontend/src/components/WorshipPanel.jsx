import { useState } from "react";
import { motion } from "framer-motion";
import { Sparkles, Loader2, Download, Layers } from "lucide-react";
import { useTranslation } from "react-i18next";
import { createPedalTone, createSegue, artifactUrl } from "@/lib/api";
import { useJobHistory } from "@/lib/useJobHistory";
import { cn } from "@/lib/utils";

/**
 * Worship-mode panel — pedal-tone synthesis + cross-job segue.
 *
 * Pedal-tone: pick a key + mode + duration, get a sustained pad you can
 * use as an interlude between worship songs.
 *
 * Segue: pick the NEXT job (from the user's library) and optionally a
 * bridge key, the backend renders A → bridge → B as a single wav.
 */

const PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const DURATION_PRESETS = [4, 8, 16, 30, 60];

export function WorshipPanel({ job }) {
  const { t } = useTranslation();
  const detectedRoot = job.meta?.key_root || "C";
  const detectedMode = (job.meta?.key_mode || "major").startsWith("min") ? "minor" : "major";

  // Pedal-tone state.
  const [pdRoot, setPdRoot] = useState(detectedRoot);
  const [pdMode, setPdMode] = useState(detectedMode);
  const [pdDur, setPdDur] = useState(16);
  const [pdBusy, setPdBusy] = useState(false);
  const [pdLast, setPdLast] = useState(null);

  // Segue state.
  const { items } = useJobHistory();
  const otherJobs = items.filter((it) => it.id !== job.id);
  const [segueTarget, setSegueTarget] = useState("");
  const [bridgeKey, setBridgeKey] = useState("");   // "" = no pedal
  const [bridgeSec, setBridgeSec] = useState(8);
  const [xfadeSec, setXfadeSec] = useState(2);
  const [sgBusy, setSgBusy] = useState(false);
  const [sgLast, setSgLast] = useState(null);

  const [err, setErr] = useState(null);

  const runPedal = async () => {
    if (pdBusy) return;
    setPdBusy(true); setErr(null);
    try {
      const res = await createPedalTone(job.id, {
        keyRoot: pdRoot, mode: pdMode, durationSec: pdDur,
      });
      setPdLast(res);
    } catch (e) { setErr(e.message); }
    finally { setPdBusy(false); }
  };

  const runSegue = async () => {
    if (sgBusy || !segueTarget) return;
    setSgBusy(true); setErr(null);
    try {
      const res = await createSegue(job.id, {
        nextJobId: segueTarget,
        bridgeKey: bridgeKey || null,
        bridgeSeconds: bridgeSec,
        crossfadeSeconds: xfadeSec,
      });
      setSgLast(res);
    } catch (e) { setErr(e.message); }
    finally { setSgBusy(false); }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-4"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-amber-300" />
        <span className="text-sm font-semibold">{t("worship2.title")}</span>
        <span className="ml-auto text-[10px] text-fg-muted/70">{t("worship2.subtitle")}</span>
      </div>

      {err && (
        <div className="rounded-md px-2.5 py-1.5 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
          {err}
        </div>
      )}

      {/* Pedal tone */}
      <section className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-3 space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">{t("worship2.pedal_title")}</div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-fg-muted">Root</span>
          <select value={pdRoot} onChange={(e) => setPdRoot(e.target.value)}
                  className="bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 mono text-[12px]">
            {PITCH_CLASSES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <select value={pdMode} onChange={(e) => setPdMode(e.target.value)}
                  className="bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 mono text-[12px]">
            <option value="major">major</option>
            <option value="minor">minor</option>
          </select>
          <span className="text-[11px] text-fg-muted ml-2">{t("worship2.duration_label")}</span>
          {DURATION_PRESETS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setPdDur(d)}
              className={cn(
                "px-2 py-0.5 rounded text-[11px] mono ring-1",
                pdDur === d
                  ? "ring-amber-400/40 bg-amber-400/15 text-amber-200"
                  : "ring-white/5 bg-white/3 text-fg-muted hover:text-fg",
              )}
            >
              {d}s
            </button>
          ))}
          <button
            type="button"
            onClick={runPedal}
            disabled={pdBusy}
            className="ml-auto inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-amber-400/15 hover:bg-amber-400/25 text-amber-200 ring-1 ring-amber-400/30 disabled:opacity-40"
          >
            {pdBusy ? <Loader2 className="size-3 animate-spin" /> : <Sparkles className="size-3" />}
            {t("worship2.generate")}
          </button>
          {pdLast && (
            <a
              href={artifactUrl(job.id, pdLast.artifact)}
              download
              className="inline-flex items-center gap-1 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
            >
              <Download className="size-3" /> {pdLast.duration_sec}s
            </a>
          )}
        </div>
      </section>

      {/* Segue */}
      <section className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-3 space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">{t("worship2.segue_title")}</div>
        {otherJobs.length === 0 ? (
          <div className="text-[12px] text-fg-muted/80">
            {t("worship2.segue_help")}
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 flex-wrap">
              <Layers className="size-3 text-amber-300" />
              <span className="text-[11px] text-fg-muted">{t("worship2.next_song")}</span>
              <select
                value={segueTarget}
                onChange={(e) => setSegueTarget(e.target.value)}
                className="bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 text-[12px] text-fg min-w-[200px]"
              >
                <option value="">{t("worship2.pick_song")}</option>
                {otherJobs.map((it) => (
                  <option key={it.id} value={it.id}>{it.title || it.id}</option>
                ))}
              </select>
              <span className="text-[11px] text-fg-muted">{t("worship2.bridge_key")}</span>
              <select
                value={bridgeKey}
                onChange={(e) => setBridgeKey(e.target.value)}
                className="bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 mono text-[12px]"
              >
                <option value="">{t("worship2.bridge_none")}</option>
                {PITCH_CLASSES.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-3 mono text-[11px]">
              <span className="text-fg-muted">{t("worship2.bridge_seconds", { sec: bridgeSec })}</span>
              <input type="range" min={0} max={30} step={1}
                     value={bridgeSec} onChange={(e) => setBridgeSec(Number(e.target.value))}
                     className="flex-1 accent-amber-400" />
              <span className="text-fg-muted">{t("worship2.crossfade_seconds", { sec: xfadeSec })}</span>
              <input type="range" min={0.5} max={8} step={0.5}
                     value={xfadeSec} onChange={(e) => setXfadeSec(Number(e.target.value))}
                     className="flex-1 accent-amber-400" />
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={runSegue}
                disabled={sgBusy || !segueTarget}
                className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-amber-400/15 hover:bg-amber-400/25 text-amber-200 ring-1 ring-amber-400/30 disabled:opacity-40"
              >
                {sgBusy ? <Loader2 className="size-3 animate-spin" /> : <Layers className="size-3" />}
                {t("worship2.make_segue")}
              </button>
              {sgLast && (
                <a
                  href={artifactUrl(job.id, sgLast.artifact)}
                  download
                  className="ml-auto inline-flex items-center gap-1 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
                >
                  <Download className="size-3" /> {sgLast.duration_sec?.toFixed(0)}s
                </a>
              )}
            </div>
          </>
        )}
      </section>

      <div className="text-[10px] text-fg-muted/70 leading-relaxed">
        {t("worship2.hint")}
      </div>
    </motion.div>
  );
}
