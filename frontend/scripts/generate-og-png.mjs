/**
 * Convert the brand SVG OG image into a 1200×630 PNG that Facebook,
 * Twitter/X, KakaoTalk and Slack all render reliably.
 *
 * Run from frontend/:
 *   node scripts/generate-og-png.mjs
 *
 * Also emits 192×192 and 512×512 PWA icons from the same source so the
 * manifest's maskable icons aren't 404s.
 *
 * Deps:
 *   - `sharp` (auto-installed on first run via npm ci, listed in
 *     package.json devDependencies)
 */

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";


const here = fileURLToPath(new URL(".", import.meta.url));
const root = resolve(here, "..");
const publicDir = resolve(root, "public");

const targets = [
  { src: "og-image.svg",   dst: "og-image.png",        w: 1200, h: 630 },
  { src: "favicon.svg",    dst: "apple-touch-icon.png", w: 180,  h: 180 },
  { src: "favicon.svg",    dst: "icon-192.png",         w: 192,  h: 192 },
  { src: "favicon.svg",    dst: "icon-512.png",         w: 512,  h: 512 },
];

let sharp;
try {
  sharp = (await import("sharp")).default;
} catch {
  console.error(
    "  ! `sharp` not installed. Run: npm i -D sharp\n" +
    "    (Skipping PNG export; existing PNGs (if any) are kept.)",
  );
  process.exit(0);
}

for (const t of targets) {
  const srcPath = resolve(publicDir, t.src);
  const dstPath = resolve(publicDir, t.dst);
  if (!existsSync(srcPath)) {
    console.warn(`  ? missing ${t.src}, skipping`);
    continue;
  }
  try {
    const svg = readFileSync(srcPath);
    await sharp(svg, { density: 300 })
      .resize(t.w, t.h, { fit: "contain", background: { r: 10, g: 10, b: 22, alpha: 1 } })
      .png({ compressionLevel: 9 })
      .toFile(dstPath);
    console.log(`  ✓ ${t.dst} (${t.w}×${t.h})`);
  } catch (e) {
    console.error(`  ! ${t.dst}: ${e.message}`);
  }
}
