"""Shared headless Chromium (Playwright) for web search and website crawling.

The browser runs on its own thread with its own event loop:
  - on Windows Playwright needs a Proactor loop to spawn the browser, while the API
    server runs a Selector loop (required by psycopg); a dedicated loop serves both;
  - a slow page never blocks the API's event loop.

Callers use `await browser_service.run(fn)`, where `fn(browser)` is a coroutine function
executed on the browser loop. One browser is launched lazily and reused.
"""
import asyncio
import concurrent.futures
import logging
import random
import sys
import threading
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Current desktop browsers. Requests identify as an ordinary browser; nothing here tries
# to defeat bot checks: engines that answer with a CAPTCHA are detected and skipped.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


class BrowserUnavailable(RuntimeError):
    pass


class BrowserService:
    def __init__(self, max_concurrent_pages: int = 3):
        self._max_pages = max_concurrent_pages
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()
        self._playwright = None
        self._browser = None
        self._launch_lock: asyncio.Lock | None = None
        self._pages: asyncio.Semaphore | None = None

    def _ensure_thread(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                self._thread = threading.Thread(target=self._thread_main, name="bizassist-browser", daemon=True)
                self._thread.start()
                self._ready.wait()
        return self._loop

    def _thread_main(self) -> None:
        loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._launch_lock = asyncio.Lock()
        self._pages = asyncio.Semaphore(self._max_pages)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    async def _get_browser(self):
        async with self._launch_lock:
            if self._browser is None or not self._browser.is_connected():
                try:
                    from playwright.async_api import async_playwright
                except ImportError as exc:
                    raise BrowserUnavailable("Playwright is not installed (pip install playwright).") from exc
                try:
                    if self._playwright is None:
                        self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(headless=True)
                except Exception as exc:
                    raise BrowserUnavailable(
                        f"Could not start Chromium ({exc.__class__.__name__}). Run: playwright install chromium"
                    ) from exc
                logger.info("Headless Chromium started for research")
            return self._browser

    async def _run_on_browser_loop(self, fn: Callable[[Any], Awaitable[T]]) -> T:
        browser = await self._get_browser()
        async with self._pages:
            return await fn(browser)

    async def run(self, fn: Callable[[Any], Awaitable[T]], *, timeout: float = 90) -> T:
        """Run `fn(browser)` on the browser thread and await its result from any loop."""
        loop = self._ensure_thread()
        future: concurrent.futures.Future = asyncio.run_coroutine_threadsafe(self._run_on_browser_loop(fn), loop)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout)
        except asyncio.TimeoutError:
            future.cancel()
            raise

    def shutdown(self) -> None:
        if self._loop is None:
            return

        async def _close():
            try:
                if self._browser is not None:
                    await self._browser.close()
                if self._playwright is not None:
                    await self._playwright.stop()
            finally:
                self._browser = self._playwright = None

        try:
            asyncio.run_coroutine_threadsafe(_close(), self._loop).result(timeout=10)
        except Exception:
            logger.warning("Browser shutdown did not complete cleanly", exc_info=True)
        self._loop.call_soon_threadsafe(self._loop.stop)


browser_service = BrowserService()
