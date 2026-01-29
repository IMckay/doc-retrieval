"""Base class for page fetchers."""

import asyncio
import random
from abc import ABC, abstractmethod
from email.utils import parsedate_to_datetime

from pydantic import BaseModel

from doc_retrieval.config import FetcherConfig

_MAX_RETRY_DELAY = 60.0  # Never sleep longer than this on a single retry


class FetchResult(BaseModel):
    """Result of fetching a page."""

    url: str
    final_url: str  # After redirects
    html: str
    status_code: int
    error: str | None = None
    retry_after: float | None = None
    attempts: int = 1

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

    async def fetch_with_retry(
        self, url: str, max_retries: int = 3, base_delay: float = 1.0
    ) -> FetchResult:
        """Fetch with exponential backoff on transient errors."""
        result = FetchResult(url=url, final_url=url, html="", status_code=0, error="no attempts")
        for attempt in range(max_retries + 1):
            result = await self.fetch(url)
            result.attempts = attempt + 1
            if result.success:
                return result
            if not self._is_retryable(result):
                return result
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                if result.retry_after is not None:
                    delay = max(delay, result.retry_after)
                delay = min(delay, _MAX_RETRY_DELAY)
                await asyncio.sleep(delay)
        return result

    @staticmethod
    def _parse_retry_after(header_value: str | None) -> float | None:
        """Parse a Retry-After header value into seconds.

        Supports both delta-seconds (e.g. "120") and HTTP-date formats.
        Returns None if the header is missing or unparseable.
        """
        if not header_value:
            return None
        try:
            return max(0.0, float(header_value))
        except ValueError:
            pass
        try:
            from datetime import datetime, timezone

            dt = parsedate_to_datetime(header_value)
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, delta)
        except Exception:
            return None

    @staticmethod
    def _is_retryable(result: FetchResult) -> bool:
        """Check if a failed fetch should be retried."""
        # Retry on rate-limit or server errors
        if result.status_code == 429 or result.status_code >= 500:
            return True
        # Retry on connection/timeout errors (status_code 0 with an error message)
        if result.status_code == 0 and result.error:
            return True
        return False

    @abstractmethod
    async def __aenter__(self):
        """Async context manager entry."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass
