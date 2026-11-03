"""Web search providers for business research.

  - BrowserSearchProvider (default): Yahoo/Bing/Google results pages read with headless
    Chromium, merged and deduplicated. No API keys.
  - OpenAIWebSearchProvider: OpenAI web search on the requesting user's own key.
  - GoogleProgrammableSearchProvider: Google's Custom Search JSON API (kept, not used by default).
"""
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx
from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int = 6, country: str | None = None) -> list[SearchResult]:
        ...


class SearchError(RuntimeError):
    pass


class OpenAIWebSearchProvider:
    """Runs the query through OpenAI's web_search tool and returns the cited pages."""

    name = "openai_web_search"

    def __init__(self, api_key: str, model: str):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def search(self, query: str, *, max_results: int = 6, country: str | None = None) -> list[SearchResult]:
        tool: dict = {"type": "web_search", "user_location": {"type": "approximate"}}
        if country and len(country) == 2:
            tool["user_location"]["country"] = country.upper()
        try:
            response = await self._client.responses.create(
                model=self._model,
                tools=[tool],
                input=(
                    f"Search the web for: {query}\n"
                    f"Report the {max_results} most relevant results. For each, write one factual sentence "
                    "about what the page says, citing the page. Do not add information that is not on the pages."
                ),
            )
        except Exception as exc:
            raise SearchError(f"Web search failed: {exc}") from exc

        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in response.output or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in getattr(item, "content", None) or []:
                text = getattr(part, "text", "") or ""
                for ann in getattr(part, "annotations", None) or []:
                    if getattr(ann, "type", None) != "url_citation" or ann.url in seen:
                        continue
                    seen.add(ann.url)
                    results.append(SearchResult(title=ann.title or ann.url, url=ann.url, snippet=_sentence_around(text, ann.start_index)))
        return results[:max_results]


class GoogleProgrammableSearchProvider:
    name = "google_programmable_search"
    ENDPOINT = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, engine_id: str):
        self._api_key = api_key
        self._engine_id = engine_id

    async def search(self, query: str, *, max_results: int = 6, country: str | None = None) -> list[SearchResult]:
        params = {"key": self._api_key, "cx": self._engine_id, "q": query, "num": min(max_results, 10)}
        if country and len(country) == 2:
            params["gl"] = country.lower()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.ENDPOINT, params=params)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchError(f"Google search failed: {exc}") from exc
        return [
            SearchResult(title=i.get("title") or i.get("link"), url=i["link"], snippet=i.get("snippet") or "")
            for i in resp.json().get("items", [])
            if i.get("link")
        ]


def _sentence_around(text: str, index: int) -> str:
    """The sentence of the model's summary that a citation is attached to."""
    if not text:
        return ""
    start = max(text.rfind(". ", 0, index), text.rfind("\n", 0, index)) + 1
    end_candidates = [p for p in (text.find(". ", index), text.find("\n", index)) if p != -1]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    return text[start:end].strip()[:400]


class BrowserSearchProvider:
    """Searches several engines through a headless browser and merges the results.

    Engines run concurrently; results are merged in engine priority order and
    deduplicated by normalized URL. A blocked or failing engine is skipped; the
    search fails only if every engine fails.
    """

    def __init__(self, engines: list):
        self._engines = engines
        self.name = "browser:" + ",".join(e.name for e in engines)

    async def search(self, query: str, *, max_results: int = 6, country: str | None = None) -> list[SearchResult]:
        import asyncio

        from app.research.search_engines import normalize_url

        outcomes = await asyncio.gather(
            *(engine.search(query, max_results=max_results, country=country) for engine in self._engines),
            return_exceptions=True,
        )
        merged: list[SearchResult] = []
        seen: set[str] = set()
        errors: list[str] = []
        for engine, outcome in zip(self._engines, outcomes):
            if isinstance(outcome, BaseException):
                errors.append(f"{engine.name}: {outcome}")
                logger.info("search.engine.skipped engine=%s reason=%s", engine.name, outcome)
                continue
            for r in outcome:
                key = normalize_url(r.url)
                if key not in seen:
                    seen.add(key)
                    merged.append(SearchResult(title=r.title, url=r.url, snippet=r.snippet))
        if len(errors) == len(self._engines):
            raise SearchError("All search engines failed: " + "; ".join(errors))
        # Over-fetch per engine, then keep the best-ranked unique results overall.
        return merged[: max_results * 2]


def build_search_provider(*, user_api_key: str, model: str) -> SearchProvider:
    """Default: headless-browser search over the configured engines (no API keys needed).

    "openai" (web search on the user's key) and "google_api" (Programmable Search) remain
    available as alternatives but are not the default.
    """
    choice = (settings.research_search_provider or "browser").lower()
    if choice == "openai":
        return OpenAIWebSearchProvider(api_key=user_api_key, model=model)
    if choice in ("google_api", "google"):
        if not (settings.google_search_api_key and settings.google_search_engine_id):
            raise SearchError("RESEARCH_SEARCH_PROVIDER=google_api needs GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_ENGINE_ID.")
        return GoogleProgrammableSearchProvider(settings.google_search_api_key, settings.google_search_engine_id)

    from app.research.search_engines import SearchEngineFactory

    return BrowserSearchProvider(SearchEngineFactory.from_config(settings.research_search_engines))
