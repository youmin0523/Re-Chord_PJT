import { test, expect } from "@playwright/test";

/**
 * Live (browser) verification of the FDE-gap features WITHOUT a backend:
 * we stub the API with page.route() and seed localStorage, so a real Chromium
 * renders the actual components.
 *
 *   - Home  : ImpactCard (estimated time-saved) shows given seeded history.
 *   - Job   : the range-aware KeyControl planner + "우리 팀" range appear when
 *             the (stubbed) job meta carries vocals_low_midi/high_midi.
 */

const FAKE_JOB = {
  id: "fdetest01",
  input: "https://example.com/song.mp3",
  status: "done",
  stage: "done",
  progress: 1,
  message: "",
  error: null,
  options: { mode: "karaoke", format: "wav", sample_rate: 48000, bit_depth: 24, models: [] },
  meta: {
    source_title: "테스트 찬양곡",
    key_name: "C major", key_root: "C", key_mode: "major", key_confidence: 0.9,
    bpm: 72.0, bpm_confidence: 0.8,
    source_duration: 240,
    vocals_low_midi: 62,    // D4
    vocals_high_midi: 79,   // G5 — well above a normal team ceiling
  },
  artifacts: {},
  created_at: 1700000000,
};

async function stubApi(page) {
  await page.route("http://127.0.0.1:7860/**", async (route) => {
    const url = route.request().url();
    const json = (body) =>
      route.fulfill({ status: 200, contentType: "application/json", body });
    if (/\/jobs\/[^/]+$/.test(url)) return json(JSON.stringify(FAKE_JOB));
    if (url.includes("/setlists")) return json("[]");
    return json("{}");
  });
}

async function seedLocalStorage(page) {
  await page.addInitScript(() => {
    const now = Date.now();
    const DAY = 86400000;
    localStorage.setItem("rechord:history:v1", JSON.stringify([
      { id: "j1", title: "은혜 아니면", mode: "karaoke", createdAt: now - DAY, lastSeenAt: now },
      { id: "j2", title: "주 품에", mode: "stems", createdAt: now - 2 * DAY, lastSeenAt: now },
    ]));
    localStorage.setItem("rechord.usage.v1", JSON.stringify([
      { type: "key_recommended", at: now - 3600000 },
    ]));
    // Team range D3–A4 (50–69) — the song's G5 ceiling is far above, so the
    // recommender will suggest a downward shift.
    localStorage.setItem("rechord.teamRange.v1", JSON.stringify({ low: 50, high: 69, label: "우리 팀" }));
  });
}

test.describe("FDE-gap features (live, stubbed API)", () => {
  test.beforeEach(async ({ page }) => {
    await stubApi(page);
    await seedLocalStorage(page);
  });

  test("Home shows the estimated-impact card", async ({ page }) => {
    await page.goto("/app");
    await expect(page.locator("h1")).toContainText(/보컬|Vocal/i);
    // ImpactCard title (renders because history was seeded).
    await expect(page.getByText(/이번 달 절감/).first()).toBeVisible();
    // The hours figure + a stat chip.
    await expect(page.getByText("실측 아님 · 조정 가능한 추정치").first()).toBeVisible();
  });

  test("Job page surfaces the range-aware key planner + 우리 팀 range", async ({ page }) => {
    await page.goto("/job/fdetest01");
    // SummaryCard renders the detected key first.
    await expect(page.getByText("C major").first()).toBeVisible();
    // KeyControl range panel is now wired (melodyRange from meta).
    await expect(page.getByText("음역 체크").first()).toBeVisible();
    // The "우리 팀" chip is reachable (seeded team range), and the recommend
    // button appears because the song's range needs shifting for this team.
    await expect(page.getByRole("button", { name: "우리 팀" }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /추천 키로 맞추기/ }).first()).toBeVisible();
  });
});
