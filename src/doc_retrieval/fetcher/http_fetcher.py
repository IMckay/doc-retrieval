"""Simple HTTP fetcher for static pages."""


import httpx

from doc_retrieval.config import FetcherConfig
from doc_retrieval.fetcher.base import BaseFetcher, FetchResult


class HttpFetcher(BaseFetcher):
    """Simple HTTP fetcher without JavaScript rendering."""

    def __init__(self, config: FetcherConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
            timeout=self.config.timeout_ms / 1000,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up HTTP client."""
        if self._client:
            await self._client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a page via HTTP."""
        if not self._client:
            raise RuntimeError("Fetcher not initialized. Use 'async with' context manager.")

        try:
            response = await self._client.get(url)

            retry_after: float | None = None
            if response.status_code == 429:
                retry_after = self._parse_retry_after(
                    response.headers.get("retry-after")
                )

            return FetchResult(
                url=url,
                final_url=str(response.url),
                html=response.text,
                status_code=response.status_code,
                retry_after=retry_after,
            )

        except Exception as e:
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                error=str(e),
            )
