"""Manual URL list discovery."""

from pathlib import Path
from typing import AsyncIterator

from doc_retrieval.config import DiscoveryConfig
from doc_retrieval.discovery.base import BaseDiscoverer, DiscoveredURL
from doc_retrieval.utils.url_utils import is_doc_url


class ManualDiscoverer(BaseDiscoverer):
    """Discover URLs from a manually provided list."""

    def __init__(self, base_url: str, config: DiscoveryConfig):
        super().__init__(base_url, config)

    async def discover(self) -> AsyncIterator[DiscoveredURL]:
        """Yield URLs from the configured file or stdin."""
        if not self.config.urls_file:
            raise ValueError("urls_file must be provided for manual discovery mode")

        urls_file = Path(self.config.urls_file)
        if not urls_file.exists():
            raise FileNotFoundError(f"URLs file not found: {urls_file}")

        count = 0
        max_pages = self.config.max_pages

        with open(urls_file, "r") as f:
            for line in f:
                url = line.strip()

                if not url or url.startswith("#"):
                    continue

                if max_pages > 0 and count >= max_pages:
                    return

                if not is_doc_url(url):
                    continue

                if not self.should_include(url):
                    continue

                count += 1
                yield DiscoveredURL(url=url)
