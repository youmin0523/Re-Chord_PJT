/**
 * Auth hook — Phase A returns a fixed guest user. Phase B will swap in
 * Clerk or Supabase by switching `VITE_AUTH_PROVIDER` in .env.local; this
 * hook abstracts over both so components don't care.
 *
 * Token storage:
 *   - localStorage["rechord:auth:token"] when present is sent as the
 *     ``Authorization: Bearer …`` header on every API call (api.js already
 *     reads from window for future use; for now the header is added only
 *     when this hook explicitly attaches it).
 *
 * Phase A behaviour:
 *   - user = { id: "guest", isGuest: true }
 *   - signIn/signOut are no-ops
 *   - components render but auth-gated routes simply degrade gracefully
 */

import { useEffect, useState } from "react";
import {
  isSupabaseConfigured,
  onAuthChange,
  getSupabase,
  signOut as sbSignOut,
} from "./supabase";


const TOKEN_KEY = "rechord:auth:token";

function loadToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || null;
  } catch {
    return null;
  }
}


export function useAuth() {
  const provider = (import.meta.env.VITE_AUTH_PROVIDER || "").toLowerCase();
  // Phase A iff no provider env AND no Supabase config — either flips
  // us into Phase B with the auth menu / consent flow visible.
  const phaseA = !provider && !isSupabaseConfigured;

  const [token, setTokenState] = useState(loadToken);
  const [user, setUser] = useState(() =>
    phaseA ? { id: "guest", isGuest: true, name: "guest" } : null,
  );

  // Phase B: decode token claims for display name. We deliberately don't
  // verify here — verification happens on the backend.
  useEffect(() => {
    if (phaseA) return;
    if (!token) { setUser({ id: "guest", isGuest: true, name: "guest" }); return; }
    try {
      const [, payload] = token.split(".");
      const claims = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
      setUser({
        id: claims.sub || claims.user_id || "?",
        email: claims.email,
        name: claims.name || claims.nickname || claims.email,
        isGuest: false,
      });
    } catch {
      setUser({ id: "guest", isGuest: true, name: "guest" });
    }
  }, [token, phaseA]);

  // Supabase: subscribe to session changes so the token state stays
  // in sync after OAuth redirect, token refresh, or sign-out.
  useEffect(() => {
    if (phaseA || !isSupabaseConfigured) return undefined;
    let unsubscribe = () => {};
    let cancelled = false;
    (async () => {
      const sb = await getSupabase();
      if (!sb || cancelled) return;
      // Seed with the existing session on mount.
      const { data: { session } } = await sb.auth.getSession();
      if (session?.access_token) {
        try { localStorage.setItem(TOKEN_KEY, session.access_token); } catch { /* ignore */ }
        setTokenState(session.access_token);
      }
      // Then keep in sync.
      unsubscribe = await onAuthChange(({ session: s }) => {
        const tk = s?.access_token ?? null;
        try {
          if (tk) localStorage.setItem(TOKEN_KEY, tk);
          else localStorage.removeItem(TOKEN_KEY);
        } catch { /* ignore */ }
        setTokenState(tk);
      });
    })();
    return () => { cancelled = true; unsubscribe(); };
  }, [phaseA]);

  const signIn = (newToken) => {
    if (phaseA) return;        // no-op in Phase A
    try { localStorage.setItem(TOKEN_KEY, newToken); } catch { /* ignore */ }
    setTokenState(newToken);
  };

  const signOut = () => {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
    setTokenState(null);
    if (phaseA) setUser({ id: "guest", isGuest: true, name: "guest" });
    // Supabase signOut runs lazily; fire-and-forget so the UI stays snappy.
    if (isSupabaseConfigured) {
      sbSignOut().catch(() => { /* ignore */ });
    }
  };

  return {
    user,
    token,
    isGuest: user?.isGuest ?? true,
    isPhaseA: phaseA,
    provider,
    signIn,
    signOut,
  };
}
