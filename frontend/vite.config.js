import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

// ESM lacks __dirname; derive it from import.meta.url so the path alias
// keeps working without Node's CJS magic globals.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  // Force the automatic JSX runtime at the esbuild level so vitest's
  // transform pipeline picks it up. Without this, plain ``<Foo />`` in
  // .jsx tests bails with "React is not defined" because the @vitejs
  // plugin-react JSX transform doesn't always run in vitest mode.
  esbuild: {
    jsx: "automatic",
  },
  server: {
    port: 3000,
    host: "127.0.0.1",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        // Split heavy vendor libs into their own chunks so the main bundle
        // stays under the 500 KB warning threshold. Each vendor chunk is
        // cached independently — when we update only app code, the user's
        // browser keeps the React/framer/lucide chunks from disk cache.
        manualChunks: (id) => {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("react-router") || id.includes("react-dom") || id.includes("/react/")) {
            return "vendor-react";
          }
          if (id.includes("framer-motion")) return "vendor-framer";
          if (id.includes("lucide-react")) return "vendor-icons";
          if (id.includes("i18next")) return "vendor-i18n";
          if (id.includes("wavesurfer")) return "vendor-wavesurfer";
          return "vendor";
        },
      },
    },
  },
  // Vitest config — unit smoke tests for pure-render components. Run
  // with ``npm run test`` (or ``npm run test:watch``). E2E lives in
  // ./e2e/ via Playwright; this is the fast, in-jsdom feedback loop.
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.{test,spec}.{js,jsx}"],
    css: false,
  },
});
