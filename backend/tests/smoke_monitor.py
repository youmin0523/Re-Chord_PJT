"""E2E: voice cues + click track + monitor mixdown on a real song stem.

Uses the existing 6-min YouTube vocals/instrumental we already separated so
this doesn't have to re-run separation. Submits a "decode only" job-like
flow by feeding the master wav directly via the CLI-friendly endpoints.

Strategy here: we already have a finished job (job_id 262e22be9492) in the
DB-less in-memory registry of a *previous* server run, but since registry
is in-process and we just restarted, we run a small new karaoke job on the
short 30s fixture with voice_cues + click + monitor turned on.
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
                "voice_cues": True,
                "voice_cue_lang": "ko",
                "click_track": True,
                "monitor_track": True,
                "make_score": False,
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
        while time.time() - t0 < 240:
            await asyncio.sleep(2)
            r = await c.get(f"/jobs/{jid}")
            j = r.json()
            print(f"  [{time.time() - t0:6.2f}s] stage={j['stage']:9} "
                  f"progress={j['progress'] * 100:5.1f}%  msg={j['message']}")
            if j["status"] in ("done", "error"):
                break

        print()
        print("final status:", j["status"])
        if j.get("error"):
            print("ERROR:", j["error"])
        print("artifacts:")
        for k, v in sorted(j["artifacts"].items()):
            print(f"  {k:24} -> {Path(v).name}  exists={Path(v).exists()}")

        wanted = {"click_track", "monitor_track", "sections_json"}
        present = wanted & set(j["artifacts"].keys())
        missing = wanted - present
        print(f"\nExpected D9 artifacts present: {sorted(present)}")
        if missing:
            print(f"[FAIL] missing: {sorted(missing)}")
            return 1
        print("[OK] D9 smoke test passed")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
