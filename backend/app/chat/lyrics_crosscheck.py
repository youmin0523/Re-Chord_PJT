"""DB ↔ YouTube lyrics cross-validation.

The seed DB is curated by humans but humans typo and worship-team
official channels routinely rewrite a single line between releases.
Trusting either source alone is unsafe. This module computes a
similarity-based agreement matrix between the two and renders a
prompt block the chatbot can use to surface discrepancies instead of
silently picking one source.

API:
    cross_check(db_kvs, yt_hits) -> CrossCheckReport
    report_to_prompt_block(report, locale='ko') -> str
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from rapidfuzz import fuzz as _rf  # type: ignore

    def _sim(a: str, b: str) -> float:
        return float(_rf.token_set_ratio(a, b)) / 100.0
except ImportError:  # graceful fallback (Python-only similarity)
    def _sim(a: str, b: str) -> float:
        a = a.strip(); b = b.strip()
        if not a or not b:
            return 0.0
        # crude shared-character ratio — good enough to flag huge gaps
        sa, sb = set(a), set(b)
        return len(sa & sb) / max(1, len(sa | sb))


# An "agreement" is a DB line that matches some YouTube line above this
# threshold. 0.70 catches paraphrases ("주 여기 운행하시네" vs
# "주 여기 임재하시네") without firing on completely different lines.
MATCH_THRESHOLD = 0.70


@dataclass
class LinePair:
    db_line: str
    yt_line: str
    similarity: float


@dataclass
class TeamCrossCheck:
    translator_team: str
    db_lines: list[str]
    yt_lines: list[str]
    agreements: list[LinePair] = field(default_factory=list)
    db_only: list[str] = field(default_factory=list)
    yt_only: list[str] = field(default_factory=list)

    @property
    def agreement_ratio(self) -> float:
        if not self.db_lines:
            return 0.0
        return len(self.agreements) / len(self.db_lines)


@dataclass
class CrossCheckReport:
    title: str
    teams: list[TeamCrossCheck] = field(default_factory=list)

    def best_team(self) -> TeamCrossCheck | None:
        if not self.teams:
            return None
        return max(self.teams, key=lambda t: t.agreement_ratio)


def cross_check(
    db_kvs: list[dict[str, Any]],
    yt_hits: list[Any],
    *,
    title: str = "",
) -> CrossCheckReport:
    """Compare each DB Korean-version's ``lyrics_lines`` with the pooled
    lyric lines from YouTube hits.

    ``db_kvs`` items must have keys ``translator_team`` and ``lyrics_lines``.
    ``yt_hits`` items are :class:`YouTubeLyricsHit` (description + subtitle).
    """
    # Pool every YouTube line (description + subtitle) across hits so a DB
    # entry can match against the team's own channel regardless of which
    # variant we pulled.
    yt_pool: list[str] = []
    for h in yt_hits or []:
        yt_pool.extend(getattr(h, "description_lyrics", []) or [])
        yt_pool.extend(getattr(h, "subtitle_lyrics", []) or [])
    yt_pool = [s for s in yt_pool if s and s.strip()]

    teams: list[TeamCrossCheck] = []
    for kv in db_kvs or []:
        team = (kv.get("translator_team") or "").strip() or "?"
        db_lines = [str(s) for s in (kv.get("lyrics_lines") or []) if s]
        agreements: list[LinePair] = []
        db_only: list[str] = []
        for line in db_lines:
            best_yt = ""
            best_sim = 0.0
            for ytl in yt_pool:
                s = _sim(line, ytl)
                if s > best_sim:
                    best_sim, best_yt = s, ytl
            if best_sim >= MATCH_THRESHOLD:
                agreements.append(LinePair(line, best_yt, round(best_sim, 3)))
            else:
                db_only.append(line)
        # yt-only = YouTube lines that didn't match any DB line, *limited*
        # to ~12 so the prompt stays compact.
        agreed_yt = {p.yt_line for p in agreements}
        yt_only = [s for s in yt_pool if s not in agreed_yt][:12]
        teams.append(TeamCrossCheck(
            translator_team=team,
            db_lines=db_lines,
            yt_lines=yt_pool[:24],
            agreements=agreements,
            db_only=db_only,
            yt_only=yt_only,
        ))
    return CrossCheckReport(title=title, teams=teams)


def report_to_prompt_block(report: CrossCheckReport, locale: str = "ko") -> str:
    """Render the report as a system-prompt block."""
    if not report or not report.teams:
        return ""
    out: list[str] = []
    if locale == "en":
        out.append(
            "[DB ↔ YouTube cross-validation for the requested song. "
            "When the DB line and the team's own YouTube description / CC "
            "agree, quote that line with high confidence. When they disagree, "
            "show BOTH versions to the user and ask which they prefer — "
            "never silently pick one source.]"
        )
    else:
        out.append(
            "[시드 DB ↔ YouTube 상호 검증 결과입니다. DB 라인과 YouTube "
            "라인이 일치하면 (similarity ≥ 0.70) 그 라인을 확신 있게 인용하고 "
            "두 출처를 모두 표기하세요. 불일치하면 사용자에게 두 버전 모두 "
            "보여주고 어느 쪽을 사용할지 묻습니다. 한 source만 임의로 "
            "선택하면 안 됩니다.]"
        )
    out.append(f"곡: {report.title}")
    for t in report.teams:
        out.append(f"\n• 번안팀: {t.translator_team}")
        out.append(f"  agreement_ratio = {t.agreement_ratio:.2f} "
                   f"(DB lines: {len(t.db_lines)}, agreements: {len(t.agreements)})")
        if t.agreements:
            out.append("  ✅ 두 source 일치:")
            for p in t.agreements[:6]:
                out.append(f"    | {p.db_line}    (sim {p.similarity:.2f})")
        if t.db_only:
            out.append("  ⚠️ DB에만 있음 (YouTube에서 확인 안 됨 — 사용자에게 확인 권장):")
            for ln in t.db_only[:4]:
                out.append(f"    | {ln}")
        if t.yt_only:
            out.append("  📺 YouTube에만 있음 (DB에 미수록 — 보강 후보):")
            for ln in t.yt_only[:6]:
                out.append(f"    | {ln}")
    return "\n".join(out)


__all__ = [
    "LinePair", "TeamCrossCheck", "CrossCheckReport",
    "cross_check", "report_to_prompt_block",
    "MATCH_THRESHOLD",
]
