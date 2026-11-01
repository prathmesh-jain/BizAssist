"""Business research workflow: website analysis + web search -> reviewable, source-backed proposal.

Deliberately separate from the chat agent graph. Dependencies (LLM, search, website
reader) are injected so the workflow is testable without network access.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel

from app.research.schemas import (
    BUSINESS_MODELS, GEOGRAPHIES, INDUSTRIES, SCALES,
    CompetitorAnalysis, OpportunityAnalysis, ProfileProposal, SearchPlan, SourcedList, SourcedValue, WebsitePick,
)
from app.research.search import SearchError, SearchProvider, SearchResult
from app.research.website import WebPage, WebsiteFetchError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
StructuredLLM = Callable[[type[T], str, str], Awaitable[T]]
WebsiteAnalyzer = Callable[[str], Awaitable[list[WebPage]]]
ProgressCallback = Callable[[str], Awaitable[None]]

MAX_COMPETITORS = 8
MAX_OPPORTUNITIES = 6

EVIDENCE_RULES = """
Evidence rules (strict):
- Use only the evidence provided. Cite sources only by URLs that appear in the evidence list.
- Never invent revenue, profit, employee counts, customer counts, market share, or rankings.
  Mention a number only if a cited source states it.
- basis "verified" requires at least one cited source that states the value.
- basis "estimated" is for reasonable inferences; say in note what the estimate rests on.
- basis "unknown" with value null when the evidence says nothing.
- The user's own answers are authoritative about their business.
"""

PROFILE_FIELDS_SINGLE = ("description", "industry", "subdomain", "scale", "geography", "location")
PROFILE_FIELDS_LIST = ("business_model", "products_services", "customer_segments")
ALLOWED_VALUES = {"industry": INDUSTRIES, "scale": SCALES, "geography": GEOGRAPHIES}


class ResearchWorkflow:
    def __init__(
        self,
        *,
        structured: StructuredLLM,
        search: SearchProvider,
        analyze_website: WebsiteAnalyzer,
        progress: ProgressCallback | None = None,
    ):
        self._structured = structured
        self._search = search
        self._analyze_website = analyze_website
        self._progress = progress
        self._sources: dict[str, dict] = {}
        self._warnings: list[str] = []

    async def _step(self, message: str) -> None:
        logger.info("research.step %s", message)
        if self._progress:
            await self._progress(message)

    def _add_source(self, url: str, title: str, kind: str) -> None:
        if url and url not in self._sources:
            self._sources[url] = {"url": url, "title": title or url, "kind": kind}

    async def _safe_search(self, query: str, country: str | None) -> list[SearchResult]:
        try:
            results = await self._search.search(query, max_results=6, country=country)
        except SearchError as exc:
            self._warnings.append(f"Search for '{query}' failed: {exc}")
            return []
        for r in results:
            self._add_source(r.url, r.title, "search")
        return results

    async def run(self, onboarding: dict[str, Any]) -> dict[str, Any]:
        name = (onboarding.get("name") or "").strip()
        if not name:
            raise ValueError("A business name is required to run research.")
        location = (onboarding.get("location") or "").strip()
        country = _country_code(onboarding.get("country"))
        user_json = json.dumps(_compact(onboarding), ensure_ascii=False, indent=1)

        # 1. Official website
        website = (onboarding.get("website") or "").strip() or None
        if not website:
            await self._step("Looking for the official website")
            results = await self._safe_search(f"{name} {location} official website".strip(), country)
            if results:
                pick = await self._structured(
                    WebsitePick,
                    "Pick the business's own official website from search results. Return null unless one result is "
                    "clearly the official site of this exact business (not a directory, marketplace listing, or namesake).",
                    f"Business: {name}\nLocation: {location or 'unknown'}\n\nResults:\n{_format_results(results)}",
                )
                if pick.url and pick.url in {r.url for r in results}:
                    website = pick.url

        # 2. Website analysis
        pages: list[WebPage] = []
        if website:
            await self._step(f"Reading {urlparse(website if '://' in website else 'https://' + website).hostname}")
            try:
                pages = await self._analyze_website(website)
                for page in pages:
                    self._add_source(page.url, page.title, "website")
            except WebsiteFetchError as exc:
                self._warnings.append(f"Could not read the website: {exc}")

        # 3. Public information
        await self._step("Searching for public information about the business")
        mentions = await self._safe_search(f'"{name}" {location}'.strip(), country)

        # 4. Classification
        await self._step("Classifying the business")
        proposal = await self._structured(
            ProfileProposal,
            "You are a business analyst building a profile of a business from evidence.\n" + EVIDENCE_RULES,
            f"User's onboarding answers:\n{user_json}\n\n"
            f"Website pages:\n{_format_pages(pages) or '(none)'}\n\n"
            f"Search results:\n{_format_results(mentions) or '(none)'}",
        )
        profile = self._merge_profile(proposal, onboarding, website)

        # 5. Scale-aware competitors
        await self._step("Finding comparable competitors")
        summary = _profile_summary(profile)
        plan = await self._structured(
            SearchPlan,
            "Write web search queries that find this business's realistic competitors: businesses of comparable "
            "scale serving the same customers in the same area. For a small local business, search locally "
            "(e.g. '<category> in <neighbourhood/city>'); never aim at national giants.",
            summary,
        )
        competitor_results: list[SearchResult] = []
        own_host = _host(profile["website"]["value"])
        for query in plan.queries[:4]:
            for r in await self._safe_search(query, country):
                if _host(r.url) != own_host and r.url not in {c.url for c in competitor_results}:
                    competitor_results.append(r)
        competitors = CompetitorAnalysis()
        if competitor_results:
            competitors = await self._structured(
                CompetitorAnalysis,
                "Identify the business's competitors from the search results.\n"
                "- Prefer direct competitors of similar scale in the same geography and customer segment.\n"
                "- A much larger company may appear only as 'indirect' with relative_scale 'much_larger', and only "
                "when customers genuinely choose between them.\n"
                "- Exclude the business itself, directories, review aggregators and news sites.\n" + EVIDENCE_RULES,
                f"The business:\n{summary}\n\nSearch results:\n{_format_results(competitor_results)}",
            )

        # 6. Trends and opportunities
        await self._step("Looking at industry trends and improvement opportunities")
        sector = profile["subdomain"]["value"] or profile["industry"]["value"] or "small business"
        region = location or "global"
        trend_results = await self._safe_search(
            f"{sector} industry trends {region} {datetime.now(timezone.utc).year}", country
        )
        opportunities = await self._structured(
            OpportunityAnalysis,
            "Suggest practical operational and growth improvements for this business, tied to its goals and "
            "challenges. Mark basis 'evidence' only when grounded in the cited sources or the user's answers; "
            "otherwise 'general_practice'. Summarize relevant industry trends from the results.\n" + EVIDENCE_RULES,
            f"The business:\n{summary}\n\nGoals: {onboarding.get('goals') or []}\n"
            f"Challenges: {onboarding.get('challenges') or []}\n\nSearch results:\n{_format_results(trend_results) or '(none)'}",
        )

        known = set(self._sources)
        return {
            "profile": profile,
            "public_facts": [
                {"fact": f.fact, "sources": _valid(f.sources, known)}
                for f in proposal.public_facts if _valid(f.sources, known)
            ],
            "competitors": [
                {**c.model_dump(), "sources": _valid(c.sources, known)}
                for c in competitors.competitors
                if _host(c.website) != own_host and c.name.strip().lower() != name.lower()
            ][:MAX_COMPETITORS],
            "industry_trends": [
                {"summary": t.summary, "sources": _valid(t.sources, known)}
                for t in opportunities.industry_trends if _valid(t.sources, known)
            ],
            "opportunities": [
                {
                    **o.model_dump(),
                    "sources": _valid(o.sources, known),
                    "basis": _opportunity_basis(o.basis, o.sources, known),
                }
                for o in opportunities.opportunities
            ][:MAX_OPPORTUNITIES],
            "sources": list(self._sources.values()),
            "warnings": self._warnings,
            "search_provider": getattr(self._search, "name", "unknown"),
        }

    def _merge_profile(self, proposal: ProfileProposal, onboarding: dict, website: str | None) -> dict:
        known = set(self._sources)
        profile: dict[str, dict] = {}

        def research_entry(field: SourcedValue | SourcedList, allowed: list[str] | None = None) -> dict:
            sources = _valid(field.sources, known)
            basis = field.basis
            if basis == "verified" and not sources:
                basis = "estimated"  # a "verified" claim needs a real source
            value = field.values if isinstance(field, SourcedList) else field.value
            if allowed is not None:
                if isinstance(value, list):
                    value = [v for v in value if v in allowed]
                elif value not in allowed:
                    value = None
            if value in (None, "", []):
                basis = "unknown"
            return {"value": value, "basis": basis, "sources": sources, "note": field.note}

        for key in PROFILE_FIELDS_SINGLE:
            profile[key] = research_entry(getattr(proposal, key), ALLOWED_VALUES.get(key))
        for key in PROFILE_FIELDS_LIST:
            profile[key] = research_entry(getattr(proposal, key), BUSINESS_MODELS if key == "business_model" else None)

        # The user's answers win; research is kept alongside as a suggestion when it differs.
        for key in PROFILE_FIELDS_SINGLE + PROFILE_FIELDS_LIST:
            given = onboarding.get(key)
            if given not in (None, "", []):
                researched = profile[key]
                entry = {"value": given, "basis": "user_provided", "sources": [], "note": ""}
                if researched["value"] not in (None, [], given) and researched["basis"] != "unknown":
                    entry["suggested"] = researched
                profile[key] = entry

        user_site = (onboarding.get("website") or "").strip()
        if user_site:
            profile["website"] = {"value": user_site, "basis": "user_provided", "sources": [], "note": ""}
        elif website:
            profile["website"] = {"value": website, "basis": "verified", "sources": [website], "note": "Found by search."}
        else:
            profile["website"] = {"value": None, "basis": "unknown", "sources": [], "note": ""}
        profile["name"] = {"value": onboarding.get("name"), "basis": "user_provided", "sources": [], "note": ""}
        return profile


def _opportunity_basis(basis: str, cited: list[str], known: set[str]) -> str:
    """"evidence" may rest on the user's answers (no URLs) or on real sources. Citations that
    all turn out to be unknown URLs mean the claimed evidence isn't there: downgrade it."""
    if basis == "evidence" and cited and not _valid(cited, known):
        return "general_practice"
    return basis


def _valid(urls: list[str], known: set[str]) -> list[str]:
    return [u for u in dict.fromkeys(urls or []) if u in known]


def _host(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    return host.removeprefix("www.") or None


def _country_code(value: Any) -> str | None:
    value = (value or "").strip() if isinstance(value, str) else ""
    return value.upper() if len(value) == 2 else None


def _compact(data: dict) -> dict:
    return {k: v for k, v in data.items() if v not in (None, "", [], {})}


def _format_results(results: list[SearchResult]) -> str:
    return "\n".join(f"- {r.title}\n  URL: {r.url}\n  {r.snippet}" for r in results)


def _format_pages(pages: list[WebPage]) -> str:
    blocks = []
    for p in pages:
        blocks.append(
            f"## {p.url}\nTitle: {p.title}\nDescription: {p.description}\n"
            f"Headings: {' | '.join(p.headings[:12])}\nText: {p.text[:2500]}"
        )
    return "\n\n".join(blocks)


def _profile_summary(profile: dict) -> str:
    lines = []
    for key in ("name", "website", "location", "industry", "subdomain", "business_model", "scale", "geography",
                "products_services", "customer_segments", "description"):
        value = profile.get(key, {}).get("value")
        if value not in (None, "", []):
            lines.append(f"{key}: {', '.join(value) if isinstance(value, list) else value}")
    return "\n".join(lines)
