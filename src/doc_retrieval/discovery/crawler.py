"""Recursive crawler-based URL discovery."""

from typing import AsyncIterator, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from doc_retrieval.config import DiscoveryConfig
from doc_retrieval.discovery.base import BaseDiscoverer, DiscoveredURL
from doc_retrieval.utils.url_utils import is_doc_url, is_same_domain, normalize_url


class CrawlerDiscoverer(BaseDiscoverer):
    """Discover URLs by recursively following links."""

    def __init__(self, base_url: str, config: DiscoveryConfig):
        super().__init__(base_url, config)
        self._visited: Set[str] = set()

    async def discover(self) -> AsyncIterator[DiscoveredURL]:
        """Crawl the site starting from base_url."""
        queue: list[tuple[str, int]] = [(self.base_url, 0)]
        count = 0
        max_pages = self.config.max_pages
        max_depth = self.config.max_depth

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            while queue:
                url, depth = queue.pop(0)
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
                yield DiscoveredURL(url=url, depth=depth)

                # Fetch page and extract links
                try:
                    links = await self._extract_links(client, url)
                    for link in links:
                        link_normalized = normalize_url(link)
                        if link_normalized not in self._visited and is_same_domain(link, self.base_url):
                            queue.append((link, depth + 1))
                except Exception:
                    continue

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
                absolute = urljoin(final_url, href)
                parsed = urlparse(absolute)
                clean_url = parsed._replace(fragment="").geturl()
                links.append(clean_url)

            return links
        except Exception:
            return []
