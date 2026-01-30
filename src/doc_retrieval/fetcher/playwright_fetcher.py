"""Playwright-based fetcher for JavaScript-rendered pages."""

import asyncio
import logging

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from doc_retrieval.config import FetcherConfig
from doc_retrieval.fetcher.base import BaseFetcher, FetchResult

logger = logging.getLogger(__name__)


class PlaywrightFetcher(BaseFetcher):
    """Fetch pages using Playwright with JavaScript rendering."""

    def __init__(self, config: FetcherConfig):
        super().__init__(config)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page_pool: asyncio.Queue | None = None
        self._pool_size: int = 0

    async def __aenter__(self):
        """Initialize Playwright browser and pre-create page pool."""
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent=self.config.user_agent,
                viewport={"width": 1280, "height": 720},
            )
            self._page_pool = asyncio.Queue()
            for _ in range(self.config.page_pool_size):
                page = await self._context.new_page()
                await self._page_pool.put(page)
            self._pool_size = self.config.page_pool_size
        except Exception:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Drain page pool and clean up Playwright resources."""
        if self._page_pool:
            while not self._page_pool.empty():
                page = await self._page_pool.get()
                try:
                    await page.close()
                except Exception:
                    logger.debug("Failed to close page during cleanup", exc_info=True)
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
                    logger.debug("Failed to wait for redirected page: %s", url, exc_info=True)

            if self.config.wait_after_load_ms > 0:
                await asyncio.sleep(self.config.wait_after_load_ms / 1000)

            # Expand all collapsed <details> elements so content is in the DOM
            await page.evaluate(
                "document.querySelectorAll('details:not([open])')"
                ".forEach(d => d.setAttribute('open', ''))"
            )

            # Capture pre-click HTML as a safety snapshot.  Tab clicking can
            # crash Docusaurus React components; if that happens we fall back
            # to the pre-click content which has valid schema data.
            pre_click_html = await page.content() if self.config.click_tabs_selector else None

            if self.config.click_tabs_selector:
                await self._click_through_tabs(page)

            html = await page.content()

            if pre_click_html and self._is_crashed_page(html):
                html = pre_click_html

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
            logger.debug("Page reset failed, replacing page", exc_info=True)
            try:
                await page.close()
            except Exception:
                logger.debug("Failed to close broken page", exc_info=True)
            try:
                new_page = await self._context.new_page()
                await self._page_pool.put(new_page)
            except Exception:
                self._pool_size -= 1
                logger.warning(
                    "Failed to create replacement page — pool shrunk to %d",
                    self._pool_size,
                    exc_info=True,
                )
                if self._pool_size <= 0:
                    raise RuntimeError(
                        "Playwright page pool is empty — all pages lost"
                    )

    @staticmethod
    def _is_crashed_page(html: str) -> bool:
        """Detect if Docusaurus rendered a React error boundary crash."""
        return "This page crashed" in html

    async def _click_through_tabs(self, page) -> None:
        """Click target language tabs and snapshot each panel's code.

        The Docusaurus OpenAPI plugin uses a two-level tab hierarchy:
          Level 1 — language tabs (curl, python, go, …)
          Level 2 — library sub-tabs within a language (http.client, requests)

        We must handle these levels separately to avoid cross-level state
        contamination that crashes Docusaurus React components.

        Note: ``config.click_tabs_selector`` gates whether this method is
        called but is not used as a selector here — the two-level DOM
        traversal uses its own hard-coded selectors.
        """
        target_languages = ["curl", "python"]
        target_sub_tabs = {"python": ["http.client", "requests"]}

        try:
            captured = await page.evaluate(
                """async ([targetLangs, subTabMap]) => {
                    const containers = document.querySelectorAll(
                        '.openapi-tabs__code-container'
                    );
                    const results = [];
                    const wait = ms => new Promise(r => setTimeout(r, ms));

                    for (let ci = 0; ci < containers.length; ci++) {
                        const c = containers[ci];
                        // Level 1: the first tablist holds language tabs
                        const langTablist = c.querySelector('[role="tablist"]');
                        if (!langTablist) continue;
                        const langTabs = langTablist.querySelectorAll(
                            ':scope > [role="tab"]'
                        );

                        for (const lang of targetLangs) {
                            let langTab = null;
                            for (const t of langTabs) {
                                if (t.textContent.trim().toLowerCase() === lang) {
                                    langTab = t;
                                    break;
                                }
                            }
                            if (!langTab) continue;

                            langTab.click();
                            await wait(200);

                            // Check for level 2 sub-tabs
                            const subs = subTabMap[lang];
                            if (subs && subs.length > 0) {
                                // Find the nested tabpanel, then its tablist
                                const langPanel = c.querySelector(
                                    '[role="tabpanel"]'
                                );
                                const subTablist = langPanel
                                    ? langPanel.querySelector('[role="tablist"]')
                                    : null;

                                if (subTablist) {
                                    const subTabs = subTablist.querySelectorAll(
                                        ':scope > [role="tab"]'
                                    );
                                    for (const sub of subs) {
                                        let subTab = null;
                                        for (const st of subTabs) {
                                            if (st.textContent.trim()
                                                    .toLowerCase() === sub) {
                                                subTab = st;
                                                break;
                                            }
                                        }
                                        if (!subTab) continue;

                                        subTab.click();
                                        await wait(200);

                                        // Capture the innermost panel
                                        const innerPanel = langPanel
                                            .querySelector('[role="tabpanel"]');
                                        if (innerPanel
                                                && innerPanel.querySelector('code')
                                        ) {
                                            results.push([
                                                ci, sub, innerPanel.outerHTML
                                            ]);
                                        }
                                    }
                                } else {
                                    // No sub-tabs; capture the language panel
                                    const panel = c.querySelector(
                                        '[role="tabpanel"]'
                                    );
                                    if (panel && panel.querySelector('code')) {
                                        results.push([
                                            ci, lang, panel.outerHTML
                                        ]);
                                    }
                                }
                            } else {
                                // No sub-tabs expected; capture the panel
                                const panel = c.querySelector(
                                    '[role="tabpanel"]'
                                );
                                if (panel && panel.querySelector('code')) {
                                    results.push([ci, lang, panel.outerHTML]);
                                }
                            }
                        }
                    }
                    return results;
                }""",
                [target_languages, target_sub_tabs],
            )

            # Inject captured panels as hidden divs so the extractor can read
            # code samples for every language.  The HTML originates from the
            # page's own rendered DOM (same-origin), not external input.
            if captured:
                await page.evaluate(
                    """(items) => {
                        const wrap = document.createElement('div');
                        const containers = document.querySelectorAll(
                            '.openapi-tabs__code-container'
                        );
                        for (const [ci, label, panelHtml] of items) {
                            const div = document.createElement('div');
                            div.className = 'doc-retrieval-captured-tab';
                            div.dataset.tabLabel = label;
                            div.style.display = 'none';
                            wrap.innerHTML = panelHtml;
                            while (wrap.firstChild) {
                                div.appendChild(wrap.firstChild);
                            }
                            containers[ci].appendChild(div);
                        }
                    }""",
                    captured,
                )
        except Exception:
            logger.debug("Tab click-through failed", exc_info=True)

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
                logger.debug(
                    "Pattern wait_selector '%s' not found, trying fallbacks",
                    self.config.wait_selector,
                )

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
                logger.debug("Content selector '%s' not found", selector)
                continue

        # If no specific content found, wait a bit for any JS to complete
        await asyncio.sleep(0.5)
