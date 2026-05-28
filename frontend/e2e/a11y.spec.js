import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Accessibility gate.
 *
 * Runs axe-core on the pages a first-time user actually lands on, before
 * any backend interaction is required:
 *   /          → Landing
 *   /app       → Home (mode picker + upload)
 *
 * We deliberately ignore rules that need real fixtures we can't load in
 * CI (no backend, no audio); the page-shell semantics still get audited.
 *
 * Fails the job on any "serious" or "critical" violation. Moderate/minor
 * findings are reported but do not gate — tighten the threshold once the
 * known issues are cleared.
 */

const PAGES = [
  { name: "landing", path: "/" },
  { name: "home", path: "/app" },
];

const SEVERITY_GATE = new Set(["serious", "critical"]);

for (const { name, path } of PAGES) {
  test(`a11y · ${name}`, async ({ page }) => {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    // Wait for React to mount the shell.
    await page.waitForSelector("#root *", { timeout: 10_000 });

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const blocking = results.violations.filter((v) => SEVERITY_GATE.has(v.impact ?? ""));

    if (blocking.length) {
      const summary = blocking
        .map((v) => `  [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node${v.nodes.length === 1 ? "" : "s"})`)
        .join("\n");
      console.error(`axe found blocking issues on ${path}:\n${summary}`);
    }
    if (results.violations.length) {
      console.warn(
        `axe found ${results.violations.length} total issue${results.violations.length === 1 ? "" : "s"} on ${path} ` +
          `(${blocking.length} blocking)`
      );
    }

    expect(blocking, `Blocking a11y violations on ${path}`).toEqual([]);
  });
}
