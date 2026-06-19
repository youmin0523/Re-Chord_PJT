import { useEffect, useState } from "react";
import { AlertTriangle, Info, CheckCircle2, X } from "lucide-react";

import { subscribe, dismiss } from "@/lib/toast";

const ICON = {
  error: AlertTriangle,
  info: Info,
  success: CheckCircle2,
};

const RING = {
  error: "ring-red-400/40",
  info: "ring-white/15",
  success: "ring-emerald-400/40",
};

const TINT = {
  error: "text-red-300",
  info: "text-fg-muted",
  success: "text-emerald-300",
};

/** Global toast outlet. Mounted once in AppShell; renders whatever
 *  `lib/toast.js` emits (e.g. a 410 "음원 만료" notice from a download). */
export function Toaster() {
  const [toasts, setToasts] = useState([]);
  useEffect(() => subscribe(setToasts), []);
  if (!toasts.length) return null;
  return (
    <div
      className="fixed z-[100] bottom-4 right-4 flex flex-col gap-2 w-[min(92vw,380px)]"
      role="status"
      aria-live="polite"
    >
      {toasts.map((t) => {
        const Icon = ICON[t.type] || Info;
        return (
          <div
            key={t.id}
            className={`glass rounded-xl px-4 py-3 text-sm shadow-lg ring-1 ${RING[t.type] || RING.info} flex items-start gap-2.5 animate-in`}
          >
            <Icon className={`size-4 mt-0.5 shrink-0 ${TINT[t.type] || TINT.info}`} />
            <span className="flex-1 leading-snug">{t.message}</span>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="닫기"
              className="opacity-50 hover:opacity-100 transition-opacity shrink-0"
            >
              <X className="size-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
