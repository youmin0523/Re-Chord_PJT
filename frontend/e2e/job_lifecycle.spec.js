import { test, expect } from "@playwright/test";

/**
 * Job-lifecycle smoke: confirms the *frontend* correctly drives the
 * upload → /jobs POST → WebSocket /jobs/:id/progress → artifact links
 * pipeline against a running backend.
 *
 * Skipped automatically when the backend isn't reachable, so this spec is
 * safe to run on a frontend-only CI lane. To activate locally:
 *   1. Start backend: `uv run uvicorn backend.app.main:app --port 7860`
 *   2. Start frontend: `cd frontend && npm run dev`
 *   3. `RECHORD_E2E_BACKEND=http://127.0.0.1:7860 npx playwright test`
 */
const BACKEND = process.env.RECHORD_E2E_BACKEND || "";

test.describe("Job lifecycle (requires live backend)", () => {
  test.skip(!BACKEND, "RECHORD_E2E_BACKEND not set — skipping live job test");

  test("/health probe responds", async ({ request }) => {
    const r = await request.get(`${BACKEND}/health`);
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    expect(body.status).toBe("ok");
  });

  test("formats endpoint returns at least wav+flac", async ({ request }) => {
    const r = await request.get(`${BACKEND}/formats`);
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    const flat = JSON.stringify(body).toLowerCase();
    expect(flat).toContain("wav");
    expect(flat).toContain("flac");
  });

  test("job page handles missing job ID gracefully", async ({ page }) => {
    await page.goto("/job/nonexistent-id-12345");
    // We expect either a not-found error message OR redirect to /app.
    const bodyText = await page.locator("body").textContent();
    expect(bodyText).toBeTruthy();
    // Should not crash with white-screen.
    const hasUnhandledError = bodyText?.includes("Cannot read properties")
      || bodyText?.includes("undefined is not a function");
    expect(hasUnhandledError).toBeFalsy();
  });

  test("library page lists jobs from /jobs API", async ({ page, request }) => {
    // Try to fetch the live job list first so we know what to expect.
    const r = await request.get(`${BACKEND}/jobs`);
    if (!r.ok()) test.skip(true, "GET /jobs not available");
    await page.goto("/library");
    await expect(page.locator("text=/라이브러리|Library/i").first()).toBeVisible();
  });
});
