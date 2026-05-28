import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Info } from "lucide-react";
import { getJob } from "@/lib/api";
import { analyzeSetlist } from "@/lib/setlistAnalyzer";

/**
 * Renders key / BPM / mode-jump warnings for a setlist.
 * Pulls each job's meta from the server (with caching) so the analyzer
 * has key_root / key_mode / bpm to compare.
 */
export function SetlistWarnings({ setlist }) {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  const jobIdsKey = (setlist?.jobIds || []).join(",");
  useEffect(() => {
    let cancelled = false;
    if (!setlist?.jobIds?.length) {
      // Use a microtask so the state update doesn't run synchronously
      // inside the effect body (strict-mode React flags that pattern).
      Promise.resolve().then(() => {
        if (cancelled) return;
        setJobs([]);
        setLoading(false);
      });
      return () => { cancelled = true; };
    }
    // setLoading deferred to next tick — same rationale as the empty branch.
    Promise.resolve().then(() => { if (!cancelled) setLoading(true); });
    Promise.all(setlist.jobIds.map((id) => getJob(id).catch(() => null)))
      .then((res) => {
        if (cancelled) return;
        const items = res.filter(Boolean).map((j) => ({
          id: j.id,
          title: j.meta?.source_title || j.input,
          key_root: j.meta?.key_root,
          key_mode: j.meta?.key_mode,
          bpm: j.meta?.bpm,
        }));
        setJobs(items);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [setlist?.id, setlist?.jobIds, jobIdsKey]);

  const warnings = useMemo(() => analyzeSetlist(jobs), [jobs]);

  if (!setlist) return null;
  if (loading) {
    return (
      <div className="text-[11px] text-fg-muted/70 px-1">{t("setlist_warn.analyzing")}</div>
    );
  }
  if (jobs.length < 2) {
    return (
      <div className="text-[11px] text-fg-muted/70 px-1">{t("setlist_warn.min_two")}</div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[10px] mono uppercase tracking-[0.18em] text-fg-muted">
        <AlertTriangle className="size-3" /> {t("setlist_warn.header")}
      </div>
      {warnings.length === 0 ? (
        <div className="text-[11px] text-emerald-300 rounded-md px-2 py-1.5 bg-emerald-500/10 ring-1 ring-emerald-500/20">
          {t("setlist_warn.all_good")}
        </div>
      ) : (
        warnings.map((w, i) => {
          const cls = w.severity === "warn"
            ? "bg-amber-400/10 ring-amber-400/30 text-amber-100"
            : "bg-cyan/10 ring-cyan/30 text-cyan/90";
          const Icon = w.severity === "warn" ? AlertTriangle : Info;
          return (
            <div key={i} className={`rounded-md px-2 py-1.5 ring-1 text-[11px] leading-relaxed ${cls}`}>
              <div className="inline-flex items-start gap-1.5">
                <Icon className="size-3 mt-0.5 shrink-0" />
                <div className="min-w-0 break-keep">
                  <div className="font-semibold">{w.message}</div>
                  <div className="opacity-80 mt-0.5">{w.recommendation}</div>
                </div>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
