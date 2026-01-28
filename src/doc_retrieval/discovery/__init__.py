"""URL discovery strategies for documentation sites."""

from doc_retrieval.discovery.base import BaseDiscoverer, DiscoveredURL
from doc_retrieval.discovery.sitemap import SitemapDiscoverer
from doc_retrieval.discovery.crawler import CrawlerDiscoverer
from doc_retrieval.discovery.manual import ManualDiscoverer

__all__ = [
    "BaseDiscoverer",
    "DiscoveredURL",
    "SitemapDiscoverer",
    "CrawlerDiscoverer",
    "ManualDiscoverer",
]
