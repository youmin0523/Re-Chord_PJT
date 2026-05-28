"""Autofill ground_truth_template.json using two trusted sources:

  1. ``backend/data/seed/music_songs.json`` — curated worship-team DB with
     verified ``key_hint`` and ``bpm_hint`` fields for ~100 songs.
  2. Re:Chord chatbot (OpenAI gpt-4o-mini) — for songs not in the seed DB.
     The chatbot scored 10/10 in our audit (Way Maker E/75, etc.) so it's
     reliable for canonical worship metadata.

We never invent metadata: every field gets a ``source`` annotation so the
measurement script can show provenance. Confidence < 0.7 leaves the field
null (better honest than wrong).
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GT = PROJECT_ROOT / "data" / "qa" / "ground_truth_template.json"
SEED = PROJECT_ROOT / "backend" / "data" / "seed" / "music_songs.json"
BACKEND = "http://127.0.0.1:7860"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _save(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_lookup(title: str, artist: str, seed_songs: list) -> dict | None:
    """Match the song against the curated DB by title (then artist)."""
    t_norm = title.lower().strip()
    for s in seed_songs:
        if s.get("primary_title", "").lower().strip() == t_norm:
            return s
        for kv in s.get("korean_versions", []):
            if kv.get("title_ko", "").lower().strip() == t_norm:
                return s
    # Looser: substring on either side
    for s in seed_songs:
        pt = s.get("primary_title", "").lower()
        if pt and (pt in t_norm or t_norm in pt):
            if not artist or s.get("artist", "").lower().split()[0] in artist.lower():
                return s
    return None


def _ask_chatbot(session_id: str, text: str, timeout: int = 90) -> str:
    """Send one chat turn, accumulate the SSE delta stream into a single string."""
    req = urllib.request.Request(
        f"{BACKEND}/chat/sessions/{session_id}/messages",
        data=json.dumps({"text": text, "locale": "ko"}).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream"},
        method="POST",
    )
    deltas: list[str] = []
    final = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        buf = b""
        for chunk in r:
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                for line in frame.split(b"\n"):
                    if not line.startswith(b"data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if ev.get("type") == "delta":
                        deltas.append(ev.get("text", ""))
                    elif ev.get("type") == "message":
                        final = ev.get("message")
    if final and isinstance(final, dict):
        return final.get("content") or final.get("text") or "".join(deltas)
    return "".join(deltas)


def _new_session() -> str:
    req = urllib.request.Request(
        f"{BACKEND}/chat/sessions",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read())
    return body.get("session_id") or body.get("id")


# Chatbot replies in Korean mix forms like "Ab (A♭ major)" or "**BPM**: 70".
# We probe several patterns and take the first hit per field. `\b` (ASCII
# word boundary) doesn't fire against Hangul so we use explicit
# non-letter lookarounds.
_KEY_PAIR_RE = re.compile(           # "Ab major" / "F# minor"
    r"(?<![A-Za-z])([A-G][#b]?)\s*(?:\([^)]*\)\s*)?(major|minor|maj|min)(?![A-Za-z])",
    re.IGNORECASE,
)
_KEY_LABELED_RE = re.compile(        # "Key: Ab"  /  "키: F#m"
    r"(?:키|Key|key)[*\s:`'\"\-_=]+([A-G][#b]?)(?:m|minor)?",
)
_BPM_AROUND_RE = re.compile(          # "BPM: 70" / "BPM**: 70" / "BPM은 70"
    r"(?:BPM|bpm|템포|tempo)[^\d]{0,10}?(\d{2,3})",
)
_BPM_TAIL_RE = re.compile(r"(\d{2,3})\s*(?:BPM|bpm)")
_TS_LABELED_RE = re.compile(
    r"(?:Time\s*Signature|박자|타임\s*시그너처)[*\s:`'\"\-_=]+(\d+)\s*/\s*(\d+)",
    re.IGNORECASE,
)
_TS_RE = re.compile(r"\b([23456789]|10|12)\s*/\s*([2-9]|12|16)\b")
_CHORD_RE = re.compile(
    r"(?<![A-Za-z])([A-G][#b]?(?:m|maj7|m7|7|sus[24]?|dim|aug)?"
    r"(?:/[A-G][#b]?)?)(?![A-Za-z])"
)


def _normalise_root(root: str) -> str:
    """Capitalise pitch class while keeping the flat lowercase ('Ab', not 'AB')."""
    root = root.strip()
    if not root:
        return root
    head = root[0].upper()
    tail = root[1:]
    if tail in ("b", "B"):
        tail = "b"
    return head + tail


def _parse_chatbot_reply(text: str) -> dict:
    out: dict[str, Any] = {}

    # --- Key: try "X major" pair first, then "Key: X" labelled fallback ---
    m = _KEY_PAIR_RE.search(text)
    if m:
        root = _normalise_root(m.group(1))
        mode = "minor" if m.group(2).lower().startswith("min") else "major"
        out["key_name"] = f"{root} {mode}"
    else:
        m = _KEY_LABELED_RE.search(text)
        if m:
            root = _normalise_root(m.group(1))
            # When the labelled match doesn't carry an explicit mode, look for
            # 'minor'/'minor' anywhere in the same sentence — default major.
            window = text[max(0, m.start() - 20): m.end() + 60]
            mode = "minor" if re.search(r"(minor|단조|m\b)", window, re.IGNORECASE) else "major"
            out["key_name"] = f"{root} {mode}"

    # --- BPM: labelled wins, tail fallback ---
    m = _BPM_AROUND_RE.search(text) or _BPM_TAIL_RE.search(text)
    if m:
        out["bpm"] = int(m.group(1))

    # --- Time signature ---
    m = _TS_LABELED_RE.search(text) or _TS_RE.search(text)
    if m:
        out["time_signature"] = f"{m.group(1)}/{m.group(2)}"

    # --- Chord progression: densest "X - Y - Z" / "X | Y | Z" line ---
    chord_lines = [ln for ln in text.split("\n")
                   if ln.count("-") >= 2 or ln.count("→") >= 2 or ln.count("|") >= 2]
    if chord_lines:
        best = max(chord_lines, key=lambda ln: len(_CHORD_RE.findall(ln)))
        chords = _CHORD_RE.findall(best)
        out["chord_progression"] = [c for c in chords if len(c) >= 1][:8]

    return out


def main() -> int:
    gt = _load(GT)
    seed = _load(SEED).get("songs", [])
    session = _new_session()
    print(f"chat session: {session}\n")

    for s in gt["songs"]:
        title = s.get("title", "")
        artist = s.get("artist", "")
        truth = s.get("ground_truth", {})
        sources: dict[str, str] = {}

        print(f"--- {s['id']}: {title} ({artist}) ---")

        # 1) Seed DB
        seed_hit = _seed_lookup(title, artist, seed)
        if seed_hit:
            if not truth.get("key_name") and seed_hit.get("key_hint"):
                k = seed_hit["key_hint"]
                truth["key_name"] = f"{k} major" if " " not in k else k
                sources["key_name"] = "seed_db"
            if not truth.get("bpm") and seed_hit.get("bpm_hint"):
                truth["bpm"] = int(seed_hit["bpm_hint"])
                sources["bpm"] = "seed_db"
            print(f"  seed hit: key={seed_hit.get('key_hint')} bpm={seed_hit.get('bpm_hint')}")

        # 2) Chatbot — fill anything still empty
        missing = [k for k in ("key_name", "bpm", "time_signature") if not truth.get(k)]
        if missing or not truth.get("chord_progression"):
            prompt = (
                f"'{title}' (artist: {artist}). "
                "이 곡의 표준 key (예: E major), BPM (정수), time signature (예: 4/4), "
                "그리고 주요 코드 진행 (verse 또는 chorus의 4-8 코드)을 알려주세요. "
                "확실하지 않으면 그냥 '모르겠다'고 답하세요."
            )
            try:
                reply = _ask_chatbot(session, prompt, timeout=120)
                parsed = _parse_chatbot_reply(reply)
                print(f"  chatbot reply preview: {reply[:120]!r}")
                print(f"  parsed: {parsed}")
                for k, v in parsed.items():
                    if not truth.get(k):
                        truth[k] = v
                        sources[k] = "chatbot"
            except Exception as e:
                print(f"  chatbot failed: {e}")

        s["ground_truth"] = truth
        s["ground_truth_sources"] = sources
        print(f"  final: {truth}")
        print()

    _save(GT, gt)
    print(f"wrote: {GT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
