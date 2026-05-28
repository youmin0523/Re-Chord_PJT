import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { getJob, getChords, getLyrics } from "@/lib/api";

// Extract jobId from URL — both /job/:id and /jobs/:id are common, plus a
// fallback regex for query-style links.
function detectJobId(pathname, search, routeParams) {
  if (routeParams?.id) return routeParams.id;
  const m = pathname.match(/^\/jobs?\/([^/?#]+)/);
  if (m) return m[1];
  const params = new URLSearchParams(search || "");
  return params.get("job") || params.get("job_id") || null;
}

function summarizeChords(chords, maxBars = 4) {
  if (!chords) return null;
  const arr = Array.isArray(chords)
    ? chords
    : Array.isArray(chords?.chords)
      ? chords.chords
      : Array.isArray(chords?.items)
        ? chords.items
        : null;
  if (!arr || !arr.length) return null;
  const labels = arr
    .slice(0, maxBars)
    .map((c) => c?.label || c?.chord || c?.name)
    .filter(Boolean);
  if (!labels.length) return null;
  return labels.join(" - ");
}

function summarizeSections(job) {
  const meta = job?.meta || {};
  const sections = meta.sections;
  if (Array.isArray(sections) && sections.length) {
    return sections
      .map((s) => s?.label || s?.name)
      .filter(Boolean)
      .slice(0, 12)
      .join(" → ");
  }
  if (typeof meta.section_summary === "string") return meta.section_summary;
  return null;
}

function summarizeLyrics(lyrics) {
  if (!lyrics) return null;
  const words = Array.isArray(lyrics?.words)
    ? lyrics.words
    : Array.isArray(lyrics?.lyrics)
      ? lyrics.lyrics
      : null;
  if (!words || !words.length) return null;
  const text = words
    .slice(0, 40)
    .map((w) => w?.word || w?.text || "")
    .join(" ")
    .trim();
  if (!text) return null;
  return text.length > 200 ? text.slice(0, 200) + "…" : text;
}

/** Reads the current Job's analysis from the backend and shapes it into a
 *  {@code JobContextSnapshot} that the chat backend understands.
 *  Returns {@code null} when we're not on a job page (or the job hasn't
 *  finished analysis yet).
 */
export function useJobContextSnapshot() {
  const { pathname, search } = useLocation();
  const routeParams = useParams();
  const jobId = detectJobId(pathname, search, routeParams);
  const [snapshot, setSnapshot] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!jobId) {
      setSnapshot(null);
      return undefined;
    }
    (async () => {
      try {
        const job = await getJob(jobId).catch(() => null);
        if (!job) {
          if (!cancelled) setSnapshot(null);
          return;
        }
        // Chords / lyrics may not be ready yet — best-effort, never block.
        const [chords, lyrics] = await Promise.all([
          getChords(jobId).catch(() => null),
          getLyrics(jobId).catch(() => null),
        ]);
        if (cancelled) return;
        const meta = job.meta || {};
        const snap = {
          job_id: jobId,
          title: meta.source_title || meta.title || null,
          key_name: meta.key_name || null,
          bpm: typeof meta.bpm === "number" ? meta.bpm : null,
          chord_summary: summarizeChords(chords),
          section_summary: summarizeSections(job),
          lyrics_excerpt: summarizeLyrics(lyrics),
        };
        setSnapshot(snap);
      } catch {
        if (!cancelled) setSnapshot(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  return snapshot;
}
