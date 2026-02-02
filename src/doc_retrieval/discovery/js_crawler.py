"""JS-rendered crawler-based URL discovery using Playwright."""

import logging
from collections import deque
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from doc_retrieval.config import DiscoveryConfig
from doc_retrieval.discovery.base import BaseDiscoverer, DiscoveredURL
from doc_retrieval.utils.url_utils import is_doc_url, is_same_domain, normalize_url

logger = logging.getLogger(__name__)


class JsCrawlerDiscoverer(BaseDiscoverer):
    """Discover URLs by crawling with Playwright JS rendering.

    Unlike CrawlerDiscoverer which uses httpx (static HTML only), this
    discoverer renders pages with a headless browser to find links
    injected by JavaScript (SPAs, client-side routing).
    """

    def __init__(self, base_url: str, config: DiscoveryConfig):
        super().__init__(base_url, config)
        self._visited: set[str] = set()

    async def discover(self) -> AsyncIterator[DiscoveredURL]:
        """Crawl the site using Playwright, rendering JS on each page."""
        queue: deque[tuple[str, int]] = deque([(self.base_url, 0)])
        count = 0
        max_pages = self.config.max_pages
        max_depth = self.config.max_depth

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                )
                page = await context.new_page()

                while queue:
                    url, depth = queue.popleft()
                    normalized = normalize_url(url)

                    if normalized in self._visited:
                        continue
                    if depth > max_depth:
                        continue
                    if max_pages > 0 and count >= max_pages:
                        return

                    self._visited.add(normalized)

                    if not is_doc_url(url):
                        continue
                    if not self.should_include(url):
                        continue

                    count += 1
                    yield DiscoveredURL(url=normalized, depth=depth)

                    try:
                        links = await self._extract_links(page, url)
                        for link in links:
                            link_normalized = normalize_url(link)
                            if (
                                link_normalized not in self._visited
                                and is_same_domain(link, self.base_url)
                            ):
                                queue.append((link, depth + 1))
                    except Exception:
                        logger.debug(
                            "JS link extraction failed for %s", url, exc_info=True
                        )
                        continue

                await page.close()
                await context.close()
            finally:
                await browser.close()

    async def _extract_links(self, page, url: str) -> list[str]:
        """Navigate to a page, render JS, and extract links from the DOM."""
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(500)

            # Extract all <a href="..."> from the rendered DOM
            links_data = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(href => href.startsWith('http'))
            """)

            links = []
            for href in links_data:
                parsed = urlparse(href)
                clean_url = parsed._replace(fragment="").geturl()
                links.append(clean_url)

            return links
        except Exception:
            logger.debug("JS page navigation failed for %s", url, exc_info=True)
            return []
