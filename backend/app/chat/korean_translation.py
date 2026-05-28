"""Korean translation orchestration (M4).

When the user asks about a song's Korean lyrics or asks for a Korean
translation, this module:

  1. Detects the intent via simple keyword heuristics (KO + EN).
  2. Surfaces every translator-team version we already have in the seed DB
     across the top search hits, so the model lists them all with team
     labels instead of guessing.
  3. Reminds the model to use the syllable / scripture-vocabulary rules
     from prompts.py when no verified translation is on file, and to wrap
     the AI-generated translation in ``<ai-trans>`` so the bubble UI
     renders the "AI 참고용 · 공식 번안 아님" warning.

We deliberately keep this layer "system-prompt only" — the LLM still
produces the text, we just hand it the right scaffolding.
"""

from __future__ import annotations

from .music_db import HymnRecord, SearchHit, SongRecord


_INTENT_PATTERNS_KO = (
    "한국어 번안", "한국어 가사", "한국어 버전",
    "번안 가사", "한글 가사", "한글 번안",
    "번역해", "번역해줘", "한글로",
    "번역", "번안",
)
_INTENT_PATTERNS_EN = (
    "korean version", "korean lyrics", "korean translation",
    "translate to korean", "in korean",
)

# "Show me the whole lyrics" overrides the default 8-line snippet policy.
_FULL_LYRICS_PATTERNS_KO = (
    "전체 가사", "가사 전체", "끝까지", "전부",
    "다 보여줘", "모든 가사", "처음부터 끝까지",
)
_FULL_LYRICS_PATTERNS_EN = (
    "full lyrics", "complete lyrics", "all the lyrics",
    "entire lyrics", "whole lyrics", "completely",
)


def detect_translation_intent(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if any(p in lower for p in _INTENT_PATTERNS_EN):
        return True
    if any(p in text for p in _INTENT_PATTERNS_KO):
        return True
    return False


def detect_full_lyrics_request(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if any(p in lower for p in _FULL_LYRICS_PATTERNS_EN):
        return True
    if any(p in text for p in _FULL_LYRICS_PATTERNS_KO):
        return True
    return False


def build_korean_versions_block(
    hits: list[SearchHit],
    *,
    locale: str = "ko",
) -> str:
    """Render every korean_versions[] entry from the matched songs into
    a structured block the system prompt can use.

    Returns empty string when no matched song carries Korean versions.
    """
    if not hits:
        return ""
    pairs: list[tuple[SongRecord, list]] = []
    for h in hits:
        if isinstance(h.record, SongRecord) and h.record.korean_versions:
            pairs.append((h.record, h.record.korean_versions))
    if not pairs:
        return ""

    if locale == "en":
        header = (
            "Korean translation context — the user is asking about Korean lyrics.\n"
            "Surface every translator-team version present in the seed DB below. "
            "When an entry is marked `needs_verification` and has no lyric lines, "
            "tell the user no verified translation is on file. If the user still "
            "wants one, generate a fresh translation inside an <ai-trans> block "
            "following the syllable count / sacred-vocabulary / accent-alignment "
            "rules from the persona, and append \"AI 참고용 · 공식 번안 아님\"."
        )
    else:
        header = (
            "한국어 번안 안내 — 사용자가 한국어 번안/가사를 요청한 것으로 감지됨.\n"
            "아래는 시드 DB에 등록된 모든 번안 버전입니다. 번안팀 이름과 함께 모두 "
            "나열하세요. needs_verification 표시된 항목은 가사 라인이 비어 있습니다 — "
            "이 경우 \"공식 출처가 등록되어 있지 않아 검증된 번안 가사가 없다\"고 "
            "안내하세요. 사용자가 그래도 번안을 원하면 페르소나의 음절·성경 어휘·"
            "강세·인칭 규칙을 따라 새 번안을 만들고 <ai-trans>...</ai-trans> 블록 "
            "안에 출력하세요. 블록 직후 \"AI 참고용 · 공식 번안 아님\"을 반드시 명시."
        )
    lines: list[str] = [header, ""]
    for record, versions in pairs:
        lines.append(f"## {record.primary_title} — {record.artist}")
        if record.year:
            lines.append(f"(원곡 발표: {record.year})")
        for kv in versions:
            tag = " ⚠ needs_verification" if kv.needs_verification else " ✓ verified"
            lines.append(f"- 번안팀: {kv.translator_team}{tag}")
            lines.append(f"  · 한국어 제목: {kv.title_ko}")
            kv_lines = kv.all_lines()
            if kv_lines:
                for ln in kv_lines[:8]:
                    lines.append(f"  · 가사: {ln}")
            else:
                lines.append("  · 가사: (시드 DB 미수록, AI 새 번안 생성 시 <ai-trans> 사용)")
            if kv.url:
                lines.append(f"  · 출처: {kv.url}")
        lines.append("")
    return "\n".join(lines).strip()


def build_full_lyrics_block(
    hits: list[SearchHit],
    *,
    locale: str = "ko",
    max_chars_per_song: int = 4000,
) -> str:
    """When the user explicitly asks for the full lyrics, surface every
    ``lyrics_full`` field available across the top matches.

    Per the seed-curation policy, ``lyrics_full`` is only populated for
    public-domain or licensed songs (mostly hymns). For copyrighted
    contemporary worship songs the field stays ``None`` and we point the
    user at the official source URL instead.

    Returns "" when none of the hits have lyrics_full populated.
    """
    if not hits:
        return ""
    payloads: list[tuple[str, str]] = []     # (header, body)
    for h in hits:
        r = h.record
        title: str
        sections: list[tuple[str, str]] = []  # (label, body)
        if isinstance(r, SongRecord):
            title = f"{r.primary_title}" + (f" — {r.artist}" if r.artist else "")
            if r.original_lyrics_full:
                sections.append(("원곡 가사", r.original_lyrics_full))
            for kv in r.korean_versions:
                if kv.lyrics_full:
                    sections.append((f"한국어 번안 [{kv.translator_team}]", kv.lyrics_full))
        elif isinstance(r, HymnRecord):
            edition_label = {
                "new_2006": "21세기찬송가",
                "unified_1981": "통일찬송가",
            }.get(r.hymnal_edition, r.hymnal_edition)
            title = f"{edition_label} {r.hymn_number}장 {r.title_ko}"
            if r.title_en:
                title += f" / {r.title_en}"
            if r.lyrics_full_ko:
                sections.append(("한국어 전체 가사", r.lyrics_full_ko))
            if r.lyrics_full_en:
                sections.append(("English full lyrics", r.lyrics_full_en))
        else:
            continue
        if not sections:
            continue
        body_parts = []
        for label, body in sections:
            trimmed = body if len(body) <= max_chars_per_song else (body[:max_chars_per_song] + " …")
            body_parts.append(f"### {label}\n{trimmed}")
        payloads.append((title, "\n\n".join(body_parts)))

    if not payloads:
        return ""
    if locale == "en":
        header = (
            "FULL LYRICS — the user explicitly asked for the complete lyrics. "
            "Quote these verbatim, citing the song title / translator team. "
            "If a song doesn't appear below, only its lyrics_lines were on "
            "file (likely copyrighted contemporary work) — point to the "
            "official URL instead of guessing the full text."
        )
    else:
        header = (
            "전체 가사 블록 — 사용자가 명시적으로 전체 가사를 요청했습니다. "
            "곡 제목/번안팀을 함께 인용하여 아래 텍스트를 그대로 사용하세요. "
            "이 블록에 없는 곡(현대 저작권 워십)은 lyrics_lines만 시드에 "
            "있으므로 전체 가사를 추측하지 말고 공식 출처 URL을 안내하세요."
        )
    blocks = [f"## {title}\n\n{body}" for title, body in payloads]
    return header + "\n\n" + "\n\n---\n\n".join(blocks)


def build_lyrics_policy_block(*, full_lyrics: bool, locale: str = "ko") -> str:
    """Hint the model whether the user explicitly asked for the full
    lyrics (overrides the default 8-line snippet rule).
    """
    if not full_lyrics:
        return ""
    if locale == "en":
        return (
            "Full-lyrics override: the user explicitly asked for the complete "
            "lyrics. You may exceed the 8-line snippet policy for this turn. "
            "Still cite the lyricist or translator team."
        )
    return (
        "전체 가사 요청 감지: 사용자가 명시적으로 전체 가사를 요청했습니다. "
        "이번 응답에 한해 기본 8줄 스니펫 정책을 넘어서도 됩니다. "
        "단, 작사자/번안팀 출처는 반드시 함께 명시하세요."
    )


__all__ = [
    "detect_translation_intent",
    "detect_full_lyrics_request",
    "build_korean_versions_block",
    "build_full_lyrics_block",
    "build_lyrics_policy_block",
]
