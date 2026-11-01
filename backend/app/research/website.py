"""Safe website fetching and text extraction for business research.

The URL comes from user input, so fetching is guarded against SSRF: only http(s) on
default ports, only hosts that resolve to public addresses (re-checked on every
redirect), with size and time limits.
"""
import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

MAX_BYTES = 1_500_000
MAX_REDIRECTS = 4
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_TEXT_CHARS = 6000
USER_AGENT = "BizAssistResearchBot/1.0 (+business profile research)"

# Internal pages most likely to describe the business.
INTERESTING_PATH_WORDS = (
    "about", "company", "story", "who-we-are", "product", "service", "solution", "shop",
    "menu", "pricing", "price", "catalog", "collection", "industr", "client", "customer",
    "location", "store", "contact", "team",
)


class WebsiteFetchError(RuntimeError):
    pass


@dataclass
class WebPage:
    url: str
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""
    links: list[str] = field(default_factory=list)


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise WebsiteFetchError("No website URL given.")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    try:
        parsed.port  # raises for junk like "javascript:alert(1)" once prefixed with https://
    except ValueError as exc:
        raise WebsiteFetchError("Website must be an http(s) URL.") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
        raise WebsiteFetchError("Website must be an http(s) URL.")
    return raw


async def _ensure_public_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebsiteFetchError("Only http(s) URLs can be fetched.")
    if parsed.port not in (None, 80, 443):
        raise WebsiteFetchError("Only default web ports can be fetched.")
    host = parsed.hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebsiteFetchError(f"Could not resolve {host}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise WebsiteFetchError(f"{host} does not resolve to a public address.")


async def fetch_page(url: str, *, client: httpx.AsyncClient | None = None) -> WebPage:
    """Fetch one HTML page, following redirects manually so each hop is re-validated."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": USER_AGENT})
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            await _ensure_public_host(current)
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise WebsiteFetchError("Redirect without a location.")
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    raise WebsiteFetchError(f"{current} returned HTTP {resp.status_code}.")
                if "html" not in resp.headers.get("content-type", "html").lower():
                    raise WebsiteFetchError(f"{current} is not an HTML page.")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        break
                return extract_page(str(resp.url), bytes(body[:MAX_BYTES]), resp.encoding or "utf-8")
        raise WebsiteFetchError("Too many redirects.")
    except httpx.HTTPError as exc:
        raise WebsiteFetchError(f"Could not fetch {url}: {exc.__class__.__name__}") from exc
    finally:
        if own_client:
            await client.aclose()


def extract_page(url: str, body: bytes, encoding: str = "utf-8") -> WebPage:
    try:
        doc = lxml_html.fromstring(body.decode(encoding, errors="replace"))
    except Exception as exc:
        raise WebsiteFetchError(f"Could not parse {url}.") from exc

    for bad in doc.xpath("//script|//style|//noscript|//svg|//template|//iframe"):
        bad.drop_tree()

    def first(xpath: str) -> str:
        found = doc.xpath(xpath)
        return " ".join(str(found[0]).split()) if found else ""

    title = first("//title/text()")
    description = first("//meta[@name='description']/@content") or first("//meta[@property='og:description']/@content")
    headings = [" ".join(h.text_content().split()) for h in doc.xpath("//h1|//h2|//h3")]
    headings = [h for h in headings if h][:30]
    text = " ".join(doc.text_content().split())[:MAX_TEXT_CHARS]

    host = urlparse(url).hostname
    links: list[str] = []
    for href in doc.xpath("//a/@href"):
        absolute = urljoin(url, str(href)).split("#", 1)[0]
        if urlparse(absolute).hostname == host and absolute not in links and absolute.rstrip("/") != url.rstrip("/"):
            links.append(absolute)

    return WebPage(url=url, title=title, description=description, headings=headings, text=text, links=links)


def pick_interesting_links(links: list[str], limit: int) -> list[str]:
    scored = []
    for link in links:
        path = urlparse(link).path.lower()
        score = sum(word in path for word in INTERESTING_PATH_WORDS)
        if score and not path.endswith((".pdf", ".jpg", ".png", ".zip")):
            scored.append((score, len(path), link))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [link for _, _, link in scored[:limit]]


async def fetch_page_with_browser(url: str) -> WebPage:
    """Render a page in headless Chromium (handles JavaScript-built sites).

    Same SSRF rules as fetch_page: every request the page makes (including redirects
    and sub-resources) is checked by a route guard, and the final URL is re-checked.
    """
    from app.research.browser import browser_service, random_user_agent

    await _ensure_public_host(url)

    async def render(browser):
        context = await browser.new_context(user_agent=random_user_agent(), locale="en-US")
        try:
            page = await context.new_page()
            allowed: dict[str, bool] = {}

            async def guard(route):
                request = route.request
                if request.resource_type in ("image", "media", "font"):
                    return await route.abort()
                parsed = urlparse(request.url)
                if parsed.scheme in ("data", "blob"):
                    return await route.continue_()
                host = parsed.hostname or ""
                if host not in allowed:
                    try:
                        await _ensure_public_host(request.url)
                        allowed[host] = True
                    except WebsiteFetchError:
                        allowed[host] = False
                        logger.info("research.website.blocked_request url=%s", request.url[:200])
                return await (route.continue_() if allowed[host] else route.abort())

            await page.route("**/*", guard)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if response is None:
                raise WebsiteFetchError(f"No response from {url}.")
            if response.status >= 400:
                raise WebsiteFetchError(f"{url} returned HTTP {response.status}.")
            if "html" not in (response.headers.get("content-type") or "html").lower():
                raise WebsiteFetchError(f"{url} is not an HTML page.")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # busy pages never go idle; the DOM is usable anyway
            return page.url, await page.content()
        finally:
            await context.close()

    try:
        final_url, html = await browser_service.run(render, timeout=45)
    except WebsiteFetchError:
        raise
    except Exception as exc:
        raise WebsiteFetchError(f"Could not load {url}: {exc.__class__.__name__}") from exc
    await _ensure_public_host(final_url)
    return extract_page(final_url, html.encode("utf-8")[:MAX_BYTES])


async def analyze_website(url: str, *, max_pages: int = 5, crawler: str = "browser") -> list[WebPage]:
    """Home page plus the most informative internal pages. Failures of extra pages are skipped.

    crawler="browser" renders pages with Playwright; "http" uses plain HTTP fetches.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        async def fetch(link: str) -> WebPage:
            if crawler == "browser":
                return await fetch_page_with_browser(link)
            return await fetch_page(link, client=client)

        home = await fetch(normalize_url(url))
        pages = [home]
        for link in pick_interesting_links(home.links, max_pages - 1):
            try:
                pages.append(await fetch(link))
            except WebsiteFetchError as exc:
                logger.info("research.website.skip url=%s reason=%s", link, exc)
        return pages
