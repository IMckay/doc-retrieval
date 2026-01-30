"""Simple HTTP fetcher for static pages."""

from pathlib import Path

import httpx

from doc_retrieval.config import AuthConfig, FetcherConfig
from doc_retrieval.fetcher.base import BaseFetcher, FetchResult


class HttpFetcher(BaseFetcher):
    """Simple HTTP fetcher without JavaScript rendering."""

    def __init__(self, config: FetcherConfig, auth: AuthConfig | None = None):
        super().__init__(config, auth)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        """Initialize HTTP client."""
        headers = {"User-Agent": self.config.user_agent}
        headers.update(self.auth.headers)

        cookies = dict(self.auth.cookies)
        if self.auth.cookie_file and self.auth.cookie_file.exists():
            cookies.update(_parse_cookie_file(self.auth.cookie_file))

        self._client = httpx.AsyncClient(
            headers=headers,
            cookies=cookies,
            follow_redirects=True,
            timeout=self.config.timeout_ms / 1000,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up HTTP client."""
        if self._client:
            await self._client.aclose()

    async def fetch(
        self,
        url: str,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch a page via HTTP."""
        if not self._client:
            raise RuntimeError("Fetcher not initialized. Use 'async with' context manager.")

        try:
            response = await self._client.get(url, headers=extra_headers or {})

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
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )

        except Exception as e:
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                error=str(e),
            )


def _parse_cookie_file(path: Path) -> dict[str, str]:
    """Parse a Netscape-format cookie jar file into name=value pairs."""
    cookies: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies
