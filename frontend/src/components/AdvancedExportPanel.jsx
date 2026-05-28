import { useState } from "react";
import { motion } from "framer-motion";
import { Speaker, Disc, Download, Loader2, Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { createSurround, createDsd, artifactUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Advanced export formats — 5.1 surround + DSD.
 *
 * 5.1 surround composes the job's stems into a 6-channel WAV. Stems
 * mode produces the cleanest spatialisation (drums front, bass front+LFE,
 * vocals dead center, guitar wide left, piano wide right, etc.).
 *
 * DSD wraps a chosen PCM artifact into .dsf — meaningful for audiophile
 * playback chains (Audirvana / JRiver). Lossy conversion of the
 * dynamic-range information when the source is float32, but format-correct.
 */

const DSD_RATES = [
  { id: "dsd64",  label: "DSD64 (2.8 MHz)", note: "SACD" },
  { id: "dsd128", label: "DSD128 (5.6 MHz)", noteKey: "advexp2.label_hires" },
  { id: "dsd256", label: "DSD256 (11.3 MHz)", noteKey: "advexp2.label_uhires" },
];

const DSD_SOURCES = [
  { id: "instrumental_final", label: "Instrumental (MR)" },
  { id: "vocals_final",       label: "Vocals" },
];

export function AdvancedExportPanel({ job }) {
  const { t } = useTranslation();
  const [surBusy, setSurBusy] = useState(false);
  const [surRes, setSurRes] = useState(null);
  const [surErr, setSurErr] = useState(null);

  const [dsdSrc, setDsdSrc] = useState("instrumental_final");
  const [dsdRate, setDsdRate] = useState("dsd64");
  const [dsdBusy, setDsdBusy] = useState(false);
  const [dsdRes, setDsdRes] = useState(null);
  const [dsdErr, setDsdErr] = useState(null);

  const renderSurround = async () => {
    if (surBusy) return;
    setSurBusy(true); setSurErr(null);
    try {
      setSurRes(await createSurround(job.id, { sampleRate: 48000 }));
    } catch (e) {
      setSurErr(e.message);
    } finally {
      setSurBusy(false);
    }
  };

  const renderDsd = async () => {
    if (dsdBusy) return;
    setDsdBusy(true); setDsdErr(null);
    try {
      setDsdRes(await createDsd(job.id, { source: dsdSrc, rate: dsdRate }));
    } catch (e) {
      setDsdErr(e.message);
    } finally {
      setDsdBusy(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 space-y-4"
    >
      <div className="flex items-center gap-2">
        <Speaker className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("advexp2.title")}</span>
      </div>

      {/* 5.1 Surround */}
      <section className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-3 space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
          {t("advexp2.surround_title")}
        </div>
        {surErr && (
          <div className="rounded-md px-2 py-1 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
            {surErr}
          </div>
        )}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={renderSurround}
            disabled={surBusy}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-cyan/15 hover:bg-cyan/25 text-cyan ring-1 ring-cyan/30 disabled:opacity-40"
          >
            {surBusy ? <Loader2 className="size-3 animate-spin" /> : <Speaker className="size-3" />}
            {t("advexp2.surround_render")}
          </button>
          {surRes && (
            <span className="mono text-[11px] text-emerald-300 inline-flex items-center gap-1.5">
              <Check className="size-3.5" /> {surRes.channel_layout} · {(surRes.sample_rate / 1000).toFixed(1)} kHz
            </span>
          )}
          {surRes && (
            <a
              href={artifactUrl(job.id, surRes.artifact)}
              download
              className="ml-auto inline-flex items-center gap-1 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
            >
              <Download className="size-3" /> {t("advexp2.download")}
            </a>
          )}
        </div>
        <div className="text-[10px] text-fg-muted/70 leading-relaxed">
          {t("advexp2.surround_hint")}
        </div>
      </section>

      {/* DSD */}
      <section className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-3 space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
          {t("advexp2.dsd_title")}
        </div>
        {dsdErr && (
          <div className="rounded-md px-2 py-1 text-[11px] text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/20">
            {dsdErr}
          </div>
        )}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-fg-muted">{t("advexp2.source")}</span>
          <select
            value={dsdSrc}
            onChange={(e) => setDsdSrc(e.target.value)}
            className="bg-black/30 ring-1 ring-white/10 rounded px-2 py-1 text-[12px] text-fg"
          >
            {DSD_SOURCES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <span className="text-[11px] text-fg-muted ml-2">{t("advexp2.rate")}</span>
          {DSD_RATES.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setDsdRate(r.id)}
              className={cn(
                "px-2 py-0.5 rounded text-[11px] mono ring-1",
                dsdRate === r.id
                  ? "ring-cyan/40 bg-cyan/15 text-cyan"
                  : "ring-white/5 bg-white/3 text-fg-muted hover:text-fg",
              )}
              title={r.noteKey ? t(r.noteKey) : r.note}
            >
              {r.label}
            </button>
          ))}
          <button
            type="button"
            onClick={renderDsd}
            disabled={dsdBusy}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-cyan/15 hover:bg-cyan/25 text-cyan ring-1 ring-cyan/30 disabled:opacity-40"
          >
            {dsdBusy ? <Loader2 className="size-3 animate-spin" /> : <Disc className="size-3" />}
            {t("advexp2.dsd_encode")}
          </button>
          {dsdRes && (
            <a
              href={artifactUrl(job.id, dsdRes.artifact)}
              download
              className="inline-flex items-center gap-1 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
            >
              <Download className="size-3" /> .dsf
            </a>
          )}
        </div>
        <div className="text-[10px] text-fg-muted/70 leading-relaxed">
          {t("advexp2.dsd_hint")}
        </div>
      </section>
    </motion.div>
  );
}
