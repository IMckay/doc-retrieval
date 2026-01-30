"""Sitemap-based URL discovery."""

import logging
from collections.abc import AsyncIterator
from urllib.parse import urljoin

import httpx
from usp.tree import sitemap_tree_for_homepage  # type: ignore[import-untyped]

from doc_retrieval.config import DiscoveryConfig
from doc_retrieval.discovery.base import BaseDiscoverer, DiscoveredURL
from doc_retrieval.utils.url_utils import is_doc_url

logger = logging.getLogger(__name__)


class SitemapDiscoverer(BaseDiscoverer):
    """Discover URLs from sitemap.xml."""

    def __init__(self, base_url: str, config: DiscoveryConfig):
        super().__init__(base_url, config)

    async def discover(self) -> AsyncIterator[DiscoveredURL]:
        """Parse sitemap and yield documentation URLs."""
        count = 0
        max_pages = self.config.max_pages

        try:
            tree = sitemap_tree_for_homepage(self.base_url)

            for page in tree.all_pages():
                url = page.url

                # Check if we've hit the limit
                if max_pages > 0 and count >= max_pages:
                    return

                # Filter non-doc URLs
                if not is_doc_url(url):
                    continue

                # Apply include/exclude patterns
                if not self.should_include(url):
                    continue

                count += 1
                yield DiscoveredURL(
                    url=url,
                    priority=page.priority if page.priority else 0.5,
                )

        except Exception:
            logger.debug("Primary sitemap parsing failed", exc_info=True)
            # If sitemap fails, try common sitemap locations
            for sitemap_path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/"]:
                try:
                    async for discovered in self._try_sitemap(sitemap_path, count, max_pages):
                        yield discovered
                        count += 1
                        if max_pages > 0 and count >= max_pages:
                            return
                    break
                except Exception:
                    logger.debug("Fallback sitemap %s failed", sitemap_path, exc_info=True)
                    continue

    async def _try_sitemap(
        self, path: str, current_count: int, max_pages: int
    ) -> AsyncIterator[DiscoveredURL]:
        """Try to fetch and parse a specific sitemap URL."""
        sitemap_url = urljoin(self.base_url, path)

        async with httpx.AsyncClient() as client:
            response = await client.get(sitemap_url, follow_redirects=True)
            response.raise_for_status()

            from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]

            root = fromstring(response.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            for url_elem in root.findall(".//sm:url", ns):
                loc = url_elem.find("sm:loc", ns)
                if loc is not None and loc.text:
                    url = loc.text.strip()

                    if not is_doc_url(url):
                        continue

                    if not self.should_include(url):
                        continue

                    priority_elem = url_elem.find("sm:priority", ns)
                    priority = 0.5
                    if priority_elem is not None and priority_elem.text:
                        try:
                            priority = float(priority_elem.text)
                        except ValueError:
                            logger.debug(
                                "Non-numeric sitemap priority: %s", priority_elem.text
                            )

                    yield DiscoveredURL(url=url, priority=priority)
