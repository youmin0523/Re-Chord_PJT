import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation, Trans } from "react-i18next";
import { motion } from "framer-motion";
import { Music2, AlertTriangle } from "lucide-react";
import { useAuth } from "@/lib/useAuth";
import { isSupabaseConfigured, signInWithKakao } from "@/lib/supabase";

/**
 * Login page (Phase B). Renders only when Supabase is configured — in
 * Phase A this page reads as "guest mode active" and links back to /app.
 *
 * Kakao is the primary path for our Korean worship users; email/password
 * is intentionally left as a manual fallback the operator can wire in
 * later (not part of the MVP consent flow).
 */
export default function Login() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { user, isGuest, isPhaseA } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);

  // Already signed in → bounce to /app (or the consent screen, which is
  // itself gated on auth).
  useEffect(() => {
    if (user && !isGuest) navigate("/app", { replace: true });
  }, [user, isGuest, navigate]);

  const handleKakao = async () => {
    if (!isSupabaseConfigured) {
      setError(t("auth.supabase_unset"));
      return;
    }
    setError(null);
    setPending(true);
    try {
      const redirectTo = `${window.location.origin}/auth/callback`;
      const { error: e } = await signInWithKakao(redirectTo);
      if (e) throw e;
      // signInWithOAuth redirects the browser; the call above resolves
      // shortly before navigation. If we get here without redirect, the
      // SDK probably refused — flag it.
    } catch (e) {
      setPending(false);
      setError(e?.message || String(e));
    }
  };

  if (isPhaseA) {
    return (
      <main className="max-w-md mx-auto px-4 py-16 text-center space-y-4">
        <Music2 className="size-10 mx-auto text-violet" />
        <h1 className="text-2xl font-bold">{t("auth.phase_a_heading")}</h1>
        <p className="text-[13px] text-fg-muted break-keep">{t("auth.phase_a_body")}</p>
        <button
          type="button"
          onClick={() => navigate("/app")}
          className="px-4 py-2 rounded-full bg-violet/20 hover:bg-violet/30 text-violet ring-1 ring-violet/40 text-[13px]"
        >
          {t("auth.go_to_app")}
        </button>
      </main>
    );
  }

  return (
    <main className="max-w-md mx-auto px-4 py-12 sm:py-20 space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center space-y-2"
      >
        <Music2 className="size-10 mx-auto text-violet" />
        <h1 className="text-2xl font-extrabold tracking-tight">
          <span className="gradient-text">{t("auth.login_heading_a")}</span>
          <span className="text-fg">{t("auth.login_heading_b")}</span>
        </h1>
        <p className="text-[13px] text-fg-muted break-keep">{t("auth.login_subtitle")}</p>
      </motion.div>

      <button
        type="button"
        onClick={handleKakao}
        disabled={pending}
        className="w-full py-3 rounded-xl bg-[#FEE500] text-[#3C1E1E] font-bold disabled:opacity-50 hover:brightness-95 transition flex items-center justify-center gap-2"
      >
        {pending ? t("auth.kakao_pending") : t("auth.kakao_start")}
      </button>

      {error && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 text-rose-200 text-[12px]">
          <AlertTriangle className="size-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="text-[10px] text-fg-muted/70 text-center break-keep">
        <Trans
          i18nKey="auth.agreement_notice"
          components={{
            terms: <a href="/legal/terms" className="underline" />,
            privacy: <a href="/legal/privacy" className="underline mx-1" />,
          }}
        />
      </div>
    </main>
  );
}
