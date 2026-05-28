import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, AlertTriangle } from "lucide-react";
import { getSupabase, isSupabaseConfigured } from "@/lib/supabase";
import { listMyConsents } from "@/lib/api";

/**
 * OAuth return endpoint.
 *
 * Supabase SDK reads the auth hash from the URL automatically
 * (``detectSessionInUrl: true``). We just need to wait for the session
 * to materialise, then route the user to either:
 *
 *   - /signup-consent  (no prior consent on the current policy version)
 *   - /app             (already onboarded)
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!isSupabaseConfigured) {
        setError("Supabase 미설정 — /login 으로 돌아갑니다");
        setTimeout(() => navigate("/login", { replace: true }), 1500);
        return;
      }
      try {
        const sb = await getSupabase();
        if (!sb) throw new Error("Supabase client load failed");
        // Wait up to ~3s for the SDK to consume the URL hash.
        let session = null;
        for (let i = 0; i < 30 && !cancelled; i++) {
          const r = await sb.auth.getSession();
          if (r.data.session) { session = r.data.session; break; }
          await new Promise((r) => setTimeout(r, 100));
        }
        if (cancelled) return;
        if (!session) throw new Error("로그인 세션을 받지 못했습니다");

        // Token already cached by the useAuth onAuthChange listener;
        // listMyConsents now carries the Authorization header.
        let consents = [];
        try { consents = await listMyConsents(); } catch { consents = []; }
        const activeRequired = new Set(
          consents
            .filter((c) => c.granted && !c.revoked_at)
            .map((c) => c.consent_type),
        );
        const REQUIRED = ["tos", "privacy", "intl_transfer", "age_14", "copyright_self"];
        const needsConsent = REQUIRED.some((t) => !activeRequired.has(t));
        navigate(needsConsent ? "/signup-consent" : "/app", { replace: true });
      } catch (e) {
        setError(e?.message || String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [navigate]);

  return (
    <main className="max-w-md mx-auto px-4 py-20 text-center space-y-4">
      {error ? (
        <>
          <AlertTriangle className="size-8 mx-auto text-rose-300" />
          <h1 className="text-lg font-bold text-rose-200">로그인 처리 실패</h1>
          <p className="text-[12px] text-fg-muted break-keep">{error}</p>
          <button
            type="button"
            onClick={() => navigate("/login", { replace: true })}
            className="px-3 py-1.5 rounded-full bg-white/5 hover:bg-white/10 text-[12px] text-fg-muted hover:text-fg"
          >
            로그인 화면으로
          </button>
        </>
      ) : (
        <>
          <Loader2 className="size-8 mx-auto text-violet animate-spin" />
          <h1 className="text-lg font-bold">로그인 확인 중…</h1>
          <p className="text-[12px] text-fg-muted break-keep">
            카카오 인증 결과를 받아 동의 화면으로 안내합니다.
          </p>
        </>
      )}
    </main>
  );
}
