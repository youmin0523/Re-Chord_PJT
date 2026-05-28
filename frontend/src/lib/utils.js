import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export function formatDuration(seconds) {
  if (!isFinite(seconds) || seconds <= 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** Filesystem-safe slug: strips reserved chars, collapses whitespace, caps length. */
export function slugFilename(s, max = 80) {
  if (!s) return "track";
  let out = String(s).normalize("NFKC")
    .replace(/[\\/:*?"<>|]+/g, " ")     // Windows reserved
    // eslint-disable-next-line no-control-regex -- stripping control chars from filenames is the intent
    .replace(/[\x00-\x1f]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (out.length > max) out = out.slice(0, max).trim();
  return out || "track";
}

/** Build a download filename from the job's source title + a role + an extension. */
export function trackFilename(job, role, ext) {
  const title = job?.meta?.source_title || "track";
  const base = slugFilename(title);
  const cleanRole = role ? `_${slugFilename(role, 32)}` : "";
  const cleanExt = ext.replace(/^\./, "").toLowerCase();
  return `${base}${cleanRole}.${cleanExt}`;
}
