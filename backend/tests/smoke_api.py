"""End-to-end smoke test against a running FastAPI server.

Usage:
  uv run --no-sync python -m backend.tests.smoke_api
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


BASE = "http://127.0.0.1:7860"
WS_BASE = "ws://127.0.0.1:7860"
FIXTURE = Path(__file__).parent / "fixtures" / "test_30s.wav"


async def main() -> int:
    if not FIXTURE.exists():
        print(f"[FAIL] fixture missing: {FIXTURE}")
        return 1

    async with httpx.AsyncClient(base_url=BASE, timeout=300.0) as c:
        # 1) health
        r = await c.get("/health")
        assert r.status_code == 200, r.text
        print("[1/5] /health OK", r.json())

        # 2) formats
        r = await c.get("/formats")
        assert r.status_code == 200
        print("[2/5] /formats: models=",
              len(r.json()["models"]),
              "modes=", [m["id"] for m in r.json()["modes"]])

        # 3) upload
        with FIXTURE.open("rb") as fp:
            files = {"file": (FIXTURE.name, fp, "audio/wav")}
            r = await c.post("/uploads", files=files)
        assert r.status_code == 200, r.text
        upload = r.json()
        print("[3/5] /uploads OK:", upload["filename"],
              upload["audio_codec"], upload["sample_rate"], "Hz")

        # 4) create job (quick_mr, single model, no karaoke postprocess)
        body = {
            "input": upload["path"],
            "options": {
                "mode": "quick_mr",
                "models": ["mdx23c_instvoc_hq"],
                "karaoke_postprocess": False,
                "mixback": False,
                "format": "wav",
                "sample_rate": 48000,
                "bit_depth": "24",
            },
        }
        r = await c.post("/jobs", json=body)
        assert r.status_code == 200, r.text
        job = r.json()
        jid = job["id"]
        print("[4/5] /jobs created:", jid)

        # 5) stream progress over WebSocket
        events = []
        async with websockets.connect(f"{WS_BASE}/jobs/{jid}/progress") as ws:
            start = time.time()
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=180.0)
                except asyncio.TimeoutError:
                    print("[FAIL] WS timeout after 180s")
                    return 1
                ev = json.loads(msg)
                events.append(ev)
                if ev.get("type") == "ping":
                    continue
                stage = ev.get("stage", "?")
                prog = ev.get("progress", 0.0)
                msg_ = ev.get("message", "")
                print(f"  WS [{time.time() - start:6.2f}s] "
                      f"{ev['type']:8} {stage:9} {prog * 100:5.1f}%  {msg_}")
                if ev["type"] in ("done", "error"):
                    break

        # 6) fetch final job
        r = await c.get(f"/jobs/{jid}")
        assert r.status_code == 200
        final = r.json()
        print(f"[5/5] final status={final['status']} stage={final['stage']} "
              f"progress={final['progress']:.2f}")
        if final["status"] != "done":
            print("[FAIL] error:", final.get("error"))
            return 1

        for k, p in final["artifacts"].items():
            exists = Path(p).exists()
            print(f"      {k:20} -> {p}   exists={exists}")

        # 7) try a download
        r = await c.get(f"/jobs/{jid}/download/instrumental_final")
        assert r.status_code == 200
        print(f"      /download/instrumental_final -> {len(r.content)} bytes")

    print("\n[OK] smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
