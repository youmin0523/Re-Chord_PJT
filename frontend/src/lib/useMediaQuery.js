import { useCallback, useSyncExternalStore } from "react";

/**
 * Subscribe to a CSS media query. Returns ``true`` while the query matches.
 *
 * Why a hook and not Tailwind responsive classes:
 *   - Some layout decisions (e.g. "render tabs vs accordion") have to
 *     toggle between *different component trees*, not just different
 *     classes — CSS-only switching would mount both branches and
 *     double-trigger React.lazy chunks.
 *   - We want a tearing-free read across concurrent renders, so we lean
 *     on ``useSyncExternalStore``. Falls back to ``false`` on the server
 *     (mobile-last layout prevention) and re-syncs on mount.
 *
 *   const isMobile = useMediaQuery("(max-width: 639px)");  // <sm
 */
export function useMediaQuery(query) {
  const subscribe = useCallback((onChange) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => {};
    let mql;
    try { mql = window.matchMedia(query); } catch { return () => {}; }
    // Safari < 14 only supports the deprecated addListener API.
    if (mql.addEventListener) {
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    }
    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, [query]);

  const getSnapshot = useCallback(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    try { return window.matchMedia(query).matches; } catch { return false; }
  }, [query]);

  // Server snapshot is always ``false`` so SSR/SSG always renders the
  // desktop branch — saves a hydration flip for non-mobile viewers.
  const getServerSnapshot = () => false;

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
