"""Web-search fallback adapter for songs the seed DB doesn't carry.

Tavily is the default provider (free 1000 calls/month). When the API key
isn't configured the NullAdapter returns an empty list so the chat
endpoint silently degrades to "no web results" instead of erroring.

Stdlib-only on purpose — the rest of the backend already standardized on
urllib for outbound HTTP, no new dependency required.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from ..config import settings


@dataclass
class WebSearchHit:
    title: str
    url: str
    snippet: str = ""


class WebSearchAdapter(Protocol):
    async def search(self, query: str, *, n: int = 5) -> list[WebSearchHit]: ...


class TavilyAdapter:
    """Calls Tavily's /search REST endpoint."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, *, n: int = 5) -> list[WebSearchHit]:
        if not self._api_key or not query.strip():
            return []
        return await asyncio.to_thread(self._sync_search, query, n)

    def _sync_search(self, query: str, n: int) -> list[WebSearchHit]:
        payload = json.dumps({
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": min(max(1, n), 10),
            "include_answer": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as r:
                body = r.read()
        except (urllib.error.URLError, TimeoutError):
            return []
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return []
        out: list[WebSearchHit] = []
        for item in data.get("results") or []:
            out.append(WebSearchHit(
                title=str(item.get("title", ""))[:200],
                url=str(item.get("url", "")),
                snippet=str(item.get("content", ""))[:400],
            ))
        return out


class NullAdapter:
    async def search(self, query: str, *, n: int = 5) -> list[WebSearchHit]:
        return []


_ADAPTER: WebSearchAdapter | None = None


def get_search_adapter() -> WebSearchAdapter:
    """Pick an adapter from settings. Cached for the process lifetime."""
    global _ADAPTER
    if _ADAPTER is None:
        provider = settings.web_search_provider
        if provider == "tavily" and settings.tavily_api_key:
            _ADAPTER = TavilyAdapter(settings.tavily_api_key)
        else:
            _ADAPTER = NullAdapter()
    return _ADAPTER


def render_web_results_block(hits: list[WebSearchHit], *, locale: str = "ko") -> str:
    if not hits:
        return ""
    if locale == "en":
        header = (
            "Web search results (unverified — surface only when the user is asking "
            "about a specific song/artist not in the seed DB). Cite the URL "
            "alongside any factual claim drawn from these:"
        )
    else:
        header = (
            "웹 검색 결과 (미검증 — 시드 DB에 없는 곡/아티스트 질문일 때만 활용). "
            "이 결과에서 끌어온 사실은 반드시 출처 URL을 함께 인용하세요:"
        )
    lines = [header, ""]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h.title}")
        if h.snippet:
            lines.append(f"   · {h.snippet[:250]}")
        if h.url:
            lines.append(f"   · {h.url}")
    return "\n".join(lines).strip()


__all__ = [
    "WebSearchHit",
    "WebSearchAdapter",
    "TavilyAdapter",
    "NullAdapter",
    "get_search_adapter",
    "render_web_results_block",
]
