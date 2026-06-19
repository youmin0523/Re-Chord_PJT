"""Live smoke test against the DEPLOYED public stack (api.youmin.site).

Unlike e2e_real_run.py (in-process), this drives the real internet path:
  curl -> Cloudflare tunnel -> local backend -> GPU -> download.
Uploads a real audio clip, runs a quick_mr job with chords, polls to done,
and downloads the MR through the public endpoint.
"""
from __future__ import annotations
import time
import httpx

BASE = "https://api.youmin.site"
INPUT = "data/datasets/fma_small/fma_small/000/000010.mp3"


def main() -> None:
    t0 = time.time()
    with httpx.Client(timeout=90, follow_redirects=True) as c:
        h = c.get(f"{BASE}/health").json()
        print(f"[health] {h.get('status')} v{h.get('version')}")

        with open(INPUT, "rb") as f:
            r = c.post(f"{BASE}/uploads", files={"file": ("song.mp3", f, "audio/mpeg")})
        r.raise_for_status()
        path = r.json()["path"]
        print(f"[upload] ok -> {path}")

        body = {"input": path, "options": {
            "mode": "quick_mr", "detect_chords": True, "make_lyrics": False,
            "make_score": False, "polish": True, "karaoke_postprocess": True,
            "format": "wav", "sample_rate": 48000, "bit_depth": "16",
        }}
        r = c.post(f"{BASE}/jobs", json=body)
        r.raise_for_status()
        jid = r.json()["id"]
        print(f"[job] {jid} — real separation on the deployed GPU, please wait...")

        last = None
        final = None
        while time.time() - t0 < 480:
            j = c.get(f"{BASE}/jobs/{jid}").json()
            st = (j.get("stage") or "")
            if st != last:
                print(f"   [{time.time()-t0:6.1f}s] stage={st!r} progress={j.get('progress')}")
                last = st
            if st in ("done", "error", "cancelled") or "FAILED" in (j.get("message") or "").upper():
                final = j
                break
            time.sleep(2)

        if final is None:
            print("TIMEOUT — job did not finish in 480s")
            return

        print("\n==================== RESULT (public stack) ====================")
        print(f"status={final.get('status')} stage={final.get('stage')} "
              f"elapsed={time.time()-t0:.1f}s")
        if final.get("error"):
            print("ERROR:", final["error"])
        arts = final.get("artifacts") or {}
        print(f"artifacts ({len(arts)}): {sorted(arts)}")
        meta = final.get("meta") or {}
        print(f"key={meta.get('key_root')} {meta.get('key_mode')}  bpm={meta.get('bpm')}")
        q = meta.get("quality") or {}
        if q:
            print(f"quality grade={q.get('grade')} null_residual={q.get('null_residual_dbfs')}")
        rc = c.get(f"{BASE}/jobs/{jid}/chords").json()
        if rc.get("available"):
            uniq = sorted({e.get("label") for e in (rc.get("events") or [])})
            print(f"chords: {len(rc.get('events') or [])} events, {len(uniq)} unique")

        for k in ("instrumental_final", "vocals_final"):
            if k in arts:
                d = c.get(f"{BASE}/jobs/{jid}/download/{k}")
                print(f"download {k}: HTTP {d.status_code}, {len(d.content)} bytes")
        ok = final.get("stage") == "done" and any(k in arts for k in ("instrumental_final", "instrumental"))
        print("VERDICT:", "PASS — deployed stack produced a downloadable MR" if ok else "FAIL")
        print("=" * 62)


if __name__ == "__main__":
    main()
