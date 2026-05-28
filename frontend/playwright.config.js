/* global process */
import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for Re:Chord frontend E2E.
 *
 * Run a single golden-path test:
 *   npx playwright test
 *
 * The webServer block starts the Vite dev server automatically; we
 * assume the FastAPI backend is already running on :7860 (developer
 * starts it separately with `uvicorn backend.app.main:app`).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,             // keep deterministic on a single-GPU dev box
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "npm run dev -- --port 5173 --host 127.0.0.1",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
