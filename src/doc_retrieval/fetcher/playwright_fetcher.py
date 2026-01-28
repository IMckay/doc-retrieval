"""Playwright-based fetcher for JavaScript-rendered pages."""

import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

from doc_retrieval.config import FetcherConfig
from doc_retrieval.fetcher.base import BaseFetcher, FetchResult


class PlaywrightFetcher(BaseFetcher):
    """Fetch pages using Playwright with JavaScript rendering."""

    def __init__(self, config: FetcherConfig):
        super().__init__(config)
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        """Initialize Playwright browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            user_agent=self.config.user_agent,
            viewport={"width": 1280, "height": 720},
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up Playwright resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a page with JavaScript rendering."""
        if not self._context:
            raise RuntimeError("Fetcher not initialized. Use 'async with' context manager.")

        page = await self._context.new_page()
        try:
            response = await page.goto(
                url,
                wait_until="networkidle",
                timeout=self.config.timeout_ms,
            )

            if response is None:
                return FetchResult(
                    url=url,
                    final_url=url,
                    html="",
                    status_code=0,
                    error="No response received",
                )

            # Wait for content to be visible
            await self._wait_for_content(page)

            # Additional wait if configured
            if self.config.wait_after_load_ms > 0:
                await asyncio.sleep(self.config.wait_after_load_ms / 1000)

            html = await page.content()

            return FetchResult(
                url=url,
                final_url=page.url,
                html=html,
                status_code=response.status,
            )

        except Exception as e:
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                error=str(e),
            )
        finally:
            await page.close()

    async def _wait_for_content(self, page) -> None:
        """Wait for main content to be visible."""
        selectors = [
            "article",
            "main",
            '[role="main"]',
            ".content",
            ".documentation",
            ".docs-content",
            ".markdown-body",
        ]

        for selector in selectors:
            try:
                await page.wait_for_selector(selector, timeout=5000)
                return
            except Exception:
                continue

        # If no specific content found, wait a bit for any JS to complete
        await asyncio.sleep(0.5)
