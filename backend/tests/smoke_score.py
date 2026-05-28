"""End-to-end smoke test: upload + create job with make_score=True + verify score artifacts."""

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
    async with httpx.AsyncClient(base_url="http://127.0.0.1:7860", timeout=300.0) as c:
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
                "make_score": True,
                "score_stems": ["vocals"],
                "format": "wav",
                "sample_rate": 48000,
                "bit_depth": "24",
            },
        }
        r = await c.post("/jobs", json=body)
        r.raise_for_status()
        job = r.json()
        jid = job["id"]
        print("job:", jid)

        t0 = time.time()
        while time.time() - t0 < 180:
            await asyncio.sleep(2)
            r = await c.get(f"/jobs/{jid}")
            j = r.json()
            print(f"  [{time.time() - t0:6.2f}s] stage={j['stage']:9} "
                  f"progress={j['progress'] * 100:5.1f}%  msg={j['message']}")
            if j["status"] in ("done", "error"):
                break

        print()
        print("final status:", j["status"])
        print("artifacts:")
        for k, v in j["artifacts"].items():
            print(f"  {k:36} -> {Path(v).name}  exists={Path(v).exists()}")

        score_keys = [k for k in j["artifacts"] if k.startswith("score_")]
        if score_keys:
            print(f"\n[OK] score artifacts present: {score_keys}")
            return 0
        else:
            print("\n[FAIL] no score artifacts found")
            return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
