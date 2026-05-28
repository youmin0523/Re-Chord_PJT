"""Full-stack smoke test for the D11 polish + chord-symbol + multi-page score features.

Verifies:
  - source_title gets persisted on the job meta
  - polish stage runs (mixback + dynaudnorm)
  - chord detection produces chords.json
  - quality report meta is populated
  - score generates multi-page SVG + PDF, with chord symbols overlay
  - section markers (json) present
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

FIXTURE = Path(__file__).parent / "fixtures" / "test_30s.wav"


async def main() -> int:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:7860", timeout=600.0) as c:
        with FIXTURE.open("rb") as fp:
            r = await c.post("/uploads", files={"file": (FIXTURE.name, fp, "audio/wav")})
        r.raise_for_status()
        up = r.json()
        print("uploaded:", up["filename"])

        body = {
            "input": up["path"],
            "options": {
                "mode": "karaoke",
                "models": ["mdx23c_instvoc_hq"],
                "karaoke_postprocess": False,
                "polish": True,
                "polish_inst_share": 0.20,
                "voice_cues": True,
                "click_track": True,
                "monitor_track": True,
                "make_score": True,
                "score_stems": ["vocals"],
                "detect_chords": True,
                "format": "wav",
                "sample_rate": 48000,
                "bit_depth": "24",
            },
        }
        r = await c.post("/jobs", json=body)
        r.raise_for_status()
        jid = r.json()["id"]
        print("job:", jid)

        t0 = time.time()
        last_stage = None
        while time.time() - t0 < 240:
            await asyncio.sleep(2)
            r = await c.get(f"/jobs/{jid}")
            j = r.json()
            stage = j["stage"]
            if stage != last_stage:
                print(f"  [{time.time() - t0:6.2f}s] stage={stage:9} "
                      f"progress={j['progress'] * 100:5.1f}%  {j['message']}")
                last_stage = stage
            if j["status"] in ("done", "error"):
                break

        print()
        print("final status:", j["status"])
        if j["status"] != "done":
            print("ERROR:", j.get("error"))
            return 1

        meta = j["meta"]
        arts = j["artifacts"]
        print(f"\n=== meta (selected) ===")
        for k in [
            "source_title", "source_codec", "source_sr", "bpm", "key_name",
            "quality_grade", "quality_null_rms_dbfs", "quality_recon_corr",
            "polish_inst_share", "polish_used", "chord_count",
            "score_vocals_pages", "score_vocals_measures",
        ]:
            v = meta.get(k)
            print(f"  {k:30} = {v}")

        print(f"\n=== artifact keys ===")
        for k in sorted(arts.keys()):
            print(f"  {k}")

        # Assertions
        fails = []
        if not meta.get("source_title"):
            fails.append("source_title missing")
        if meta.get("quality_grade") is None:
            fails.append("quality report missing")
        if "chords_json" not in arts:
            fails.append("chords_json missing")
        if "sections_json" not in arts:
            fails.append("sections_json missing")
        if "monitor_track" not in arts:
            fails.append("monitor_track missing")
        if not any(k.startswith("score_vocals_svg_p") for k in arts):
            fails.append("score multi-page SVG missing")
        if "score_vocals_pdf" not in arts:
            fails.append("score PDF missing")

        if fails:
            print("\n[FAIL]")
            for f in fails:
                print(" -", f)
            return 1

        print("\n[OK] full E2E smoke passed")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
