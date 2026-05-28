/**
 * Vitest global setup.
 *
 * Extends ``expect`` with jest-dom matchers (toBeInTheDocument, etc.) and
 * stubs the browser APIs jsdom doesn't ship — matchMedia is the main one
 * React components hit when they read prefers-color-scheme on mount.
 */

import "@testing-library/jest-dom/vitest";

// matchMedia: jsdom doesn't implement this. Components that read
// ``window.matchMedia("(prefers-color-scheme: light)")`` (e.g. useTheme)
// crash without it.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},      // deprecated but some libs still call it
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  });
}

// ResizeObserver: framer-motion / wavesurfer / our slider components
// instantiate it on mount. Provide a no-op so render() doesn't blow up.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// IntersectionObserver: lazy-mount checks in some panels.
if (typeof window !== "undefined" && !window.IntersectionObserver) {
  window.IntersectionObserver = class {
    constructor() { this.root = null; this.rootMargin = ""; this.thresholds = []; }
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
  };
}
