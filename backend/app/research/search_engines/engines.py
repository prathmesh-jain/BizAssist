"""Yahoo, Bing and Google result-page readers.

Selectors reflect each engine's markup at the time of writing; if an engine changes
its page, update `result_selector` / `extract_js` here. In testing (Nov 2026) Yahoo
and Bing returned results to a headless browser; Google answered with a CAPTCHA.
"""
import base64
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from app.research.search_engines.base import BrowserSearchEngine


class YahooSearchEngine(BrowserSearchEngine):
    name = "yahoo"
    result_selector = "#web ol li"
    own_hosts = ("search.yahoo.com", "r.search.yahoo.com", "video.search.yahoo.com", "images.search.yahoo.com")
    extract_js = """() => [...document.querySelectorAll('#web ol li')].map(li => {
        const a = li.querySelector('h3 a') || li.querySelector('.compTitle a');
        if (!a) return null;
        return {
            href: a.href,
            title: (li.querySelector('h3') || a).innerText,
            snippet: (li.querySelector('.compText') || {}).innerText || '',
        };
    }).filter(Boolean)"""

    def build_url(self, query: str, country: str | None) -> str:
        return f"https://search.yahoo.com/search?p={quote_plus(query)}"

    def unwrap(self, href: str) -> str | None:
        # Some results are r.search.yahoo.com/.../RU=<encoded target>/RK=...
        if "r.search.yahoo.com" in href and "/RU=" in href:
            return unquote(href.split("/RU=", 1)[1].split("/R", 1)[0])
        return href


class BingSearchEngine(BrowserSearchEngine):
    name = "bing"
    result_selector = "li.b_algo h2 a"
    own_hosts = ("bing.com", "microsoft.com/bing", "go.microsoft.com")
    extract_js = """() => [...document.querySelectorAll('li.b_algo')].map(li => {
        const a = li.querySelector('h2 a');
        if (!a) return null;
        const snippet = li.querySelector('.b_caption p, .b_lineclamp2, .b_lineclamp3, .b_lineclamp4, p');
        return { href: a.href, title: a.innerText, snippet: snippet ? snippet.innerText : '' };
    }).filter(Boolean)"""

    def build_url(self, query: str, country: str | None) -> str:
        url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=en"
        return f"{url}&cc={country.upper()}" if country else url

    def unwrap(self, href: str) -> str | None:
        # bing.com/ck/a?...&u=a1<base64url(target)>
        parsed = urlparse(href)
        if parsed.hostname and parsed.hostname.endswith("bing.com") and parsed.path.startswith("/ck/"):
            encoded = (parse_qs(parsed.query).get("u") or [""])[0]
            if encoded.startswith("a1"):
                encoded = encoded[2:]
                try:
                    return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    return None
            return None
        return href


class GoogleSearchEngine(BrowserSearchEngine):
    name = "google"
    result_selector = "#search a:has(h3)"
    own_hosts = ("google.com", "google.co.in", "webcache.googleusercontent.com")
    extract_js = """() => [...document.querySelectorAll('#search a:has(h3)')].map(a => {
        const box = a.closest('.g, [data-hveid]');
        const snippet = box && box.querySelector('.VwiC3b, [data-sncf], [style*="-webkit-line-clamp"]');
        return { href: a.href, title: a.querySelector('h3').innerText, snippet: snippet ? snippet.innerText : '' };
    })"""

    def build_url(self, query: str, country: str | None) -> str:
        url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en"
        return f"{url}&gl={country.lower()}" if country else url

    def unwrap(self, href: str) -> str | None:
        parsed = urlparse(href)
        if parsed.path == "/url":
            return (parse_qs(parsed.query).get("q") or [None])[0]
        return href
