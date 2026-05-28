import { ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * One row inside the SignupConsent flow — checkbox + label + "상세" link.
 *
 * Required vs optional is purely visual; the parent enforces submit
 * gating via `requiredConsentsGranted`.
 *
 *   <ConsentSection id="tos" required label="이용약관 동의"
 *                   docHref="/legal/terms" checked={…} onChange={…} />
 */
export function ConsentSection({
  id,
  label,
  required = false,
  checked,
  onChange,
  docHref,
  description,
}) {
  return (
    <label
      htmlFor={`consent-${id}`}
      className={cn(
        "flex items-start gap-3 px-3 py-3 rounded-xl ring-1 transition-colors cursor-pointer",
        checked
          ? "bg-violet/10 ring-violet/30"
          : "bg-white/[0.02] ring-white/8 hover:bg-white/[0.04]",
      )}
    >
      <input
        id={`consent-${id}`}
        type="checkbox"
        checked={!!checked}
        onChange={(e) => onChange(e.target.checked)}
        aria-required={required}
        className="mt-0.5 size-4 accent-violet shrink-0"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-sm text-fg">
          <span
            className={cn(
              "mono text-[10px] uppercase tracking-[0.18em] px-1.5 py-0.5 rounded-full",
              required
                ? "bg-rose-500/15 text-rose-300"
                : "bg-white/5 text-fg-muted",
            )}
          >
            {required ? "필수" : "선택"}
          </span>
          <span className="font-medium">{label}</span>
        </div>
        {description && (
          <div className="text-[11px] text-fg-muted mt-1 break-keep">
            {description}
          </div>
        )}
      </div>
      {docHref && (
        <a
          href={docHref}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-[11px] text-cyan-300 hover:text-cyan-200 shrink-0"
        >
          상세 <ExternalLink className="size-3" />
        </a>
      )}
    </label>
  );
}
