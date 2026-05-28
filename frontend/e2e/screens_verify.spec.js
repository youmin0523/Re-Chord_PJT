/**
 * Visual verification of the UX changes shipped this session.
 *
 * Runs against the existing dev server; saves screenshots to
 * ``test-results/screens/`` so the operator can eyeball them. Not a gate
 * — pure capture. We dismiss the OnboardingTour first because it overlays
 * everything and intercepts pointer events otherwise.
 *
 * Targets:
 *   1. Landing       (desktop) — baseline
 *   2. /app          (desktop) — Karaoke selected + Key/Tempo accordion open → ±1 steppers visible
 *   3. /app          (mobile 360px) — narrow viewport, regen banner area
 *   4. /app + regen  — routed with location.state to verify the prefill banner
 */

import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const OUT = path.resolve(__dirname, "../test-results/screens");
mkdirSync(OUT, { recursive: true });

async function dismissOnboarding(page) {
  // Seed the localStorage flag the tour checks so it never opens. Has to
  // happen BEFORE the React app boots, so we set it via initScript and
  // reload once the page is in scope.
  await page.addInitScript(() => {
    try { window.localStorage.setItem("rechord:onboarding:seen:v1", "1"); } catch { /* noop */ }
  });
}

test.describe("UX visual verification", () => {
  test("1. landing desktop", async ({ page }) => {
    await dismissOnboarding(page);
    await page.goto("/", { waitUntil: "networkidle" });
    await page.screenshot({ path: path.join(OUT, "01-landing-desktop.png"), fullPage: false });
    await expect(page.locator("text=/Re:?Chord/").first()).toBeVisible();
  });

  test("2. /app desktop with key/tempo controls visible", async ({ page }) => {
    await dismissOnboarding(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/app", { waitUntil: "networkidle" });
    // Disclosure trigger uses an aria-expanded button. The label can vary
    // by locale (Key & tempo / 키와 템포), so target by role + flexible regex.
    const trigger = page.getByRole("button", { name: /key.*tempo|키.*템포/i }).first();
    if (await trigger.isVisible().catch(() => false)) {
      await trigger.click().catch(() => {});
      await page.waitForTimeout(400);
    }
    await page.screenshot({ path: path.join(OUT, "02-app-desktop.png"), fullPage: true });
  });

  test("5. chat widget open with action button", async ({ page }) => {
    await dismissOnboarding(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/app", { waitUntil: "networkidle" });
    // The chat fab — round button with aria-label that includes "chat"
    // or the speech-bubble lucide icon. Open it.
    const chatFab = page.getByRole("button", { name: /chat|챗|봇|어시스턴트/i }).first();
    if (await chatFab.isVisible().catch(() => false)) {
      await chatFab.click().catch(() => {});
      await page.waitForTimeout(400);
    }
    await page.screenshot({ path: path.join(OUT, "05-chat-widget.png"), fullPage: false });
  });

  test("3. /app mobile narrow", async ({ page }) => {
    await dismissOnboarding(page);
    await page.setViewportSize({ width: 390, height: 844 });        // iPhone 14 size
    await page.goto("/app", { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, "03-app-mobile.png"), fullPage: true });
  });

  test("4. /app with regen banner via location state", async ({ page }) => {
    await dismissOnboarding(page);
    // Inject the regenerateFrom location state on first paint by navigating
    // through history.pushState before React reads useLocation.
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => {
      window.history.replaceState(
        {
          usr: {
            regenerateFrom: {
              sourceTitle: "Reckless Love",
              options: {
                mode: "karaoke",
                semitones: 2,
                tempo_ratio: 0.95,
                format: "wav",
                sample_rate: 48000,
                bit_depth: "24",
                make_score: true,
                score_stems: ["vocals"],
                score_style: "lead_sheet",
                make_lyrics: true,
                lyrics_lang: "ko",
                voice_cues: false,
                click_track: true,
                polish: true,
              },
            },
          },
          key: "regen-test",
        },
        "",
        "/app",
      );
    });
    await page.goto("/app", { waitUntil: "networkidle" });
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, "04-app-regen-banner.png"), fullPage: true });
  });
});
