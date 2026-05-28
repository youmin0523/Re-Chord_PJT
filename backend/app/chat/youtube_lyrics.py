"""Fetch verified Korean worship lyrics from YouTube.

User insight (2026-05-21): worship teams (마커스 / 어노인팅 / 제이어스 /
위러브 / 예람 etc.) routinely publish the official Korean lyrics either:

  * in the video **description** (가장 흔함 — "가사" 또는 "Lyrics" 섹션)
  * as Closed Captions / subtitles (자동 또는 수동, 워시 곡은 보통 수동)

Both channels are far more reliable than generic search hits because the
team itself authored the text. This module wraps yt-dlp's metadata +
subtitle extraction so the chat tool can pull verified lyrics on demand
without forcing the user to copy-paste from YouTube.

API:
    fetch_youtube_lyrics(query, top_n=3) -> list[YouTubeLyricsHit]
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class YouTubeLyricsHit:
    video_id: str
    title: str
    channel: str
    duration_sec: int
    url: str
    description_lyrics: list[str]    # candidate lyric lines from description
    subtitle_lyrics: list[str]       # lines pulled from CC (ko if available)
    confidence: float                # 0..1 heuristic — how worship-shaped
    source_tag: str                  # "description" | "subtitle" | "both"


# Lines that look like Korean worship lyric (broadly: contain at least one
# Hangul block of length ≥ 2 and aren't URLs / boilerplate). We keep this
# lax and let the chatbot/user filter further.
_HANGUL_RE = re.compile(r"[가-힣]{2,}")
_URL_RE = re.compile(r"https?://|www\.")
_BOILERPLATE = (
    "구독", "좋아요", "알림", "공유", "댓글", "subscribe", "channel",
    "follow", "instagram", "facebook", "twitter", "cafe", "blog",
    "copyright", "all rights reserved", "ccli", "음원 출처", "©",
)
_LYRIC_HINT = (
    "주", "하나님", "예수", "성령", "할렐루야", "아멘", "은혜", "사랑",
    "영광", "주님", "찬양", "거룩", "노래", "복음", "축복",
)


def _looks_like_lyric_line(line: str) -> bool:
    line = line.strip()
    if not line or len(line) < 3 or len(line) > 80:
        return False
    if _URL_RE.search(line):
        return False
    lower = line.lower()
    if any(b in lower for b in _BOILERPLATE):
        return False
    if not _HANGUL_RE.search(line):
        return False
    return True


def _score_lyric_block(lines: list[str]) -> float:
    """Heuristic: how worship-shaped is this block? Drives confidence."""
    if not lines:
        return 0.0
    hangul = sum(1 for ln in lines if _HANGUL_RE.search(ln))
    hint_hits = sum(1 for ln in lines for w in _LYRIC_HINT if w in ln)
    avg_len = sum(len(ln) for ln in lines) / len(lines)
    # Worship lyric blocks: many short Hangul lines with worship vocabulary.
    base = min(1.0, hangul / max(1, len(lines)))
    hint_factor = min(1.0, hint_hits / max(1, len(lines)))
    length_factor = 1.0 if 6 <= avg_len <= 40 else 0.5
    return round(0.5 * base + 0.3 * hint_factor + 0.2 * length_factor, 3)


def _extract_lyric_lines_from_description(desc: str) -> list[str]:
    """Pull candidate lyric lines from a video description.

    Most worship channels structure descriptions as:
        곡 정보 / 가사 / 사역자 / 출처
    We don't try to parse sections — we just keep every line that looks
    like a Korean lyric line (heuristic above).
    """
    if not desc:
        return []
    lines = [ln.strip() for ln in desc.splitlines()]
    return [ln for ln in lines if _looks_like_lyric_line(ln)]


def _parse_vtt(vtt_text: str) -> list[str]:
    """Pull caption text from a .vtt file, dedupe consecutive lines."""
    out: list[str] = []
    prev: str | None = None
    for raw in vtt_text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            continue
        if "-->" in line:
            continue
        # Strip inline tags like <c.colorE5E5E5> etc.
        cleaned = re.sub(r"<[^>]+>", "", line).strip()
        if not cleaned or cleaned == prev:
            continue
        if _looks_like_lyric_line(cleaned):
            out.append(cleaned)
            prev = cleaned
    return out


def _run_ytdlp(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    cmd = [sys.executable, "-m", "yt_dlp"] + args
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def fetch_youtube_lyrics(
    query: str,
    top_n: int = 3,
    fetch_subtitles: bool = True,
) -> list[YouTubeLyricsHit]:
    """Search YouTube for ``query`` and return lyric candidates per hit.

    Args:
        query: free-form text. Worship-team-style queries work best
            (e.g. "Way Maker 마커스 워시 한국어 가사").
        top_n: clamp to 1..5; 3 is a good speed/precision trade.
        fetch_subtitles: when True, also download Korean CC tracks.
            Set False for a faster description-only path.
    """
    top_n = max(1, min(int(top_n), 5))
    # 1) Search → get per-video metadata JSON (no download).
    rc, stdout, stderr = _run_ytdlp(
        [
            "--no-warnings", "--no-playlist", "--skip-download",
            "--dump-single-json",
            "--flat-playlist",
            f"ytsearch{top_n}:{query}",
        ],
        timeout=60,
    )
    if rc != 0:
        return []
    try:
        roots = json.loads(stdout)
    except Exception:
        return []

    entries = roots.get("entries") or [roots]
    hits: list[YouTubeLyricsHit] = []

    for ent in entries[:top_n]:
        vid = ent.get("id") or ent.get("url")
        if not vid:
            continue
        if not vid.startswith("http"):
            vurl = f"https://www.youtube.com/watch?v={vid}"
        else:
            vurl = vid

        # 2) Per-video full metadata (description + sub list) — separate
        #    call so a single bad video doesn't kill the whole batch.
        rc2, out2, _ = _run_ytdlp(
            ["--no-warnings", "--skip-download", "--dump-single-json", vurl],
            timeout=45,
        )
        if rc2 != 0 or not out2.strip():
            continue
        try:
            meta = json.loads(out2)
        except Exception:
            continue

        desc_lyrics = _extract_lyric_lines_from_description(
            meta.get("description") or ""
        )

        sub_lyrics: list[str] = []
        if fetch_subtitles:
            with tempfile.TemporaryDirectory() as td:
                tdp = Path(td)
                # Prefer manual Korean CC; fall back to auto-generated KO.
                _run_ytdlp(
                    ["--no-warnings", "--skip-download",
                     "--write-subs", "--write-auto-subs",
                     "--sub-langs", "ko,ko-KR",
                     "--sub-format", "vtt",
                     "-o", str(tdp / "%(id)s.%(ext)s"),
                     vurl],
                    timeout=60,
                )
                for vtt in tdp.glob("*.vtt"):
                    try:
                        text = vtt.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    sub_lyrics.extend(_parse_vtt(text))
                    if len(sub_lyrics) > 200:
                        break
            # Dedupe while preserving order, cap at 200 lines.
            seen: set[str] = set()
            sub_lyrics = [ln for ln in sub_lyrics
                          if ln not in seen and not seen.add(ln)][:200]

        if not (desc_lyrics or sub_lyrics):
            continue

        if desc_lyrics and sub_lyrics:
            tag = "both"
        elif desc_lyrics:
            tag = "description"
        else:
            tag = "subtitle"

        score = max(_score_lyric_block(desc_lyrics),
                    _score_lyric_block(sub_lyrics))

        hits.append(YouTubeLyricsHit(
            video_id=meta.get("id", ""),
            title=meta.get("title", ""),
            channel=meta.get("channel") or meta.get("uploader") or "",
            duration_sec=int(meta.get("duration") or 0),
            url=vurl,
            description_lyrics=desc_lyrics[:60],
            subtitle_lyrics=sub_lyrics[:60],
            confidence=score,
            source_tag=tag,
        ))

    hits.sort(key=lambda h: -h.confidence)
    return hits


def hits_to_prompt_block(hits: list[YouTubeLyricsHit]) -> str:
    """Render hits into a system-prompt block the chatbot can quote from."""
    if not hits:
        return ""
    lines: list[str] = [
        "[YouTube 검색 결과 — 워시팀이 직접 영상에 표기한 가사입니다. "
        "곡명과 채널이 사용자 요청과 일치하면 아래 라인을 그대로 인용하세요. "
        "임의로 가사를 추가하거나 다른 표현으로 바꾸지 마세요.]",
    ]
    for h in hits:
        lines.append(f"\n* {h.title} — {h.channel}  ({h.url})")
        lines.append(f"  source={h.source_tag}, confidence={h.confidence:.2f}")
        if h.description_lyrics:
            lines.append("  [description lyrics]")
            for ln in h.description_lyrics[:12]:
                lines.append(f"    | {ln}")
        if h.subtitle_lyrics:
            lines.append("  [CC/subtitle lyrics]")
            for ln in h.subtitle_lyrics[:12]:
                lines.append(f"    | {ln}")
    return "\n".join(lines)


__all__ = [
    "YouTubeLyricsHit",
    "fetch_youtube_lyrics",
    "hits_to_prompt_block",
]
