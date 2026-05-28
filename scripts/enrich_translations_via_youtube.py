"""Auto-enrich music_songs.json translations using YouTube description + CC.

For every Korean version with ``needs_verification: true`` AND empty
``lyrics_lines``, we:

  1. Query YouTube for "<primary_title> <translator_team> 가사".
  2. Pull the top hit's description + Korean subtitles.
  3. Extract candidate lyric lines and stash them in a *staging* file —
     `backend/data/seed/music_songs.youtube_enrichment.json` — for the
     user to review before promoting any line into `music_songs.json`.

We deliberately do NOT auto-promote into the main seed file. Worship
lyrics are sensitive (worship-team copyright + theological language) and
the chatbot is what reads music_songs.json at runtime; if a line is
hallucinated by YouTube auto-CC the chatbot would happily quote it as
verified. The staging file makes the human review step explicit.

Run::

    python scripts/enrich_translations_via_youtube.py
    python scripts/enrich_translations_via_youtube.py --only way-maker
    python scripts/enrich_translations_via_youtube.py --limit 5   # smoke
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED = PROJECT_ROOT / "backend" / "data" / "seed" / "music_songs.json"
STAGING = PROJECT_ROOT / "backend" / "data" / "seed" / "music_songs.youtube_enrichment.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(p: Path, d: dict) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="restrict to these song ids")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap how many entries to process (0 = all)")
    ap.add_argument("--include-verified", action="store_true",
                    help="also revisit translations marked verified")
    ap.add_argument("--no-subs", action="store_true",
                    help="skip CC download (faster, description-only)")
    args = ap.parse_args()

    seed = _load(SEED)
    songs = seed.get("songs", [])
    if not songs:
        print("[fatal] no songs in seed file", file=sys.stderr); return 1

    # Lazy import — youtube_lyrics pulls yt-dlp.
    sys.path.insert(0, str(PROJECT_ROOT))
    from backend.app.chat.youtube_lyrics import fetch_youtube_lyrics  # type: ignore

    staging = _load(STAGING) or {"schema": "rechord.music_songs.youtube_enrichment.v1",
                                 "generated_at": "", "songs": {}}
    processed = 0

    for song in songs:
        sid = song["id"]
        if args.only and sid not in args.only:
            continue
        title = song.get("primary_title") or sid
        per_song = staging["songs"].setdefault(sid, {"primary_title": title,
                                                     "translations": {}})

        for kv in song.get("korean_versions", []):
            team = (kv.get("translator_team") or "").strip()
            needs = kv.get("needs_verification", True)
            has_lines = bool(kv.get("lyrics_lines"))
            if has_lines and not args.include_verified:
                continue
            if not needs and not args.include_verified:
                continue
            if not team:
                continue

            slot = per_song["translations"].setdefault(team, {})
            if slot.get("fetched_ok"):
                continue   # already done in a previous run

            q = f"{title} {team} 가사"
            print(f"\n[{sid}] {team} — query: {q}")
            try:
                hits = fetch_youtube_lyrics(
                    q, top_n=3, fetch_subtitles=not args.no_subs,
                )
            except Exception as e:
                print(f"  ! fetch failed: {e}")
                slot.update({"fetched_ok": False, "error": str(e)[:200]})
                continue

            if not hits:
                slot.update({"fetched_ok": False, "error": "no hits"})
                print("  ! no hits")
                continue

            best = hits[0]
            slot.update({
                "fetched_ok": True,
                "best_hit": {
                    "url": best.url,
                    "title": best.title,
                    "channel": best.channel,
                    "source_tag": best.source_tag,
                    "confidence": best.confidence,
                    "description_lyrics": best.description_lyrics,
                    "subtitle_lyrics": best.subtitle_lyrics,
                },
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            print(f"  ✓ best: {best.channel} ({best.source_tag}, conf={best.confidence:.2f})")
            print(f"    desc lines: {len(best.description_lyrics)}  "
                  f"sub lines: {len(best.subtitle_lyrics)}")

            processed += 1
            staging["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save(STAGING, staging)
            if args.limit and processed >= args.limit:
                print(f"\n[stop] limit {args.limit} reached")
                _save(STAGING, staging)
                return 0

    staging["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(STAGING, staging)
    print(f"\n[done] processed={processed}")
    print(f"staged: {STAGING}")
    print("Review the staging file, then merge promising lines into "
          "music_songs.json's lyrics_lines (and flip needs_verification "
          "to false) by hand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
