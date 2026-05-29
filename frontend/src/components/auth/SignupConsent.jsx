import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Sparkles, Check, AlertTriangle } from "lucide-react";
import { ConsentSection } from "./ConsentSection";
import { grantConsent } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

// 약관 시행 버전 — `docs/legal/*.md` 의 시행일+버전과 일치해야 함.
// 약관 개정 시 여기 + 백엔드 화이트리스트(CONSENT_TYPES)는 그대로, 새
// 버전만 발행하면 사용자가 재동의 화면 진입.
const POLICY_VERSION = "2026-05-29-v1.0";

const REQUIRED_IDS = [
  { id: "tos",            docHref: "/legal/terms" },
  { id: "privacy",        docHref: "/legal/privacy" },
  { id: "intl_transfer",  docHref: "/legal/privacy#section-4" },
  { id: "age_14",         hasDescription: true },
  { id: "copyright_self", docHref: "/legal/copyright", hasDescription: true },
];

const OPTIONAL_IDS = [
  { id: "marketing" },
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
  const { t } = useTranslation();
  const { user, isGuest } = useAuth();
  const [granted, setGranted] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const allRequiredOk = useMemo(
    () => REQUIRED_IDS.every((c) => granted[c.id]),
    [granted],
  );

  const toggleAll = () => {
    const next = {};
    REQUIRED_IDS.forEach((c) => { next[c.id] = true; });
    OPTIONAL_IDS.forEach((c) => { next[c.id] = true; });
    setGranted(next);
  };

  const submit = async () => {
    if (!allRequiredOk || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      // Send each grant — backend dedupes on (user, type, version).
      const toGrant = [
        ...REQUIRED_IDS.map((c) => c.id),
        ...OPTIONAL_IDS.filter((c) => granted[c.id]).map((c) => c.id),
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
        {t("auth.consent_login_required")} <a href="/login" className="text-violet hover:underline">{t("auth.consent_login_link")}</a>
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
          <Sparkles className="size-3 text-violet" /> {t("auth.consent_pretitle")}
        </div>
        <h1 className="text-2xl font-extrabold leading-tight">
          {t("auth.consent_heading_a")}<span className="gradient-text">{t("auth.consent_heading_b")}</span>
        </h1>
        <p className="text-[12px] text-fg-muted break-keep">{t("auth.consent_subtitle")}</p>
      </motion.div>

      <button
        type="button"
        onClick={toggleAll}
        className="w-full inline-flex items-center justify-center gap-1.5 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-fg text-[12px] ring-1 ring-white/8"
      >
        <Check className="size-3.5" /> {t("auth.consent_agree_all")}
      </button>

      <section className="space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
          {t("auth.consent_required_label")}
        </div>
        {REQUIRED_IDS.map((c) => (
          <ConsentSection
            key={c.id}
            id={c.id}
            label={t(`auth.consent_label_${c.id}`)}
            description={c.hasDescription ? t(`auth.consent_label_${c.id}_desc`) : undefined}
            docHref={c.docHref}
            required
            checked={granted[c.id]}
            onChange={(v) => setGranted((p) => ({ ...p, [c.id]: v }))}
          />
        ))}
      </section>

      <section className="space-y-2">
        <div className="text-[11px] mono uppercase tracking-[0.18em] text-fg-muted">
          {t("auth.consent_optional_label")}
        </div>
        {OPTIONAL_IDS.map((c) => (
          <ConsentSection
            key={c.id}
            id={c.id}
            label={t(`auth.consent_label_${c.id}`)}
            description={c.hasDescription ? t(`auth.consent_label_${c.id}_desc`) : undefined}
            checked={granted[c.id]}
            onChange={(v) => setGranted((p) => ({ ...p, [c.id]: v }))}
          />
        ))}
      </section>

      {error && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 text-rose-200 text-[12px]" role="alert">
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
        {submitting ? t("auth.consent_submitting") : t("auth.consent_submit")}
      </button>

      <div className="text-[10px] text-fg-muted/70 text-center break-keep">
        {t("auth.consent_footer")}
      </div>
    </main>
  );
}
