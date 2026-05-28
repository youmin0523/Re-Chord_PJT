import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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
      setError("Supabase가 설정되지 않았습니다 (.env의 VITE_SUPABASE_URL/ANON_KEY).");
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
        <h1 className="text-2xl font-bold">게스트 모드로 사용 중</h1>
        <p className="text-[13px] text-fg-muted break-keep">
          베타 단계는 별도 로그인 없이 모든 기능을 사용할 수 있습니다.
          정식 출시 시 카카오 로그인 + 동의 화면이 활성화됩니다.
        </p>
        <button
          type="button"
          onClick={() => navigate("/app")}
          className="px-4 py-2 rounded-full bg-violet/20 hover:bg-violet/30 text-violet ring-1 ring-violet/40 text-[13px]"
        >
          /app 으로 이동
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
          <span className="gradient-text">Re:Chord</span> 시작
        </h1>
        <p className="text-[13px] text-fg-muted break-keep">
          AI 보컬 분리 · 키·템포·코드·악보 자동 분석. 카카오로 1초 만에
          시작하세요.
        </p>
      </motion.div>

      <button
        type="button"
        onClick={handleKakao}
        disabled={pending}
        className="w-full py-3 rounded-xl bg-[#FEE500] text-[#3C1E1E] font-bold disabled:opacity-50 hover:brightness-95 transition flex items-center justify-center gap-2"
      >
        {pending ? "카카오 로그인 진행 중…" : "카카오로 시작"}
      </button>

      {error && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 text-rose-200 text-[12px]">
          <AlertTriangle className="size-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="text-[10px] text-fg-muted/70 text-center break-keep">
        가입 시 <a href="/legal/terms" className="underline">이용약관</a>과
        <a href="/legal/privacy" className="underline mx-1">개인정보처리방침</a>
        에 동의하게 됩니다 (다음 화면에서 확인).
      </div>
    </main>
  );
}
