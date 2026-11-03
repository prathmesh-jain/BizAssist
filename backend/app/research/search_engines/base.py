"""Base class for browser-driven (Playwright) web search engines."""
import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.research.browser import browser_service, random_user_agent

logger = logging.getLogger(__name__)

BLOCK_MARKERS = (
    "unusual traffic", "are you a robot", "not a robot", "verify you are human", "captcha",
    "detected unusual", "please complete the security check", "access denied",
)
TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "msclkid", "yclid", "mc_cid", "mc_eid", "ref_src")


@dataclass(frozen=True)
class EngineResult:
    title: str
    url: str
    snippet: str
    engine: str


class SearchEngineBlocked(RuntimeError):
    """The engine answered with a CAPTCHA or block page; it is paused for a while."""


class SearchEngineFailed(RuntimeError):
    pass


def normalize_url(url: str) -> str:
    """Canonical form used to deduplicate results across engines."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING_PARAMS)
    ))
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", query, ""))


class BrowserSearchEngine(ABC):
    name: str
    #: CSS selector that appears once organic results have rendered.
    result_selector: str
    #: JavaScript evaluated on the results page, returning [{href, title, snippet}].
    extract_js: str
    #: Hosts belonging to the engine itself (navigation, ads, related searches).
    own_hosts: tuple[str, ...] = ()
    min_interval_seconds: float = 2.5
    block_cooldown_seconds: float = 900

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._blocked_until = 0.0

    @abstractmethod
    def build_url(self, query: str, country: str | None) -> str:
        ...

    def unwrap(self, href: str) -> str | None:
        """Turn an engine redirect link into the destination URL (default: as is)."""
        return href

    @property
    def blocked(self) -> bool:
        return time.monotonic() < self._blocked_until

    def _is_own(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == h or host.endswith("." + h) for h in self.own_hosts)

    async def _respect_rate_limit(self) -> None:
        # Space out requests to the same engine, with jitter, like a person would.
        wait = self._last_request + self.min_interval_seconds - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait + random.uniform(0.3, 1.2))
        self._last_request = time.monotonic()

    async def search(self, query: str, *, max_results: int = 8, country: str | None = None) -> list[EngineResult]:
        if self.blocked:
            raise SearchEngineBlocked(f"{self.name} is paused after a block page")
        url = self.build_url(query, country)

        async def fetch(browser):
            context = await browser.new_context(
                user_agent=random_user_agent(), locale="en-US", viewport={"width": 1366, "height": 860},
            )
            try:
                page = await context.new_page()
                # Results pages don't need images, media or fonts.
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ("image", "media", "font")
                    else route.continue_(),
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_selector(self.result_selector, timeout=8000)
                except Exception:
                    pass
                rows = await page.evaluate(self.extract_js)
                body = "" if rows else (await page.inner_text("body"))[:3000]
                return page.url, await page.title(), rows or [], body
            finally:
                await context.close()

        async with self._lock:
            for attempt in (1, 2):
                await self._respect_rate_limit()
                try:
                    final_url, title, rows, body = await browser_service.run(fetch, timeout=60)
                    break
                except Exception as exc:
                    # The first navigations after the browser starts can be slow (cold DNS/TLS);
                    # retry a timeout once. Block pages are detected below and never retried.
                    if attempt == 1 and "Timeout" in exc.__class__.__name__:
                        logger.info("search.engine.retry engine=%s reason=timeout", self.name)
                        continue
                    # Playwright errors include a multi-line call log; keep the first line.
                    first_line = (str(exc).splitlines() or [""])[0][:150]
                    raise SearchEngineFailed(f"{exc.__class__.__name__}: {first_line}".rstrip(": ")) from exc

        if not rows:
            text = f"{final_url} {title} {body}".lower()
            if "/sorry/" in final_url or any(marker in text for marker in BLOCK_MARKERS):
                self._blocked_until = time.monotonic() + self.block_cooldown_seconds
                logger.warning("search.engine.blocked engine=%s cooldown=%ss", self.name, self.block_cooldown_seconds)
                raise SearchEngineBlocked(f"{self.name} returned a block/CAPTCHA page")
            return []

        results: list[EngineResult] = []
        seen: set[str] = set()
        for row in rows:
            target = self.unwrap(str(row.get("href") or ""))
            if not target or urlparse(target).scheme not in ("http", "https") or self._is_own(target):
                continue
            key = normalize_url(target)
            if key in seen:
                continue
            seen.add(key)
            results.append(EngineResult(
                title=" ".join(str(row.get("title") or target).split())[:300],
                url=target,
                snippet=" ".join(str(row.get("snippet") or "").split())[:500],
                engine=self.name,
            ))
            if len(results) >= max_results:
                break
        logger.info("search.engine.results engine=%s query=%r count=%s", self.name, query, len(results))
        return results
