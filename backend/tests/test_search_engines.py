"""Browser search engines: link unwrapping, URL normalization, multi-engine merge. No network."""
import base64

import pytest

from app.research.search import BrowserSearchProvider, SearchError
from app.research.search_engines import (
    BingSearchEngine, EngineResult, GoogleSearchEngine, SearchEngineBlocked, SearchEngineFactory,
    YahooSearchEngine, normalize_url,
)

pytestmark = pytest.mark.no_db


def test_bing_and_yahoo_and_google_links_unwrap_to_destinations():
    target = "https://www.iranichaimumbai.com/kyani"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    bing = BingSearchEngine()
    assert bing.unwrap(f"https://www.bing.com/ck/a?!&&p=abc&ptn=3&u=a1{encoded}&ntb=1") == target
    assert bing.unwrap("https://www.bing.com/ck/a?!&&p=abc") is None
    assert bing.unwrap("https://example.com/x") == "https://example.com/x"

    yahoo = YahooSearchEngine()
    wrapped = "https://r.search.yahoo.com/_ylt=A;_ylu=B/RV=2/RE=1/RO=10/RU=https%3a%2f%2fexample.com%2fabout/RK=2/RS=x-"
    assert yahoo.unwrap(wrapped) == "https://example.com/about"

    assert GoogleSearchEngine().unwrap("https://www.google.com/url?q=https://example.com/a&sa=U") == "https://example.com/a"


def test_normalize_url_dedupes_cosmetic_differences():
    assert normalize_url("http://www.Example.com/menu/?utm_source=x&b=2&a=1#top") == normalize_url(
        "https://example.com/menu?a=1&b=2&fbclid=zzz"
    )
    assert normalize_url("https://example.com/") == normalize_url("https://example.com")
    assert normalize_url("https://example.com/a") != normalize_url("https://example.com/b")


def test_engine_own_links_are_filtered():
    yahoo = YahooSearchEngine()
    assert yahoo._is_own("https://search.yahoo.com/search?p=related")
    assert not yahoo._is_own("https://news.example.com/story")


def test_factory_returns_shared_instances_in_priority_order():
    engines = SearchEngineFactory.from_config(" bing, yahoo ")
    assert [e.name for e in engines] == ["bing", "yahoo"]
    assert SearchEngineFactory.get("yahoo") is SearchEngineFactory.get("YAHOO")
    with pytest.raises(ValueError):
        SearchEngineFactory.get("altavista")


class FakeEngine:
    def __init__(self, name, results=None, error=None):
        self.name, self._results, self._error = name, results or [], error

    async def search(self, query, *, max_results=8, country=None):
        if self._error:
            raise self._error
        return self._results


def r(url, engine):
    return EngineResult(title=url, url=url, snippet="", engine=engine)


async def test_multi_engine_merge_dedupes_in_priority_order_and_survives_failures():
    provider = BrowserSearchProvider([
        FakeEngine("google", error=SearchEngineBlocked("captcha")),
        FakeEngine("yahoo", [r("https://www.zomato.com/kyani", "yahoo"), r("https://kyani.example", "yahoo")]),
        FakeEngine("bing", [r("https://zomato.com/kyani/", "bing"), r("https://tripadvisor.example/k", "bing")]),
    ])
    results = await provider.search("kyani")
    assert [x.url for x in results] == [
        "https://www.zomato.com/kyani", "https://kyani.example", "https://tripadvisor.example/k",
    ]
    assert provider.name == "browser:google,yahoo,bing"


async def test_multi_engine_fails_only_when_every_engine_fails():
    provider = BrowserSearchProvider([
        FakeEngine("google", error=SearchEngineBlocked("captcha")),
        FakeEngine("bing", error=RuntimeError("timeout")),
    ])
    with pytest.raises(SearchError) as exc:
        await provider.search("kyani")
    assert "google" in str(exc.value) and "bing" in str(exc.value)
