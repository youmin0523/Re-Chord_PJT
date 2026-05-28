import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, Check, AlertTriangle } from "lucide-react";
import { ConsentSection } from "./ConsentSection";
import { grantConsent } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

// 약관 시행 버전 — `docs/legal/*.md` 의 시행일+버전과 일치해야 함.
// 약관 개정 시 여기 + 백엔드 화이트리스트(CONSENT_TYPES)는 그대로, 새
// 버전만 발행하면 사용자가 재동의 화면 진입.
const POLICY_VERSION = "2026-05-29-v1.0";

const REQUIRED_CONSENTS = [
  { id: "tos",            label: "서비스 이용약관 동의",       docHref: "/legal/terms" },
  { id: "privacy",        label: "개인정보 수집·이용 동의",    docHref: "/legal/privacy" },
  { id: "intl_transfer",  label: "개인정보 국외이전 동의",     docHref: "/legal/privacy#section-4" },
  { id: "age_14",         label: "만 14세 이상 확인",          description: "만 14세 미만은 법정대리인 동의가 필요합니다." },
  { id: "copyright_self", label: "저작권 책임 자가 진술",      docHref: "/legal/copyright",
    description: "업로드하는 음원은 본인이 적법한 권리를 보유했음을 확인합니다." },
];

const OPTIONAL_CONSENTS = [
  { id: "marketing", label: "마케팅 정보 수신 (이메일·푸시)" },
];

/**
 * Signup-time consent flow (Phase B).
 *
 * Renders once after a fresh OAuth sign-in OR when the user re-logs in
 * after a policy version bump. Required consents must all be checked
 * for [동의하고 시작] to enable. Each checked consent is persisted to
 * the backend via POST /consents. After submit we navigate to /app.
 */
export function SignupConsent() {
  const navigate = useNavigate();
  const { user, isGuest } = useAuth();
  const [granted, setGranted] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const allRequiredOk = useMemo(
    () => REQUIRED_CONSENTS.every((c) => granted[c.id]),
    [granted],
  );

  const toggleAll = () => {
    const next = {};
    REQUIRED_CONSENTS.forEach((c) => { next[c.id] = true; });
    OPTIONAL_CONSENTS.forEach((c) => { next[c.id] = true; });
    setGranted(next);
  };

  const submit = async () => {
    if (!allRequiredOk || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      // Send each grant — backend dedupes on (user, type, version).
      const toGrant = [
        ...REQUIRED_CONSENTS.map((c) => c.id),
        ...OPTIONAL_CONSENTS.filter((c) => granted[c.id]).map((c) => c.id),
      ];
      for (const consent_type of toGrant) {
        await grantConsent({
          consent_type,
          version: POLICY_VERSION,
          granted: true,
        });
      }
      navigate("/app", { replace: true });
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (isGuest || !user) {
    return (
      <div className="max-w-md mx-auto px-4 py-12 text-center text-fg-muted">
        로그인 후 동의 화면이 표시됩니다. <a href="/login" className="text-violet hover:underline">로그인</a>
      </div>
    );
  }

  return (
    <main className="max-w-md mx-auto px-4 py-8 sm:py-12 pb-32 space-y-5">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-1.5"
      >
        <div className="flex items-center gap-2 text-[11px] mono uppercase tracking-[0.22em] text-fg-muted">
          <Sparkles className="size-3 text-violet" /> Welcome to Re:Chord
        </div>
        <h1 className="text-2xl font-extrabold leading-tight">
          시작 전 <span className="gradient-text">약관 확인</span>
        </h1>
        <p className="text-[12px] text-fg-muted break-keep">
          정직한 사용을 위해 아래 항목을 확인하고 동의해 주세요. 모든
          필수 항목은 한국 개인정보보호법(PIPA)에 따라 요구됩니다.
        </p>
      </motion.div>

      <button
        type="button"
        onClick={toggleAll}
        className="w-full inline-flex items-center justify-center gap-1.5 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-fg text-[12px] ring-1 ring-white/8"
      >
        <Check className="size-3.5" /> 모두 동의
      </button>

      <section className="space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
          필수 동의
        </div>
        {REQUIRED_CONSENTS.map((c) => (
          <ConsentSection
            key={c.id}
            id={c.id}
            label={c.label}
            description={c.description}
            docHref={c.docHref}
            required
            checked={granted[c.id]}
            onChange={(v) => setGranted((p) => ({ ...p, [c.id]: v }))}
          />
        ))}
      </section>

      <section className="space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
          선택 동의
        </div>
        {OPTIONAL_CONSENTS.map((c) => (
          <ConsentSection
            key={c.id}
            id={c.id}
            label={c.label}
            description={c.description}
            checked={granted[c.id]}
            onChange={(v) => setGranted((p) => ({ ...p, [c.id]: v }))}
          />
        ))}
      </section>

      {error && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 text-rose-200 text-[12px]">
          <AlertTriangle className="size-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={!allRequiredOk || submitting}
        className="w-full py-3 rounded-xl bg-gradient-to-r from-violet to-cyan text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
      >
        {submitting ? "처리 중…" : "동의하고 시작"}
      </button>

      <div className="text-[10px] text-fg-muted/70 text-center break-keep">
        동의 후에도 마이페이지에서 언제든지 변경·철회할 수 있습니다.
      </div>
    </main>
  );
}
