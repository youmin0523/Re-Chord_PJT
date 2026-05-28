import { useTranslation } from "react-i18next";
import { AlertTriangle, RefreshCw, ExternalLink, Cpu, FileX, Lock, Network } from "lucide-react";
import { Link } from "react-router-dom";

/**
 * Friendly error recovery card. Inspects the raw error string and picks the
 * most useful recovery hint we can give — never a bare stack trace.
 *
 * Usage:
 *   <ErrorCard error={errString} onRetry={() => ...} jobInput={job.input} />
 */
export function ErrorCard({ error, onRetry, jobInput, className = "" }) {
  const { t } = useTranslation();
  const diag = classify(error || "", t);
  const Icon = diag.icon;

  return (
    <div
      className={`rounded-2xl p-5 space-y-4 bg-rose-500/[0.05] ring-1 ring-rose-500/20 ${className}`}
    >
      <div className="flex items-start gap-3">
        <div className="inline-flex items-center justify-center size-9 rounded-xl bg-rose-500/15 text-rose-300 shrink-0">
          <Icon className="size-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-rose-100">{diag.title}</div>
          <div className="text-[12px] text-rose-200/80 leading-relaxed mt-1 break-keep">
            {diag.hint}
          </div>
        </div>
      </div>

      {diag.steps && diag.steps.length > 0 && (
        <ol className="ml-2 space-y-1 text-[12px] text-rose-100/85 leading-relaxed">
          {diag.steps.map((s, i) => (
            <li key={i} className="flex gap-2">
              <span className="mono text-rose-300 shrink-0">{i + 1}.</span>
              <span className="break-keep">{s}</span>
            </li>
          ))}
        </ol>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-rose-500/15 hover:bg-rose-500/25 text-rose-100 ring-1 ring-rose-500/25"
          >
            <RefreshCw className="size-3.5" /> {t("errors.card_retry")}
          </button>
        )}
        <Link
          to="/app"
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
        >
          {t("error_card.new_job")}
        </Link>
        {jobInput && (
          <a
            href={typeof jobInput === "string" && jobInput.startsWith("http") ? jobInput : "#"}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs bg-white/5 hover:bg-white/10 text-fg-muted hover:text-fg"
          >
            <ExternalLink className="size-3.5" /> {t("error_card.open_source")}
          </a>
        )}
      </div>

      <details className="text-[10px] text-rose-200/50 mono">
        <summary className="cursor-pointer select-none hover:text-rose-200/80">
          {t("error_card.tech_details")}
        </summary>
        <pre className="mt-2 whitespace-pre-wrap break-all">{error}</pre>
      </details>
    </div>
  );
}

function classify(msg, t) {
  const m = String(msg).toLowerCase();

  if (/private|sign.?in|login|members.?only|403|401/.test(m)) {
    return {
      icon: Lock,
      title: t("error_card.private_title"),
      hint: t("error_card.private_hint"),
      steps: [t("error_card.private_step1"), t("error_card.private_step2")],
    };
  }
  if (/timeout|timed.?out|connection|network|dns|getaddrinfo/.test(m)) {
    return {
      icon: Network,
      title: t("error_card.network_title"),
      hint: t("error_card.network_hint"),
      steps: [t("error_card.network_step1"), t("error_card.network_step2")],
    };
  }
  if (/cuda|out of memory|oom|vram|cublas/.test(m)) {
    return {
      icon: Cpu,
      title: t("error_card.gpu_title"),
      hint: t("error_card.gpu_hint"),
      steps: [t("error_card.gpu_step1"), t("error_card.gpu_step2")],
    };
  }
  if (/no audio|invalid format|unsupported|codec|ffprobe|moov/.test(m)) {
    return {
      icon: FileX,
      title: t("error_card.format_title"),
      hint: t("error_card.format_hint"),
      steps: [t("error_card.format_step1"), t("error_card.format_step2")],
    };
  }
  if (/yt.?dlp|extractor|unable to download|http error 4/.test(m)) {
    return {
      icon: ExternalLink,
      title: t("error_card.extractor_title"),
      hint: t("error_card.extractor_hint"),
      steps: [t("error_card.extractor_step1"), t("error_card.extractor_step2")],
    };
  }

  return {
    icon: AlertTriangle,
    title: t("error_card.generic_title"),
    hint: t("error_card.generic_hint"),
    steps: [t("error_card.generic_step1"), t("error_card.generic_step2")],
  };
}
