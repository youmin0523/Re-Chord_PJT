/**
 * Supabase client — Phase B auth provider.
 *
 * Returns ``null`` when ``VITE_SUPABASE_URL`` / ``VITE_SUPABASE_ANON_KEY``
 * are not set so Phase A (guest-only) deploys don't fail at module load.
 * Components must null-check before calling ``supabase.auth.*``.
 *
 * The SDK is loaded lazily (dynamic import inside a memoised getter) so
 * Phase A bundles don't pay the ~50 KB cost. First sign-in call pulls
 * the chunk on demand.
 */

const URL = import.meta.env.VITE_SUPABASE_URL || "";
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || "";

export const isSupabaseConfigured = Boolean(URL && ANON_KEY);

let _client = null;

/** Returns the singleton Supabase client, or ``null`` if not configured. */
export async function getSupabase() {
  if (!isSupabaseConfigured) return null;
  if (_client) return _client;
  try {
    const { createClient } = await import("@supabase/supabase-js");
    _client = createClient(URL, ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,            // handle OAuth callback hash
        flowType: "pkce",
      },
    });
    return _client;
  } catch (err) {
    // SDK missing or load failed — log and degrade to "not configured".
    // eslint-disable-next-line no-console
    console.warn("Supabase SDK failed to load; sign-in disabled", err);
    return null;
  }
}

/** Start a Kakao OAuth sign-in. ``redirectTo`` is where Supabase sends
 *  the user after the kakao.com round-trip — usually ``/auth/callback``. */
export async function signInWithKakao(redirectTo) {
  const sb = await getSupabase();
  if (!sb) throw new Error("Supabase not configured");
  return sb.auth.signInWithOAuth({
    provider: "kakao",
    options: { redirectTo, scopes: "profile_nickname account_email" },
  });
}

/** Email + password sign-in (fallback when Kakao isn't desired). */
export async function signInWithPassword(email, password) {
  const sb = await getSupabase();
  if (!sb) throw new Error("Supabase not configured");
  return sb.auth.signInWithPassword({ email, password });
}

export async function signOut() {
  const sb = await getSupabase();
  if (!sb) return;
  await sb.auth.signOut();
  try { localStorage.removeItem("rechord:auth:token"); } catch { /* noop */ }
}

/** Subscribe to session changes. Returns an unsubscribe function. */
export async function onAuthChange(handler) {
  const sb = await getSupabase();
  if (!sb) return () => {};
  const { data } = sb.auth.onAuthStateChange((event, session) => {
    handler({ event, session });
  });
  return () => data.subscription.unsubscribe();
}
