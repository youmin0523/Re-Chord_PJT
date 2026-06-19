import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import {
  Play,
  Pause,
  Repeat,
  Repeat1,
  Scissors,
  Download,
  Magnet,
  Turtle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  artifactUrl,
  artifactUnavailableReason,
  createLoop,
  createSlowdown,
  downloadArtifact,
  getSections,
} from "@/lib/api";
import { toast } from "@/lib/toast";
import { cn, formatDuration, trackFilename } from "@/lib/utils";
import { SectionsTimeline } from "@/components/SectionsTimeline";
import { ChordsPanel } from "@/components/ChordsPanel";

// Which artifacts to expose in the source picker.
const SOURCE_CANDIDATES = [
  { key: "instrumental_final", label: "Instrumental (MR)" },
  { key: "vocals_final",       label: "Vocals" },
  { key: "monitor_track",      labelKey: "wave2.monitor_label" },
];

export function WaveformPanel({ job }) {
  const { t } = useTranslation();
  // Pick available sources for this job.
  const sources = useMemo(
    () => SOURCE_CANDIDATES.filter((s) => !!job.artifacts?.[s.key]),
    [job.artifacts],
  );
  const [sourceKey, setSourceKey] = useState(sources[0]?.key || null);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [loopEnabled, setLoopEnabled] = useState(true);
  const [snap, setSnap] = useState(true);
  const [ab, setAB] = useState(null);              // {start, end}
  const [downbeats, setDownbeats] = useState([]);
  const [bpm, setBpm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [repeats, setRepeats] = useState(8);
  const [withCountin, setWithCountin] = useState(true);
  const [history, setHistory] = useState([]);

  // Slowdown (pitch-preserving). null = original speed.
  const [slowdownRatio, setSlowdownRatio] = useState(1.0);
  const [slowdownBusy, setSlowdownBusy] = useState(false);
  const [slowdownArtifact, setSlowdownArtifact] = useState(null);

  const containerRef = useRef(null);
  const wsRef = useRef(null);
  const regionsRef = useRef(null);
  const regionRef = useRef(null);

  // Fetch section/beat grid for snapping.
  useEffect(() => {
    getSections(job.id)
      .then((r) => {
        if (r?.available) {
          setDownbeats(r.downbeats_sec || []);
          if (r.bpm) setBpm(r.bpm);
        }
      })
      .catch(() => {});
  }, [job.id]);

  // When the user picks a different source, drop any previous slowdown.
  useEffect(() => { setSlowdownArtifact(null); setSlowdownRatio(1.0); }, [sourceKey]);

  // Initialize WaveSurfer when source (or slowdown artifact) changes.
  useEffect(() => {
    if (!sourceKey || !containerRef.current) return;
    const activeArtifact = slowdownArtifact || sourceKey;
    const ws = WaveSurfer.create({
      container: containerRef.current,
      height: 96,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
      waveColor: "rgba(139, 92, 246, 0.55)",
      progressColor: "rgba(6, 182, 212, 0.85)",
      cursorColor: "rgba(236, 72, 153, 0.85)",
      cursorWidth: 2,
      url: artifactUrl(job.id, activeArtifact),
    });
    const regions = ws.registerPlugin(RegionsPlugin.create());
    wsRef.current = ws;
    regionsRef.current = regions;

    ws.on("ready", (d) => setDuration(d));
    // Media failed to load — most often the artifact passed its 30-day
    // retention window. Probe the reason and surface it as a toast instead
    // of a silently dead player.
    ws.on("error", async () => {
      const reason = await artifactUnavailableReason(job.id, activeArtifact);
      if (reason) toast.error(reason);
    });
    ws.on("audioprocess", (t) => setCurrentTime(t));
    ws.on("seeking", (t) => setCurrentTime(t));
    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("finish", () => setPlaying(false));

    // Loop hook: when playback passes region end, jump back to region start.
    const onTime = (t) => {
      const r = regionRef.current;
      if (!loopEnabled || !r) return;
      if (t >= r.end - 0.01) ws.setTime(r.start);
    };
    const unsub = ws.on("audioprocess", onTime);

    return () => {
      try { unsub && unsub(); } catch {}
      try { ws.destroy(); } catch {}
      wsRef.current = null;
      regionsRef.current = null;
      regionRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, sourceKey, slowdownArtifact]);

  // Re-apply loop watcher when toggle flips.
  useEffect(() => {
    const ws = wsRef.current;
    if (!ws) return;
    const handler = (t) => {
      const r = regionRef.current;
      if (!loopEnabled || !r) return;
      if (t >= r.end - 0.01) ws.setTime(r.start);
    };
    const unsub = ws.on("audioprocess", handler);
    return () => { try { unsub && unsub(); } catch {} };
  }, [loopEnabled]);

  const snapToBeat = (t) => {
    if (!snap || downbeats.length === 0) return t;
    let best = downbeats[0];
    let bestDist = Math.abs(t - best);
    for (const db of downbeats) {
      const d = Math.abs(t - db);
      if (d < bestDist) { best = db; bestDist = d; }
    }
    return best;
  };

  const placeMarkers = () => {
    const ws = wsRef.current;
    const regions = regionsRef.current;
    if (!ws || !regions || !duration) return;
    const center = currentTime || duration * 0.25;
    const length = Math.min(8, duration - center);
    let start = snapToBeat(center);
    let end = snapToBeat(center + length);
    if (end <= start) end = Math.min(duration, start + 4);

    // Clear previous regions.
    regions.getRegions().forEach((r) => r.remove());
    const region = regions.addRegion({
      start, end,
      color: "rgba(139, 92, 246, 0.18)",
      drag: true,
      resize: true,
    });
    regionRef.current = region;
    setAB({ start: region.start, end: region.end });

    region.on("update-end", () => {
      let s = region.start;
      let e = region.end;
      if (snap) {
        s = snapToBeat(s);
        e = snapToBeat(e);
        if (e <= s) e = Math.min(duration, s + 1);
        region.setOptions({ start: s, end: e });
      }
      setAB({ start: s, end: e });
    });
  };

  const togglePlay = () => {
    const ws = wsRef.current;
    if (!ws) return;
    ws.isPlaying() ? ws.pause() : ws.play();
  };

  const buildLoop = async () => {
    if (!ab || busy) return;
    setBusy(true);
    try {
      const res = await createLoop(job.id, {
        source: sourceKey,
        startSec: ab.start,
        endSec: ab.end,
        repeats,
        withCountin,
      });
      setHistory((prev) => [{ ...res, ab, at: Date.now() }, ...prev].slice(0, 6));
      const tag = `loop_${ab.start.toFixed(1)}-${ab.end.toFixed(1)}_x${repeats}`;
      const name = trackFilename(job, tag, "wav");
      await downloadArtifact(job.id, res.artifact, name);
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  };

  if (sources.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-6 space-y-4 glow-magenta"
    >
      <div className="flex items-center gap-2">
        <Repeat className="size-4 text-magenta" />
        <span className="text-sm font-semibold">{t("wave2.title")}</span>
        {bpm && (
          <span className="ml-auto mono text-[11px] text-fg-muted">
            BPM <span className="text-cyan">{bpm.toFixed(1)}</span>
          </span>
        )}
      </div>

      {/* Source picker */}
      {sources.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {sources.map((s) => (
            <button
              key={s.key}
              onClick={() => setSourceKey(s.key)}
              className={cn(
                "px-3 py-1 rounded-full text-xs transition-all",
                sourceKey === s.key
                  ? "bg-magenta/20 text-magenta ring-1 ring-magenta/40"
                  : "bg-white/5 text-fg-muted hover:text-fg",
              )}
            >
              {s.labelKey ? t(s.labelKey) : s.label}
            </button>
          ))}
        </div>
      )}

      {/* Waveform */}
      <div
        ref={containerRef}
        className="rounded-xl bg-black/30 border border-white/5 px-2 pt-3 pb-2"
      />

      {/* Sections timeline (only if D9 ran) */}
      <SectionsTimeline
        job={job}
        onSeek={(sec) => {
          const ws = wsRef.current;
          if (ws && duration > 0) {
            ws.setTime(Math.max(0, Math.min(duration - 0.05, sec)));
            if (!ws.isPlaying()) ws.play();
          }
        }}
      />

      {/* Chord progression (karaoke/pro) */}
      <ChordsPanel
        job={job}
        onSeek={(sec) => {
          const ws = wsRef.current;
          if (ws && duration > 0) {
            ws.setTime(Math.max(0, Math.min(duration - 0.05, sec)));
            if (!ws.isPlaying()) ws.play();
          }
        }}
      />

      {/* Transport */}
      <div className="flex items-center gap-3">
        <button
          onClick={togglePlay}
          className="inline-flex items-center justify-center size-10 rounded-full bg-gradient-to-br from-violet to-magenta text-white hover:shadow-[0_0_24px_-4px_rgba(139,92,246,0.7)]"
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4 translate-x-px" />}
        </button>
        <div className="mono text-xs text-fg-muted">
          {formatDuration(currentTime)} / {formatDuration(duration)}
        </div>

        <button
          onClick={() => setLoopEnabled((v) => !v)}
          title={t("wave2.loop_title")}
          className={cn(
            "ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs transition-all",
            loopEnabled
              ? "bg-cyan/15 text-cyan ring-1 ring-cyan/40"
              : "bg-white/5 text-fg-muted hover:text-fg",
          )}
        >
          {loopEnabled ? <Repeat1 className="size-3.5" /> : <Repeat className="size-3.5" />}
          {t("wave2.loop")}
        </button>
        <button
          onClick={() => setSnap((v) => !v)}
          title={t("wave2.snap_title")}
          className={cn(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs transition-all",
            snap
              ? "bg-violet/15 text-violet ring-1 ring-violet/40"
              : "bg-white/5 text-fg-muted hover:text-fg",
          )}
        >
          <Magnet className="size-3.5" /> {t("wave2.snap")}
        </button>
      </div>

      {/* Slowdown (pitch-preserving) */}
      <div className="rounded-xl bg-white/3 ring-1 ring-white/5 p-3 flex flex-wrap items-center gap-2">
        <div className="inline-flex items-center gap-1.5 text-xs text-fg">
          <Turtle className="size-4 text-cyan" /> {t("wave2.slow_listen")}
        </div>
        {[
          { r: 1.0, label: t("wave2.original") },
          { r: 0.75, label: "0.75×" },
          { r: 0.5, label: "0.5×" },
        ].map((p) => {
          const isOn = Math.abs(slowdownRatio - p.r) < 0.001;
          return (
            <button
              key={p.r}
              type="button"
              onClick={() => setSlowdownRatio(p.r)}
              className={cn(
                "px-3 py-1 rounded-full text-xs transition-all",
                isOn
                  ? "bg-cyan/20 text-cyan ring-1 ring-cyan/40"
                  : "bg-white/5 text-fg-muted hover:text-fg",
              )}
            >
              {p.label}
            </button>
          );
        })}
        <button
          type="button"
          disabled={slowdownBusy || Math.abs(slowdownRatio - 1.0) < 0.001}
          onClick={async () => {
            if (slowdownBusy) return;
            setSlowdownBusy(true);
            try {
              const res = await createSlowdown(job.id, {
                source: sourceKey,
                tempoRatio: slowdownRatio,
                stemKind:
                  sourceKey === "vocals_final" ? "vocals" :
                  sourceKey === "monitor_track" ? "mix" : "instrumental",
              });
              setSlowdownArtifact(res.artifact);
            } catch (e) {
              console.error(e);
            } finally {
              setSlowdownBusy(false);
            }
          }}
          className="ml-auto inline-flex items-center gap-1.5 rounded-full h-8 px-3 text-xs font-medium bg-gradient-to-br from-cyan to-violet text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {slowdownBusy ? t("wave2.rendering")
            : slowdownArtifact ? t("wave2.redo")
            : t("wave2.play_at_this_speed")}
        </button>
        {slowdownArtifact && (
          <button
            type="button"
            onClick={() => { setSlowdownArtifact(null); setSlowdownRatio(1.0); }}
            className="text-[11px] text-fg-muted hover:text-fg"
          >
            {t("wave2.back_to_original")}
          </button>
        )}
      </div>

      {/* A-B controls */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          onClick={placeMarkers}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg transition-all"
        >
          <Scissors className="size-3.5" /> {t("wave2.ab_create")}
        </button>
        {ab && (
          <span className="mono text-[11px] text-fg-muted">
            <span className="text-violet">{formatDuration(ab.start)}</span>
            {" → "}
            <span className="text-cyan">{formatDuration(ab.end)}</span>
            {"  ("}
            {(ab.end - ab.start).toFixed(2)}s
            {")"}
          </span>
        )}
      </div>

      {/* Loop downloader */}
      {ab && (
        <div className="rounded-xl bg-white/3 ring-1 ring-white/5 p-3 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
            {t("wave2.repeat_label")}
            <input
              type="number"
              min="1"
              max="64"
              value={repeats}
              onChange={(e) => setRepeats(Math.max(1, Math.min(64, Number(e.target.value))))}
              className="mono w-14 bg-black/30 border border-white/10 rounded px-1.5 py-0.5 text-center text-fg"
            />
            {t("wave2.repeat_times")}
          </div>
          <label className="flex items-center gap-1.5 text-[11px] text-fg-muted cursor-pointer">
            <input
              type="checkbox"
              checked={withCountin}
              onChange={(e) => setWithCountin(e.target.checked)}
              className="appearance-none size-4 rounded border border-white/15 bg-white/5 checked:bg-gradient-to-br checked:from-amber checked:to-magenta"
            />
            {t("wave2.count_in_label")}
          </label>
          <button
            onClick={buildLoop}
            disabled={busy}
            className="ml-auto inline-flex items-center gap-1.5 rounded-full h-9 px-4 text-xs font-medium bg-gradient-to-br from-magenta via-violet to-cyan text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy ? (
              t("wave2.making")
            ) : (
              <>
                <Download className="size-3.5" /> {t("wave2.download_loop")}
              </>
            )}
          </button>
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="pt-2 border-t border-white/5 space-y-1.5">
          <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
            {t("wave2.recent_loops")}
          </div>
          {history.map((h) => (
            <div
              key={`${h.artifact}-${h.at}`}
              className="text-[11px] mono text-fg-muted flex items-center justify-between gap-2"
            >
              <span className="truncate">
                {formatDuration(h.ab.start)}–{formatDuration(h.ab.end)} × {h.repeats}
              </span>
              <button
                onClick={() => {
                  const tag = `loop_${h.ab.start.toFixed(1)}-${h.ab.end.toFixed(1)}_x${h.repeats}`;
                  downloadArtifact(job.id, h.artifact, trackFilename(job, tag, "wav"));
                }}
                className="px-2 py-1 rounded-md hover:bg-white/5 text-fg-muted hover:text-fg"
              >
                {t("wave2.redownload")}
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="text-[11px] text-fg-muted/80">
        {t("wave2.hint")}
      </div>
    </motion.div>
  );
}
