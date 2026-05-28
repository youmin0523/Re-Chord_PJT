"""Music seed DB loader + lightweight lyric/title search.

Two JSON files back this module:
  - backend/data/seed/music_songs.json  (CCM + Pop/K-Pop + jazz/standards)
  - backend/data/seed/hymns.json        (Korean hymnals; bilingual KO/EN)

The schemas are documented in the chatbot plan. Both files are optional;
a missing/empty seed file just means the corresponding indexes stay empty.

We use rapidfuzz when available (fast token-set ratio) and gracefully fall
back to a simple substring score when it isn't installed yet. This keeps
the chatbot working on a freshly cloned project before the user runs
``pip install rapidfuzz``.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import settings


try:  # optional dep — graceful fallback
    from rapidfuzz import fuzz as _rapidfuzz_fuzz  # type: ignore

    def _score(query: str, candidate: str) -> float:
        if not query or not candidate:
            return 0.0
        # token_set_ratio is forgiving of word reordering, which fits how
        # users type lyric fragments.
        return float(_rapidfuzz_fuzz.token_set_ratio(query, candidate)) / 100.0
except Exception:  # noqa: BLE001
    def _score(query: str, candidate: str) -> float:
        if not query or not candidate:
            return 0.0
        q = query.lower().strip()
        c = candidate.lower().strip()
        if q in c:
            return min(1.0, 0.5 + len(q) / max(1, len(c)) * 0.5)
        # Word overlap heuristic.
        qw = set(re.findall(r"\w+", q))
        cw = set(re.findall(r"\w+", c))
        if not qw or not cw:
            return 0.0
        return len(qw & cw) / len(qw | cw)


SEED_DIR = settings.data_dir.parent / "backend" / "data" / "seed"
# Fall back to a sibling path layout if the project root isn't named "MR Project".
if not SEED_DIR.exists():
    alt = Path(__file__).resolve().parents[2] / "data" / "seed"
    if alt.exists():
        SEED_DIR = alt


@dataclass
class KoreanVersion:
    translator_team: str
    title_ko: str
    lyrics_snippet_ko: str = ""        # legacy single-line snippet
    lyrics_lines: list[str] = field(default_factory=list)  # 5–10 key lines covering verse / chorus / bridge
    # Full Korean translation lyrics. Only fill in for songs where the
    # copyright holder permits redistribution (e.g. hymn-adjacent or
    # explicit CCLI license). Otherwise leave None — the LLM should fall
    # back to citing the official source URL.
    lyrics_full: str | None = None
    url: str | None = None
    needs_verification: bool = False   # surfaces to UI; true means "AI-guessed, not curated"

    def all_lines(self) -> list[str]:
        """Every searchable lyric fragment for this version (legacy snippet
        included). Empty strings are filtered.
        """
        out = [s for s in (self.lyrics_lines or []) if s and s.strip()]
        if self.lyrics_snippet_ko and self.lyrics_snippet_ko.strip():
            out.append(self.lyrics_snippet_ko)
        return out


@dataclass
class SongRecord:
    id: str
    primary_title: str
    primary_language: str
    artist: str
    year: int | None = None
    genre: str | None = None
    ccli: str | None = None
    hymn_number: int | None = None
    original_lyrics_snippet: str = ""             # legacy single-line snippet
    original_lyrics_lines: list[str] = field(default_factory=list)
    # Full original-language lyrics. Same copyright caveat as KoreanVersion.
    original_lyrics_full: str | None = None
    korean_versions: list[KoreanVersion] = field(default_factory=list)
    official_url: str | None = None
    license_note: str | None = None
    key_hint: str | None = None
    bpm_hint: float | None = None
    tags: list[str] = field(default_factory=list)

    def original_all_lines(self) -> list[str]:
        out = [s for s in (self.original_lyrics_lines or []) if s and s.strip()]
        if self.original_lyrics_snippet and self.original_lyrics_snippet.strip():
            out.append(self.original_lyrics_snippet)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SongRecord":
        kvs = []
        for v in d.get("korean_versions") or []:
            kvs.append(KoreanVersion(
                translator_team=str(v.get("translator_team", "")),
                title_ko=str(v.get("title_ko", "")),
                lyrics_snippet_ko=str(v.get("lyrics_snippet_ko", "") or ""),
                lyrics_lines=[str(s) for s in (v.get("lyrics_lines") or []) if s],
                lyrics_full=v.get("lyrics_full"),
                url=v.get("url"),
                needs_verification=bool(v.get("needs_verification", False)),
            ))
        return cls(
            id=str(d["id"]),
            primary_title=str(d.get("primary_title", "")),
            primary_language=str(d.get("primary_language", "en")),
            artist=str(d.get("artist", "")),
            year=d.get("year"),
            genre=d.get("genre"),
            ccli=d.get("ccli"),
            hymn_number=d.get("hymn_number"),
            original_lyrics_snippet=str(d.get("original_lyrics_snippet", "") or ""),
            original_lyrics_lines=[str(s) for s in (d.get("original_lyrics_lines") or []) if s],
            original_lyrics_full=d.get("original_lyrics_full"),
            korean_versions=kvs,
            official_url=d.get("official_url"),
            license_note=d.get("license_note"),
            key_hint=d.get("key_hint"),
            bpm_hint=d.get("bpm_hint"),
            tags=list(d.get("tags") or []),
        )


@dataclass
class HymnRecord:
    id: str
    hymnal_edition: str          # "new_2006" | "unified_1981"
    hymn_number: int
    title_ko: str
    title_en: str | None = None
    original_writer: str | None = None
    composer: str | None = None
    year: int | None = None
    korean_translator: str | None = None
    lyrics_snippet_ko: str = ""                   # legacy single-line snippet
    lyrics_snippet_en: str | None = None
    lyrics_lines_ko: list[str] = field(default_factory=list)
    lyrics_lines_en: list[str] = field(default_factory=list)
    # Full lyrics — only populated for songs in the public domain (most
    # hymns). Loaded into the system prompt ONLY when the user explicitly
    # asks for "전체 가사"/"full lyrics"; otherwise we use lyrics_lines
    # so token usage and copyright exposure stay bounded.
    lyrics_full_ko: str | None = None
    lyrics_full_en: str | None = None
    key_hint: str | None = None
    time_signature: str | None = None
    tags: list[str] = field(default_factory=list)
    origin: str | None = None    # "translated" | "native_korean" | "hymn_traditional"
    cross_ref: str | None = None

    def ko_lines(self) -> list[str]:
        out = [s for s in (self.lyrics_lines_ko or []) if s and s.strip()]
        if self.lyrics_snippet_ko and self.lyrics_snippet_ko.strip():
            out.append(self.lyrics_snippet_ko)
        return out

    def en_lines(self) -> list[str]:
        out = [s for s in (self.lyrics_lines_en or []) if s and s.strip()]
        if self.lyrics_snippet_en and self.lyrics_snippet_en.strip():
            out.append(self.lyrics_snippet_en)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HymnRecord":
        return cls(
            id=str(d["id"]),
            hymnal_edition=str(d.get("hymnal_edition", "new_2006")),
            hymn_number=int(d.get("hymn_number", 0) or 0),
            title_ko=str(d.get("title_ko", "")),
            title_en=d.get("title_en"),
            original_writer=d.get("original_writer"),
            composer=d.get("composer"),
            year=d.get("year"),
            korean_translator=d.get("korean_translator"),
            lyrics_snippet_ko=str(d.get("lyrics_snippet_ko", "") or ""),
            lyrics_snippet_en=d.get("lyrics_snippet_en"),
            lyrics_lines_ko=[str(s) for s in (d.get("lyrics_lines_ko") or []) if s],
            lyrics_lines_en=[str(s) for s in (d.get("lyrics_lines_en") or []) if s],
            lyrics_full_ko=d.get("lyrics_full_ko"),
            lyrics_full_en=d.get("lyrics_full_en"),
            key_hint=d.get("key_hint"),
            time_signature=d.get("time_signature"),
            tags=list(d.get("tags") or []),
            origin=d.get("origin"),
            cross_ref=d.get("cross_ref"),
        )


@dataclass
class SearchHit:
    kind: str                    # "song" | "hymn"
    score: float
    record: SongRecord | HymnRecord
    matched_via: str             # human-readable hint, e.g. "korean_versions[마커스]"


class MusicDB:
    """In-memory index. Lazy-loaded; safe to call from any thread.

    Reload by deleting ``music_songs.json`` / ``hymns.json`` and creating
    a new MusicDB() instance; the file is otherwise read once per process.
    """

    def __init__(self, seed_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self.seed_dir = seed_dir or SEED_DIR
        self.songs: dict[str, SongRecord] = {}
        self.hymns: dict[str, HymnRecord] = {}
        # Tag-based cross-reference indexes (built after songs are loaded).
        # Keys are tag-payload strings (lowercase), values are song id lists.
        self._lineage_index: dict[str, list[str]] = {}  # original_id -> arrangement song ids
        self._team_index: dict[str, list[str]] = {}     # team_slug   -> song ids performed by team
        self._voicing_index: dict[str, list[str]] = {}  # voicing tag -> song ids

    # --- loading ---------------------------------------------------------

    def _load_songs(self) -> None:
        path = self.seed_dir / "music_songs.json"
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = raw.get("songs") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        for d in items:
            try:
                rec = SongRecord.from_dict(d)
                self.songs[rec.id] = rec
            except Exception:
                continue

    def _load_hymns(self) -> None:
        path = self.seed_dir / "hymns.json"
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = raw.get("hymns") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        for d in items:
            try:
                rec = HymnRecord.from_dict(d)
                self.hymns[rec.id] = rec
            except Exception:
                continue

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._load_songs()
            self._load_hymns()
            self._build_tag_indexes()
            self._loaded = True

    # --- tag indexing ---------------------------------------------------
    # Tag taxonomy is documented in music_songs.json#tag_taxonomy. This
    # parser is intentionally tolerant: malformed/non-standard tags just
    # don't get indexed (rather than crashing the load).

    _LINEAGE_PREFIXES = ("arrangement-of:", "cover-of:", "translation-of:")
    _TEAM_PREFIX = "performed-by:"
    _VOICING_PREFIX = "voicing:"

    def _build_tag_indexes(self) -> None:
        self._lineage_index.clear()
        self._team_index.clear()
        self._voicing_index.clear()
        for sid, rec in self.songs.items():
            for tag in rec.tags:
                t = str(tag).strip().lower()
                if not t:
                    continue
                # lineage — any of arrangement-of: / cover-of: / translation-of: all
                # point to the same family root, so collapse into one index.
                for prefix in self._LINEAGE_PREFIXES:
                    if t.startswith(prefix):
                        root = t[len(prefix):].strip()
                        if root:
                            self._lineage_index.setdefault(root, []).append(sid)
                        break
                else:
                    if t.startswith(self._TEAM_PREFIX):
                        team = t[len(self._TEAM_PREFIX):].strip()
                        if team:
                            self._team_index.setdefault(team, []).append(sid)
                    elif t.startswith(self._VOICING_PREFIX):
                        self._voicing_index.setdefault(t, []).append(sid)

    # --- tag-based lookup APIs -----------------------------------------

    def arrangements_of(self, original_id: str) -> list[SongRecord]:
        """All songs tagged as an arrangement/cover/translation of ``original_id``.

        Excludes the original itself. Returned in seed insertion order.
        """
        self.ensure_loaded()
        ids = self._lineage_index.get(original_id.lower(), [])
        return [self.songs[i] for i in ids if i in self.songs and i != original_id]

    def songs_by_team(self, team_slug: str) -> list[SongRecord]:
        """All songs performed by the given team slug (performed-by:slug)."""
        self.ensure_loaded()
        ids = self._team_index.get(team_slug.lower(), [])
        return [self.songs[i] for i in ids if i in self.songs]

    def songs_by_voicing(self, voicing_tag: str) -> list[SongRecord]:
        """All songs with a specific voicing tag (e.g. 'voicing:satb').

        The full tag form (with prefix) is expected so caller can be
        explicit about whether they want SATB vs 3-part vs unison.
        """
        self.ensure_loaded()
        t = voicing_tag.lower()
        if not t.startswith(self._VOICING_PREFIX):
            t = self._VOICING_PREFIX + t
        ids = self._voicing_index.get(t, [])
        return [self.songs[i] for i in ids if i in self.songs]

    # --- search ----------------------------------------------------------

    def search(self, query: str, *, top_k: int = 5, min_score: float = 0.3) -> list[SearchHit]:
        """Score every record against ``query``.

        For lyric fields we compare against every available line and keep
        the best, so a user can quote the chorus / bridge and still match
        (single-snippet schemas miss those queries).
        """
        self.ensure_loaded()
        q = (query or "").strip()
        if not q:
            return []
        hits: list[SearchHit] = []

        def best_of_lines(lines: list[str]) -> tuple[float, int]:
            best = 0.0
            best_idx = -1
            for i, line in enumerate(lines):
                sc = _score(q, line)
                if sc > best:
                    best, best_idx = sc, i
            return best, best_idx

        q_lower = q.lower()
        for s in self.songs.values():
            best = 0.0
            via = ""
            # Substring boost — if the user typed the exact title (en or ko),
            # token-set ratio dilutes it against the rest of the sentence and
            # the song would lose to artist-only matches on other records.
            # We force a strong score whenever the canonical title appears
            # as a substring so the correct entry always surfaces.
            for kt in [s.primary_title] + [kv.title_ko for kv in s.korean_versions if kv.title_ko]:
                if kt and len(kt) >= 3 and kt.lower() in q_lower:
                    best = max(best, 0.95)
                    via = "primary_title_substring"
                    break
            # Title / artist (single-string fields stay single-string).
            for name, candidate in (
                ("primary_title", s.primary_title),
                ("artist", s.artist),
            ):
                sc = _score(q, candidate)
                if sc > best:
                    best, via = sc, name
            # Original lyrics — score against every known line, keep best.
            orig_lines = s.original_all_lines()
            if orig_lines:
                sc, idx = best_of_lines(orig_lines)
                if sc > best:
                    best, via = sc, f"original_lyrics[{idx}]"
            # Korean versions — title plus every translated line.
            for i, kv in enumerate(s.korean_versions):
                sc = _score(q, kv.title_ko)
                if sc > best:
                    best, via = sc, f"korean[{kv.translator_team or i}]:title"
                kv_lines = kv.all_lines()
                if kv_lines:
                    sc, idx = best_of_lines(kv_lines)
                    if sc > best:
                        best, via = sc, f"korean[{kv.translator_team or i}]:lyrics[{idx}]"
            if best >= min_score:
                hits.append(SearchHit(kind="song", score=best, record=s, matched_via=via))

        for h in self.hymns.values():
            best = 0.0
            via = ""
            for name, candidate in (
                ("title_ko", h.title_ko),
                ("title_en", h.title_en or ""),
                ("original_writer", h.original_writer or ""),
            ):
                sc = _score(q, candidate)
                if sc > best:
                    best, via = sc, name
            ko_lines = h.ko_lines()
            if ko_lines:
                sc, idx = best_of_lines(ko_lines)
                if sc > best:
                    best, via = sc, f"lyrics_ko[{idx}]"
            en_lines = h.en_lines()
            if en_lines:
                sc, idx = best_of_lines(en_lines)
                if sc > best:
                    best, via = sc, f"lyrics_en[{idx}]"
            if best >= min_score:
                hits.append(SearchHit(kind="hymn", score=best, record=h, matched_via=via))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def stats(self) -> dict[str, int]:
        self.ensure_loaded()
        return {"songs": len(self.songs), "hymns": len(self.hymns)}


_DB: MusicDB | None = None


def get_db() -> MusicDB:
    global _DB
    if _DB is None:
        _DB = MusicDB()
    return _DB


def render_hits_block(hits: list[SearchHit], locale: str = "ko") -> str:
    """Render search hits as a structured block for the system prompt.

    Format keeps it compact (each hit ≈ 4 lines) so we don't blow the
    context window on a noisy match list.
    """
    if not hits:
        return ""
    lines = []
    if locale == "en":
        lines.append("Possible matches from Re:Chord's music DB (use these "
                     "to ground your answer; cite the translator team when "
                     "showing Korean lyrics):")
    else:
        lines.append("Re:Chord 시드 DB의 후보 매칭 (응답에서 이 정보를 우선 활용. "
                     "한국어 가사를 보일 때는 번안팀명을 함께 명시):")
    for i, h in enumerate(hits, 1):
        r = h.record
        score_pct = int(round(h.score * 100))
        if isinstance(r, SongRecord):
            head = f"{i}. [song · {score_pct}%] {r.primary_title}"
            if r.artist:
                head += f" — {r.artist}"
            if r.year:
                head += f" ({r.year})"
            lines.append(head)
            if r.korean_versions:
                for kv in r.korean_versions:
                    kv_lines = kv.all_lines()
                    tag = " ⚠미검증" if kv.needs_verification else " ✅검증됨"
                    head = (
                        f"   · 한국어 번안 [{kv.translator_team}]{tag} "
                        f"{kv.title_ko}"
                    )
                    lines.append(head)
                    if kv_lines and not kv.needs_verification:
                        # Verified translation — inject all lines so the model
                        # has to quote them verbatim instead of paraphrasing.
                        # This is the key fix for the "Way Maker 마커스 번안
                        # 첫 줄 환각" failure: previously only the first 60
                        # chars made it into the prompt and the model would
                        # confidently substitute its own near-miss.
                        for ln in kv_lines[:8]:
                            lines.append(f"     | {ln}")
                    elif kv_lines:
                        # Unverified — show one preview line + the explicit
                        # warning that this isn't trustworthy for citation.
                        lines.append(f"     | {kv_lines[0][:60]}  (미검증 — 인용 금지)")
                    else:
                        lines.append("     (시드 DB에 가사 미수록 — YouTube lookup 또는 AI 번안 필요)")
            orig_lines = r.original_all_lines()
            if orig_lines:
                # Show up to 3 lines so the model has more anchor points.
                for ln in orig_lines[:3]:
                    lines.append(f"   · 원곡 가사: \"{ln[:80]}\"")
            extras = []
            if r.key_hint: extras.append(f"key {r.key_hint}")
            if r.bpm_hint: extras.append(f"BPM {r.bpm_hint:.0f}")
            if r.official_url: extras.append(f"출처 {r.official_url}")
            if extras:
                lines.append("   · " + " · ".join(extras))
            lines.append(f"   · matched_via: {h.matched_via}")
            # If this record is the family root (original), surface known
            # arrangements/covers from the lineage index so the model can
            # point users to e.g. SATB references or alternate team versions.
            db = get_db()
            arrangements = db.arrangements_of(r.id)
            if arrangements:
                arr_summary = ", ".join(
                    f"{a.primary_title} [{a.artist[:30]}]" for a in arrangements[:6]
                )
                more = "" if len(arrangements) <= 6 else f" 외 {len(arrangements) - 6}건"
                lines.append(f"   · 알려진 편곡/커버 ({len(arrangements)}건): {arr_summary}{more}")
        else:
            # HymnRecord
            edition_label = {
                "new_2006": "21세기찬송가",
                "unified_1981": "통일찬송가",
            }.get(r.hymnal_edition, r.hymnal_edition)
            head = f"{i}. [hymn · {score_pct}%] {edition_label} {r.hymn_number}장 — {r.title_ko}"
            if r.title_en:
                head += f" / {r.title_en}"
            lines.append(head)
            ko_lines = r.ko_lines()
            for ln in ko_lines[:3]:
                lines.append(f"   · 한국어: \"{ln[:80]}\"")
            en_lines = r.en_lines()
            for ln in en_lines[:3]:
                lines.append(f"   · English: \"{ln[:80]}\"")
            if r.original_writer:
                lines.append(f"   · 원작사자: {r.original_writer}")
            lines.append(f"   · matched_via: {h.matched_via}")
    return "\n".join(lines)


__all__ = [
    "MusicDB",
    "SongRecord",
    "HymnRecord",
    "KoreanVersion",
    "SearchHit",
    "get_db",
    "render_hits_block",
]
