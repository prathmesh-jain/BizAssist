"""Browser-based multi-engine web search (Playwright), with a factory like the engine registry
used elsewhere: engines are created once and reused so their rate limits and block
cooldowns persist across research runs."""
from app.research.search_engines.base import (
    BrowserSearchEngine,
    EngineResult,
    SearchEngineBlocked,
    SearchEngineFailed,
    normalize_url,
)
from app.research.search_engines.engines import BingSearchEngine, GoogleSearchEngine, YahooSearchEngine


class SearchEngineFactory:
    _engine_classes: dict[str, type[BrowserSearchEngine]] = {
        "yahoo": YahooSearchEngine,
        "bing": BingSearchEngine,
        "google": GoogleSearchEngine,
    }
    _instances: dict[str, BrowserSearchEngine] = {}

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._engine_classes)

    @classmethod
    def get(cls, name: str) -> BrowserSearchEngine:
        key = name.strip().lower()
        if key not in cls._engine_classes:
            raise ValueError(f"Unsupported search engine '{name}'. Available: {', '.join(cls.available())}")
        if key not in cls._instances:
            cls._instances[key] = cls._engine_classes[key]()
        return cls._instances[key]

    @classmethod
    def from_config(cls, names: str) -> list[BrowserSearchEngine]:
        """Engines in priority order from a comma-separated setting, e.g. "yahoo,bing,google"."""
        engines = [cls.get(n) for n in names.split(",") if n.strip()]
        if not engines:
            raise ValueError("No search engines configured.")
        return engines


__all__ = [
    "BrowserSearchEngine", "EngineResult", "SearchEngineBlocked", "SearchEngineFailed", "SearchEngineFactory",
    "normalize_url", "YahooSearchEngine", "BingSearchEngine", "GoogleSearchEngine",
]
