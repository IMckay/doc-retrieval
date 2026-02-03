"""Recursive crawler-based URL discovery."""

import asyncio
import logging
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from doc_retrieval.config import DiscoveryConfig
from doc_retrieval.discovery.base import BaseDiscoverer, DiscoveredURL
from doc_retrieval.utils.url_utils import is_doc_url, is_same_domain, normalize_url

logger = logging.getLogger(__name__)


class CrawlerDiscoverer(BaseDiscoverer):
    """Discover URLs by recursively following links with concurrent fetching."""

    def __init__(self, base_url: str, config: DiscoveryConfig):
        super().__init__(base_url, config)
        self._visited: set[str] = set()
        self._semaphore = asyncio.Semaphore(config.max_concurrent_discovery)

    async def discover(self) -> AsyncIterator[DiscoveredURL]:
        """Crawl the site using breadth-first concurrent fetching."""
        current_level: list[tuple[str, int]] = [(self.base_url, 0)]
        count = 0
        max_pages = self.config.max_pages
        max_depth = self.config.max_depth

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            while current_level:
                # Filter URLs for this level: skip visited, over depth, non-doc, excluded
                urls_to_process = []
                for url, depth in current_level:
                    normalized = normalize_url(url)

                    if normalized in self._visited:
                        continue
                    if depth > max_depth:
                        continue

                    self._visited.add(normalized)

                    if not is_doc_url(url):
                        continue
                    if not self.should_include(url):
                        continue

                    urls_to_process.append((normalized, depth))

                if not urls_to_process:
                    break

                # Fetch all URLs at this depth concurrently, yielding as each completes
                tasks = [
                    asyncio.create_task(self._fetch_and_extract(client, url, depth))
                    for url, depth in urls_to_process
                ]

                next_level: list[tuple[str, int]] = []

                for coro in asyncio.as_completed(tasks):
                    url, depth, links = await coro

                    count += 1
                    yield DiscoveredURL(url=url, depth=depth)

                    if max_pages > 0 and count >= max_pages:
                        # Cancel remaining tasks
                        for task in tasks:
                            task.cancel()
                        return

                    # Add child links to next level
                    for link in links:
                        link_normalized = normalize_url(link)
                        if (
                            link_normalized not in self._visited
                            and is_same_domain(link, self.base_url)
                        ):
                            next_level.append((link, depth + 1))

                current_level = next_level

    async def _fetch_and_extract(
        self, client: httpx.AsyncClient, url: str, depth: int
    ) -> tuple[str, int, list[str]]:
        """Fetch a URL and extract links, with semaphore control.

        Returns (url, depth, links) tuple so caller can identify which URL completed.
        """
        async with self._semaphore:
            links = await self._extract_links(client, url)
            return (url, depth, links)

    async def _extract_links(self, client: httpx.AsyncClient, url: str) -> list[str]:
        """Extract all links from a page."""
        try:
            response = await client.get(url)
            response.raise_for_status()

            # Use the final URL after redirects as the base for relative links
            final_url = str(response.url)

            soup = BeautifulSoup(response.text, "lxml")
            links = []

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if isinstance(href, list):
                    href = href[0]

                # Skip non-HTTP links and malformed hrefs
                href = href.strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                # Skip hrefs with obvious corruption (quotes, spaces in wrong places)
                if "'" in href or href.startswith(" ") or "%20" in href.split("/")[0]:
                    continue

                absolute = urljoin(final_url, href)
                parsed = urlparse(absolute)

                # Only keep http/https links
                if parsed.scheme not in ("http", "https"):
                    continue

                clean_url = parsed._replace(fragment="").geturl()
                links.append(clean_url)

            return links
        except Exception:
            logger.debug("Link extraction failed for %s", url, exc_info=True)
            return []
