"""E2E for D10: create a quick_mr job, then call /loop on the finished artifact."""

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
        # 1) upload + create job
        with FIXTURE.open("rb") as fp:
            up = (await c.post("/uploads", files={"file": (FIXTURE.name, fp, "audio/wav")})).json()
        body = {
            "input": up["path"],
            "options": {
                "mode": "quick_mr",
                "models": ["mdx23c_instvoc_hq"],
                "karaoke_postprocess": False,
                "format": "wav",
                "sample_rate": 48000,
                "bit_depth": "24",
            },
        }
        r = await c.post("/jobs", json=body)
        r.raise_for_status()
        jid = r.json()["id"]
        print("job:", jid)

        # 2) poll until done
        t0 = time.time()
        while time.time() - t0 < 120:
            await asyncio.sleep(2)
            r = await c.get(f"/jobs/{jid}")
            j = r.json()
            if j["status"] in ("done", "error"):
                break
        print("status:", j["status"], "after", round(time.time() - t0, 2), "s")
        if j["status"] != "done":
            print("ERROR:", j.get("error"))
            return 1

        # 3) build a 10-12s loop, repeated 3 times, with countin off (no BPM yet).
        r = await c.post(f"/jobs/{jid}/loop", json={
            "source": "instrumental_final",
            "start_sec": 10.0,
            "end_sec": 12.0,
            "repeats": 3,
            "with_countin": False,
            "target_sr": 48000,
        })
        r.raise_for_status()
        loop = r.json()
        print("loop:")
        for k, v in loop.items():
            print(f"  {k}: {v}")
        if not Path(loop["out_path"]).exists():
            print("[FAIL] loop wav missing on disk")
            return 1

        # 4) download via /download/{artifact}
        r = await c.get(f"/jobs/{jid}/download/{loop['artifact']}")
        assert r.status_code == 200, r.text
        print(f"download OK: {len(r.content)} bytes")

        # 5) /sections on a job without D9 should return available:false (sanity).
        r = await c.get(f"/jobs/{jid}/sections")
        print("sections endpoint:", r.json())

        expected_duration = 3 * (12.0 - 10.0)
        if abs(loop["duration_sec"] - expected_duration) > 0.05:
            print(f"[FAIL] duration mismatch: {loop['duration_sec']} vs {expected_duration}")
            return 1

        print("\n[OK] D10 smoke test passed")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
