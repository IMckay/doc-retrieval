"""Playwright-based fetcher for JavaScript-rendered pages."""

import asyncio

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from doc_retrieval.config import FetcherConfig
from doc_retrieval.fetcher.base import BaseFetcher, FetchResult


class PlaywrightFetcher(BaseFetcher):
    """Fetch pages using Playwright with JavaScript rendering."""

    def __init__(self, config: FetcherConfig):
        super().__init__(config)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page_pool: asyncio.Queue | None = None

    async def __aenter__(self):
        """Initialize Playwright browser and pre-create page pool."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            user_agent=self.config.user_agent,
            viewport={"width": 1280, "height": 720},
        )
        self._page_pool = asyncio.Queue()
        for _ in range(self.config.page_pool_size):
            page = await self._context.new_page()
            await self._page_pool.put(page)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Drain page pool and clean up Playwright resources."""
        if self._page_pool:
            while not self._page_pool.empty():
                page = await self._page_pool.get()
                try:
                    await page.close()
                except Exception:
                    pass
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a page with JavaScript rendering using pooled pages."""
        if not self._context or not self._page_pool:
            raise RuntimeError("Fetcher not initialized. Use 'async with' context manager.")

        page = await self._page_pool.get()
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

            await self._wait_for_content(page)

            # Detect client-side redirects (SPA navigation, meta refresh).
            # If the URL changed after initial load, re-wait for content
            # on the new page.
            if page.url != url:
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    await self._wait_for_content(page)
                except Exception:
                    pass

            if self.config.wait_after_load_ms > 0:
                await asyncio.sleep(self.config.wait_after_load_ms / 1000)

            # Expand all collapsed <details> elements so content is in the DOM
            await page.evaluate(
                "document.querySelectorAll('details:not([open])')"
                ".forEach(d => d.setAttribute('open', ''))"
            )

            if self.config.click_tabs_selector:
                await self._click_through_tabs(page)

            html = await page.content()

            retry_after: float | None = None
            if response.status == 429:
                retry_after = self._parse_retry_after(
                    response.headers.get("retry-after")
                )

            return FetchResult(
                url=url,
                final_url=page.url,
                html=html,
                status_code=response.status,
                retry_after=retry_after,
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
            await self._return_page_to_pool(page)

    async def _return_page_to_pool(self, page) -> None:
        """Reset a page and return it to the pool, replacing it if broken."""
        assert self._page_pool is not None
        assert self._context is not None
        try:
            await page.goto("about:blank", wait_until="load", timeout=5000)
            await self._page_pool.put(page)
        except Exception:
            # Page is broken — close it and create a fresh replacement
            try:
                await page.close()
            except Exception:
                pass
            try:
                new_page = await self._context.new_page()
                await self._page_pool.put(new_page)
            except Exception:
                pass

    async def _click_through_tabs(self, page) -> None:
        """Click target language tabs and snapshot each panel's code.

        The Docusaurus OpenAPI plugin only renders one language panel at a
        time (clicking a tab replaces the previous panel), so we click each
        desired tab, wait for React to re-render, capture the panel HTML,
        and inject all captured panels as hidden elements.

        Uses a single in-browser JS evaluation to click all tabs and capture
        panels, minimizing Python-to-browser round-trips.
        """
        target_labels = ["curl", "python", "http.client", "requests", "bash"]
        try:
            # Single JS call: click through all tabs in all containers,
            # waiting for React re-renders in-browser via setTimeout.
            captured = await page.evaluate(
                """async ([selector, labels]) => {
                    const containers = document.querySelectorAll(
                        '.openapi-tabs__code-container'
                    );
                    const results = [];
                    const tabSel = selector.replace(
                        '.openapi-tabs__code-container ', ''
                    );
                    for (let ci = 0; ci < containers.length; ci++) {
                        const c = containers[ci];
                        for (const label of labels) {
                            const tabs = c.querySelectorAll(tabSel);
                            let clicked = false;
                            for (const tab of tabs) {
                                if (tab.textContent.trim().toLowerCase()
                                        === label) {
                                    tab.click();
                                    clicked = true;
                                    break;
                                }
                            }
                            if (!clicked) continue;
                            await new Promise(r => setTimeout(r, 150));
                            const p = c.querySelector('[role="tabpanel"]');
                            if (p && p.querySelector('code')) {
                                results.push([ci, label, p.outerHTML]);
                            }
                        }
                    }
                    return results;
                }""",
                [self.config.click_tabs_selector, target_labels],
            )

            # Inject all captured panels as hidden divs so the extractor
            # can read code samples for every language.  The HTML comes from
            # the page's own rendered DOM (same-origin), not external input.
            if captured:
                await page.evaluate(
                    """(items) => {
                        const containers = document.querySelectorAll(
                            '.openapi-tabs__code-container'
                        );
                        for (const [ci, label, html] of items) {
                            const tpl = document.createElement('template');
                            tpl.innerHTML = html;
                            const div = document.createElement('div');
                            div.className = 'doc-retrieval-captured-tab';
                            div.setAttribute('data-tab-label', label);
                            div.style.display = 'none';
                            div.appendChild(tpl.content);
                            containers[ci].appendChild(div);
                        }
                    }""",
                    captured,
                )
        except Exception:
            pass

    async def _wait_for_content(self, page) -> None:
        """Wait for main content to be visible."""
        # Try the pattern-configured wait_selector first (highest priority)
        if self.config.wait_selector:
            try:
                await page.wait_for_selector(
                    self.config.wait_selector, timeout=10000
                )
                # Additional wait if the pattern requests it (e.g. for lazy-loaded schema)
                if self.config.wait_time_ms > 0:
                    await asyncio.sleep(self.config.wait_time_ms / 1000)
                return
            except Exception:
                pass

        # Fall back to generic content selectors
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
