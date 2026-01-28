"""Base class for page fetchers."""

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from doc_retrieval.config import FetcherConfig


class FetchResult(BaseModel):
    """Result of fetching a page."""

    url: str
    final_url: str  # After redirects
    html: str
    status_code: int
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status_code >= 200 and self.status_code < 400 and not self.error


class BaseFetcher(ABC):
    """Abstract base class for page fetchers."""

    def __init__(self, config: FetcherConfig):
        self.config = config

    @abstractmethod
    async def fetch(self, url: str) -> FetchResult:
        """Fetch a page and return its HTML content."""
        pass

    @abstractmethod
    async def __aenter__(self):
        """Async context manager entry."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass
