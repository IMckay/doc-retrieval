"""Base class for URL discovery."""

import re
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from pydantic import BaseModel

from doc_retrieval.config import DiscoveryConfig


class DiscoveredURL(BaseModel):
    """A discovered documentation URL."""

    url: str
    title: Optional[str] = None
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

    @abstractmethod
    async def discover(self) -> AsyncIterator[DiscoveredURL]:
        """Yield discovered URLs."""
        pass

    def should_include(self, url: str) -> bool:
        """Check if URL matches include/exclude patterns."""
        # Check exclude pattern first
        if self._exclude_re and self._exclude_re.search(url):
            return False

        # Check include pattern
        if self._include_re and not self._include_re.search(url):
            return False

        return True
