"""Base class for URL discovery."""

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from pydantic import BaseModel

from doc_retrieval.config import DiscoveryConfig


class DiscoveredURL(BaseModel):
    """A discovered documentation URL."""

    url: str
    title: str | None = None
    priority: float = 0.5
    depth: int = 0


class BaseDiscoverer(ABC):
    """Abstract base class for URL discovery strategies."""

    def __init__(self, base_url: str, config: DiscoveryConfig):
        # Keep trailing slash if present - it's important for relative URL resolution
        self.base_url = base_url
        self.config = config
        self._include_re = re.compile(config.include_pattern) if config.include_pattern else None
        self._exclude_re = re.compile(config.exclude_pattern) if config.exclude_pattern else None

        # Auto-scope discovery to the base URL's path prefix.
        # For https://example.com/docs/api/v2/, scope = "/docs/api/v2".
        # When the path is "/" (site root), no scoping is applied.
        parsed = urlparse(base_url)
        base_path = parsed.path.rstrip("/")
        self._base_path = base_path if base_path else None

    @abstractmethod
    def discover(self) -> AsyncIterator[DiscoveredURL]:
        """Yield discovered URLs."""
        ...

    def should_include(self, url: str) -> bool:
        """Check if URL matches path scope and include/exclude patterns."""
        # Check path-prefix scope (skip for root base URLs)
        if self._base_path:
            parsed = urlparse(url)
            url_path = parsed.path.rstrip("/")
            if not url_path.startswith(self._base_path):
                return False

        if self._exclude_re and self._exclude_re.search(url):
            return False

        if self._include_re and not self._include_re.search(url):
            return False

        return True
