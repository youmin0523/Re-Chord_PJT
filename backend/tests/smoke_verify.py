"""Cross-cutting verification of all D1–D12 features in one run.

Validates that every artifact + API surface still works after the AUX cues +
LyricsEditor + Polish + score restyle + ATM brand refactor.
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
        # --- /formats and /health sanity ---
        h = (await c.get("/health")).json()
        assert h.get("status") == "ok", h
        print("[/health] OK", h)

        f = (await c.get("/formats")).json()
        assert len(f.get("models", [])) >= 6, "fewer models than expected"
        print(f"[/formats] models={len(f['models'])} modes={[m['id'] for m in f['modes']]}")

        # --- upload + create karaoke job with everything ON ---
        with FIXTURE.open("rb") as fp:
            up = (await c.post("/uploads", files={"file": (FIXTURE.name, fp, "audio/wav")})).json()
        print(f"[/uploads] {up['filename']}  {up['audio_codec']} {up['sample_rate']}Hz")

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
                "score_style": "lead_sheet",
                "make_lyrics": True,
                "lyrics_lang": "auto",
                "lyrics_model": "small",
                "detect_chords": True,
                "format": "wav",
                "sample_rate": 48000,
                "bit_depth": "24",
            },
        }
        r = await c.post("/jobs", json=body)
        r.raise_for_status()
        jid = r.json()["id"]
        print(f"[/jobs POST] {jid}")

        # --- poll until done ---
        t0 = time.time()
        last_stage = None
        while time.time() - t0 < 300:
            await asyncio.sleep(2)
            j = (await c.get(f"/jobs/{jid}")).json()
            if j["stage"] != last_stage:
                print(f"  [{time.time()-t0:6.2f}s] {j['stage']:9} {int(j['progress']*100):3d}%  {j['message']}")
                last_stage = j["stage"]
            if j["status"] in ("done", "error"):
                break
        print(f"[final] status={j['status']}")
        if j["status"] != "done":
            print(" ERROR:", j.get("error"))
            return 1

        meta = j["meta"]
        arts = j["artifacts"]
        print(f"\n[meta] grade={meta.get('quality_grade')} "
              f"null={meta.get('quality_null_rms_dbfs'):.1f}dB "
              f"recon={meta.get('quality_recon_corr'):.3f} "
              f"polish={meta.get('polish_used')} title={meta.get('source_title')!r}")
        print(f"[artifacts] {len(arts)} keys")

        # --- expectation list (the union of every feature switch) ---
        expected = {
            "source", "master",
            "instrumental", "vocals",
            "instrumental_final", "vocals_final",
            "quality_json",
            "monitor_track", "click_track", "sections_json",
            "lyrics_json", "chords_json",
            "score_vocals_midi", "score_vocals_musicxml", "score_vocals_pdf",
        }
        missing = expected - set(arts)
        if missing:
            print(f"[FAIL] missing artifacts: {sorted(missing)}")
            return 1

        # --- secondary API checks ---
        # Sections
        s = (await c.get(f"/jobs/{jid}/sections")).json()
        assert s.get("available"), "sections endpoint not available"
        print(f"[/sections] bpm={s.get('bpm')} sections={len(s.get('sections') or [])}")

        # Chords
        ch = (await c.get(f"/jobs/{jid}/chords")).json()
        assert ch.get("available"), "chords endpoint not available"
        print(f"[/chords] {len(ch.get('events') or [])} events")

        # Lyrics GET
        ly = (await c.get(f"/jobs/{jid}/lyrics")).json()
        if ly.get("available"):
            print(f"[/lyrics GET] lang={ly.get('language')} words={len(ly.get('words') or [])}")
        else:
            print("[/lyrics GET] no lyrics (sine has no real vocal)")

        # Lyrics PUT (force a rebuild with one edited word)
        ly_put = await c.put(f"/jobs/{jid}/lyrics", json={
            "words": [{"word": "test", "start_sec": 0.0, "end_sec": 1.0,
                       "confidence": 1.0, "verse": 1}],
            "rebuild_score": True,
        })
        ly_put.raise_for_status()
        print(f"[/lyrics PUT] {ly_put.json()}")

        # AUX cues PUT
        cu = await c.put(f"/jobs/{jid}/aux_cues", json={
            "cues": [
                {"start_measure": 1, "end_measure": 4, "patch": "organ", "note": "intro"},
                {"start_measure": 5, "end_measure": 8, "patch": "pad", "note": "warm"},
            ],
            "rebuild_score": True,
        })
        cu.raise_for_status()
        cu_res = cu.json()
        print(f"[/aux_cues PUT] {cu_res}")

        # AUX cues GET
        gc = (await c.get(f"/jobs/{jid}/aux_cues")).json()
        assert gc.get("available"), "aux_cues GET not available"
        print(f"[/aux_cues GET] {len(gc.get('cues') or [])} cues")

        # Loop
        lp = await c.post(f"/jobs/{jid}/loop", json={
            "source": "instrumental_final",
            "start_sec": 5.0, "end_sec": 10.0,
            "repeats": 2, "with_countin": False,
        })
        lp.raise_for_status()
        lp_res = lp.json()
        print(f"[/loop] dur={lp_res['duration_sec']}s artifact={lp_res['artifact']}")
        assert abs(lp_res["duration_sec"] - 10.0) < 0.05

        # Slowdown
        sd = await c.post(f"/jobs/{jid}/slowdown", json={
            "source": "instrumental_final",
            "tempo_ratio": 0.75,
            "stem_kind": "instrumental",
        })
        sd.raise_for_status()
        sd_res = sd.json()
        print(f"[/slowdown] engine={sd_res.get('engine')} elapsed={sd_res.get('elapsed_sec')}")

        # Download an artifact
        dl = await c.get(f"/jobs/{jid}/download/instrumental_final")
        assert dl.status_code == 200, dl.text
        print(f"[/download/instrumental_final] {len(dl.content)} bytes")

        print("\n[OK] all features pass cross-cutting verification")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
