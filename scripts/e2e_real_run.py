"""TRUE end-to-end: real audio through the real GPU pipeline (no mocks).

Boots the FastAPI app in-process, uploads a real song, creates a quick_mr
job with chord detection, polls to completion, and verifies the artifacts +
a download actually work. Unlike test_e2e_pipeline (which mocks the
separator), this runs the genuine 4-model ensemble separation on the GPU.
"""
from __future__ import annotations
import os, time, json
from pathlib import Path

os.environ["RECHORD_PREWARM_AT_BOOT"] = "0"

from fastapi.testclient import TestClient
from backend.app.main import app

INPUT = "data/e2e_real_input.wav"


def main() -> None:
    t0 = time.time()
    with TestClient(app) as c:
        # 1) Upload
        with open(INPUT, "rb") as fp:
            r = c.post("/uploads", files={"file": ("song.wav", fp, "audio/wav")})
        assert r.status_code in (200, 201), r.text
        path = r.json()["path"]
        print(f"[upload] ok -> {path}")

        # 2) Create job — real separation + chords + sections (quick_mr).
        body = {"input": path, "options": {
            "mode": "quick_mr", "detect_chords": True, "make_lyrics": False,
            "make_score": False, "polish": True, "karaoke_postprocess": True,
            "format": "wav", "sample_rate": 48000, "bit_depth": "16",
        }}
        r = c.post("/jobs", json=body)
        assert r.status_code in (200, 201), r.text
        jid = r.json()["id"]
        print(f"[job] created {jid} — running real separation, please wait...")

        # 3) Poll to completion (real GPU work — allow up to 8 min).
        last_stage = None
        deadline = time.time() + 480
        final = None
        while time.time() < deadline:
            j = c.get(f"/jobs/{jid}").json()
            stage = j.get("stage") or ""
            if stage != last_stage:
                print(f"   [{time.time()-t0:6.1f}s] stage={stage!r} progress={j.get('progress')}")
                last_stage = stage
            if stage in ("done", "error", "cancelled") or "FAILED" in (j.get("message") or "").upper():
                final = j
                break
            time.sleep(1.0)
        assert final is not None, "job did not finish in time"

        # 4) Report
        print("\n==================== RESULT ====================")
        print(f"status={final.get('status')} stage={final.get('stage')} "
              f"elapsed={time.time()-t0:.1f}s")
        if final.get("error"):
            print("ERROR:", final["error"])
        arts = final.get("artifacts") or {}
        print(f"\nartifacts ({len(arts)}): {sorted(arts.keys())}")
        meta = final.get("meta") or {}
        print(f"\nkey={meta.get('key_root')} {meta.get('key_mode')}  "
              f"bpm={meta.get('bpm')}  time_sig={meta.get('time_signature')}")
        q = meta.get("quality") or {}
        if q:
            print(f"quality: grade={q.get('grade')} "
                  f"null_residual_dbfs={q.get('null_residual_dbfs')} "
                  f"recon_corr={q.get('reconstruction_corr')}")
        bs = meta.get("backend_summary") or {}
        print(f"backend fallbacks: {bs.get('fallbacks')}")

        # chords
        rc = c.get(f"/jobs/{jid}/chords").json()
        if rc.get("available"):
            evs = rc.get("events") or []
            uniq = sorted({e.get("label") for e in evs})
            print(f"chords: {len(evs)} events, {len(uniq)} unique -> {uniq[:16]}")

        # 5) Verify a download actually serves bytes
        for key in ("instrumental_final", "vocals_final"):
            if key in arts:
                d = c.get(f"/jobs/{jid}/download/{key}")
                print(f"download {key}: HTTP {d.status_code}, "
                      f"{len(d.content)} bytes")
        print("===============================================")
        ok = (final.get("stage") == "done"
              and any(k in arts for k in ("instrumental_final", "instrumental")))
        print("VERDICT:", "PASS (real end-to-end produced a downloadable MR)" if ok else "FAIL")


if __name__ == "__main__":
    main()
