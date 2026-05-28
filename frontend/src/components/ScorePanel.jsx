import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Music3,
  Download,
  FileText,
  FileMusic,
  ChevronLeft,
  ChevronRight,
  Printer,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { API_BASE, downloadArtifact } from "@/lib/api";
import { cn, trackFilename } from "@/lib/utils";
import { ScorePlayback } from "@/components/ScorePlayback";

/**
 * Layout for a multi-page score:
 *   - Stem tabs across the top.
 *   - Page navigator (← prev / page x of N / next →) with inline SVG preview.
 *   - Download row: MusicXML / MIDI / PDF / current page SVG.
 */
export function ScorePanel({ job }) {
  const { t } = useTranslation();
  const grouped = useMemo(() => {
    const out = {};
    for (const [key, path] of Object.entries(job.artifacts || {})) {
      // Match: score_<stem>_midi | _musicxml | _pdf | _svg | _svg_p<N>
      let m = key.match(/^score_(.+?)_svg_p(\d+)$/);
      if (m) {
        const [, stem, pageStr] = m;
        out[stem] = out[stem] || { svgs: [] };
        out[stem].svgs.push({ key, page: Number(pageStr), path });
        continue;
      }
      m = key.match(/^score_(.+?)_(midi|musicxml|svg|pdf)$/);
      if (m) {
        const [, stem, kind] = m;
        out[stem] = out[stem] || { svgs: [] };
        out[stem][kind] = { key, path };
      }
    }
    // Sort pages.
    for (const stem of Object.keys(out)) {
      (out[stem].svgs || []).sort((a, b) => a.page - b.page);
    }
    return out;
  }, [job.artifacts]);

  const stems = Object.keys(grouped);
  const [active, setActive] = useState(stems[0] || null);
  const [page, setPage] = useState(1);
  const [timemap, setTimemap] = useState(null);   // {bpm, measures:[{measure,start_sec,end_sec}]}
  const [currentMeasure, setCurrentMeasure] = useState(0);

  useEffect(() => {
    if (!active && stems.length) setActive(stems[0]);
  }, [active, stems]);
  useEffect(() => { setPage(1); setCurrentMeasure(0); }, [active]);

  // Load per-stem measure timemap. Falls back to linear page-mapping if
  // the timemap artifact isn't present (older jobs).
  useEffect(() => {
    setTimemap(null);
    if (!active) return;
    const key = `score_${active}_timemap`;
    if (!job.artifacts?.[key]) return;
    let cancelled = false;
    fetch(`${API_BASE}/jobs/${job.id}/download/${key}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancelled && d?.measures?.length) setTimemap(d); })
      .catch(() => { /* keep null → linear fallback */ });
    return () => { cancelled = true; };
  }, [active, job.id, job.artifacts]);

  const measureTimes = useMemo(
    () => (timemap?.measures || []).map((m) => m.start_sec),
    [timemap],
  );

  if (stems.length === 0) return null;
  const cur = grouped[active] || {};
  const svgs = cur.svgs || [];
  const pages = svgs.length;
  const pageObj = pages > 0
    ? (svgs.find((s) => s.page === page) || svgs[0])
    : (cur.svg || null);
  const stemMeta = job.meta || {};
  const measures = stemMeta[`score_${active}_measures`];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-6 space-y-4 glow-cyan"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Music3 className="size-4 text-cyan" />
        <span className="text-sm font-semibold">{t("score_panel2.title")}</span>
        <span className="ml-auto mono text-[11px] text-fg-muted">
          {pages > 0 ? t("score_panel2.pages_short", { n: pages }) : "single"}
          {measures != null && ` · ${t("score_panel2.measures_short", { n: measures })}`}
          {currentMeasure > 0 && measureTimes.length > 0 && (
            <span className="ml-2 text-cyan">{t("score_panel2.current_measure", { current: currentMeasure, total: measureTimes.length })}</span>
          )}
        </span>
        <button
          type="button"
          onClick={() => {
            // Inject per-job copyright into the print footer.
            const title = job.meta?.source_title || job.id;
            const year = new Date().getFullYear();
            const copyright = `© ${year} ${title} · 자동 전사 by Re:Chord`;
            document.documentElement.style.setProperty(
              "--print-copyright",
              `"${copyright.replace(/"/g, "'")}"`,
            );
            window.print();
          }}
          title={t("score_panel2.print_title")}
          className="inline-flex items-center gap-1 h-7 px-2.5 rounded-full text-[11px] bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg no-print"
        >
          <Printer className="size-3" /> {t("score_panel2.print")}
        </button>
      </div>

      {/* Stem tabs */}
      {stems.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {stems.map((s) => (
            <button
              key={s}
              onClick={() => setActive(s)}
              className={cn(
                "px-3 py-1 rounded-full text-xs transition-all",
                active === s
                  ? "bg-cyan/20 text-cyan ring-1 ring-cyan/40"
                  : "bg-white/5 text-fg-muted hover:text-fg",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Score-aware audio playback — sets the current page automatically. */}
      {pages > 0 && (
        <ScorePlayback
          job={job}
          pageCount={pages}
          measureTimes={measureTimes.length ? measureTimes : null}
          onPageChange={(idx) => setPage(idx + 1)}
          onMeasureChange={setCurrentMeasure}
        />
      )}

      {/* Page navigator */}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-2 mono text-[11px]">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-white/5 hover:bg-white/10 disabled:opacity-30 text-fg-muted hover:text-fg"
          >
            <ChevronLeft className="size-3.5" /> {t("score_panel2.prev")}
          </button>
          <span className="text-fg">
            page <span className="text-cyan">{page}</span>
            <span className="text-fg-muted"> / {pages}</span>
          </span>
          <button
            type="button"
            disabled={page >= pages}
            onClick={() => setPage((p) => Math.min(pages, p + 1))}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-white/5 hover:bg-white/10 disabled:opacity-30 text-fg-muted hover:text-fg"
          >
            {t("score_panel2.next")} <ChevronRight className="size-3.5" />
          </button>
        </div>
      )}

      {/* SVG preview — inline-injected so we can highlight the active measure. */}
      {pageObj && (
        <ScoreSvgInline
          jobId={job.id}
          artifactKey={pageObj.key}
          label={`${active} score page ${page}`}
          currentMeasure={currentMeasure}
        />
      )}

      {/* Downloads — explicit picker + one click */}
      <DownloadBar
        jobId={job.id}
        stem={active}
        pageObj={pageObj}
        pages={pages}
        cur={cur}
        job={job}
      />

      <div className="text-[11px] text-fg-muted/80 leading-relaxed">
        {t("score_panel2.explain")}
      </div>
    </motion.div>
  );
}

/**
 * Inline-injected Verovio SVG with active-measure highlight.
 *
 * Verovio emits `<g class="measure" data-n="N">` for every bar. We can't
 * reach into an `<object>`'s document, so we fetch the SVG text and use
 * dangerouslySetInnerHTML — the SVG comes from our own pipeline so this
 * is same-origin, sanitised at source.
 *
 * When ``currentMeasure`` changes, we toggle a CSS class instead of
 * re-rendering, so highlighting is cheap during playback.
 */
function ScoreSvgInline({ jobId, artifactKey, label, currentMeasure }) {
  const { t: tFn } = useTranslation();
  const containerRef = useRef(null);
  const [svgText, setSvgText] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setSvgText("");
    setLoading(true);
    let cancelled = false;
    fetch(`${API_BASE}/jobs/${jobId}/download/${artifactKey}`)
      .then((r) => (r.ok ? r.text() : ""))
      .then((t) => {
        if (cancelled) return;
        // Verovio sometimes prefixes XML declaration; strip for safe inlining.
        const cleaned = t.replace(/^<\?xml[^>]*\?>\s*/, "");
        setSvgText(cleaned);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [jobId, artifactKey]);

  // Highlight active measure. Try `data-n="N"` first (Verovio standard);
  // fall back to document order so pickup bars or renumbered scores still
  // light up the right measure.
  useEffect(() => {
    const root = containerRef.current;
    if (!root || !svgText) return;
    const measures = root.querySelectorAll("g.measure");
    measures.forEach((m) => m.classList.remove("rc-measure-active"));
    if (currentMeasure <= 0) return;
    let sel = root.querySelector(`g.measure[data-n="${currentMeasure}"]`);
    if (!sel && measures[currentMeasure - 1]) sel = measures[currentMeasure - 1];
    if (sel) {
      sel.classList.add("rc-measure-active");
      try {
        sel.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
      } catch { /* older browsers */ }
    }
  }, [svgText, currentMeasure]);

  return (
    <div className="relative rounded-xl bg-white p-3 max-h-[640px] overflow-auto rc-score-svg">
      {loading && !svgText && (
        <div className="text-xs text-slate-500 italic">{tFn("score_panel2.loading")}</div>
      )}
      <div
        ref={containerRef}
        aria-label={label}
        role="img"
        // SVG body comes from our own backend (Verovio); not user input.
        dangerouslySetInnerHTML={{ __html: svgText }}
      />
    </div>
  );
}

function DownloadBar({ jobId, stem, pageObj, pages, cur, job }) {
  const { t } = useTranslation();
  // Build the menu only with formats that actually exist for this job.
  const opts = [];
  if (cur.pdf) opts.push({
    id: "pdf",
    label: "PDF",
    sub: t("score_panel2.pdf_sub", { pages: pages || 1 }),
    icon: FileText,
    artifact: cur.pdf.key,
    ext: "pdf",
  });
  if (cur.musicxml) opts.push({
    id: "musicxml",
    label: "MusicXML",
    sub: t("score_panel2.musicxml_sub"),
    icon: FileText,
    artifact: cur.musicxml.key,
    ext: "musicxml",
  });
  if (cur.midi) opts.push({
    id: "midi",
    label: "MIDI",
    sub: t("score_panel2.midi_sub"),
    icon: FileMusic,
    artifact: cur.midi.key,
    ext: "mid",
  });
  if (pageObj) opts.push({
    id: "svg",
    label: "SVG (현재 페이지)",
    sub: t("score_panel2.svg_sub"),
    icon: Music3,
    artifact: pageObj.key,
    ext: "svg",
  });

  const [pick, setPick] = useState(opts[0]?.id || null);
  // Re-sync if the picked option disappears (e.g. stem switch).
  useEffect(() => {
    if (!opts.find((o) => o.id === pick)) {
      setPick(opts[0]?.id || null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stem, opts.map((o) => o.id).join(",")]);

  const chosen = opts.find((o) => o.id === pick) || opts[0];
  if (!chosen) return null;

  const handleDownload = () => {
    if (!chosen) return;
    const fname = trackFilename(
      job,
      chosen.id === "svg" ? `score_${stem}_p${pageObj?.page || 1}` : `score_${stem}`,
      chosen.ext,
    );
    downloadArtifact(jobId, chosen.artifact, fname);
  };

  return (
    <div className="rounded-2xl bg-white/[0.02] ring-1 ring-white/5 p-4 space-y-3">
      <div className="text-[10px] mono uppercase tracking-[0.22em] text-fg-muted">
        {t("score_panel2.title_block")}
      </div>

      {/* Format options */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
        {opts.map((o) => {
          const Icon = o.icon;
          const on = o.id === chosen.id;
          return (
            <button
              key={o.id}
              type="button"
              onClick={() => setPick(o.id)}
              aria-pressed={on}
              className={cn(
                "rounded-xl p-3 text-left ring-1 transition-all",
                on
                  ? "bg-gradient-to-br from-violet/20 to-cyan/15 ring-violet/45 text-fg"
                  : "bg-white/[0.02] ring-white/5 text-fg-muted hover:text-fg hover:bg-white/5",
              )}
            >
              <div className="flex items-center gap-2 mb-1">
                <Icon className={cn("size-4", on ? "text-violet" : "")} />
                <span className="text-sm font-semibold">{o.label}</span>
              </div>
              <div className="text-[11px] leading-snug">{o.sub}</div>
            </button>
          );
        })}
      </div>

      {/* Action row */}
      <div className="flex flex-wrap items-center gap-3 pt-1">
        <div className="text-[11px] text-fg-muted">
          {t("score_panel2.selected")} <span className="text-fg">{chosen.label}</span>
          <span className="text-fg-muted/70"> · stem: {stem}</span>
        </div>
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={handleDownload}
          className="ml-auto inline-flex items-center gap-1.5 rounded-full h-10 px-5 text-sm font-medium bg-gradient-to-br from-violet to-magenta text-white hover:shadow-[0_10px_36px_-12px_rgba(139,92,246,0.7)]"
        >
          <Download className="size-4" /> {t("score_panel2.download_format")}
        </motion.button>
      </div>
    </div>
  );
}
