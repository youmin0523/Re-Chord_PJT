import { useTranslation } from "react-i18next";
import { LogIn, LogOut, User as UserIcon } from "lucide-react";
import { useAuth } from "@/lib/useAuth";
import { cn } from "@/lib/utils";

/**
 * Header auth menu. In Phase A this just shows "guest" — clicking signin
 * does nothing because no provider is configured. In Phase B (set
 * ``VITE_AUTH_PROVIDER=clerk`` and wire the Clerk SDK), signin pops the
 * Clerk modal and signout clears the cached JWT.
 */
export function AuthMenu({ className = "" }) {
  const { t } = useTranslation();
  const { user, isGuest, isPhaseA, provider, signOut } = useAuth();

  if (isPhaseA) {
    // Phase A: passive label, no interaction.
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 mono text-[10px] text-fg-muted",
          className,
        )}
        title={t("auth.phase_a_title")}
      >
        <UserIcon className="size-3" /> {t("auth.guest")}
      </span>
    );
  }

  // Phase B paths — these need the actual SDK wired up. For now the
  // buttons exist but signin is a placeholder; integrators replace
  // ``handleSignIn`` with their SDK call.
  const handleSignIn = () => {
    // e.g. Clerk: openSignIn(); Supabase: supabase.auth.signInWithOAuth(...).
    // Left blank intentionally — see docs/auth-integration.md.
    alert(
      `Sign-in path placeholder. Wire ${provider} SDK into AuthMenu.handleSignIn.`,
    );
  };

  if (isGuest || !user) {
    return (
      <button
        type="button"
        onClick={handleSignIn}
        className={cn(
          "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-[11px] bg-violet/15 hover:bg-violet/25 text-violet ring-1 ring-violet/30",
          className,
        )}
      >
        <LogIn className="size-3" /> {t("auth.sign_in")}
      </button>
    );
  }

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span className="inline-flex items-center gap-1 mono text-[10px] text-fg-muted">
        <UserIcon className="size-3" />
        <span className="max-w-[120px] truncate">{user.name || user.email || user.id}</span>
      </span>
      <button
        type="button"
        onClick={signOut}
        title={t("auth.sign_out")}
        className="inline-flex items-center justify-center size-6 rounded hover:bg-white/5 text-fg-muted hover:text-fg"
      >
        <LogOut className="size-3" />
      </button>
    </span>
  );
}
