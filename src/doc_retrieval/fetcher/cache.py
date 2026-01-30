"""HTTP response cache with ETag/Last-Modified support."""

import hashlib
import json
import time
from pathlib import Path

from doc_retrieval.fetcher.base import FetchResult


class CacheEntry:
    """Metadata stored alongside a cached response."""

    def __init__(
        self,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
        fetched_at: float = 0.0,
        status_code: int = 200,
        final_url: str = "",
    ):
        self.url = url
        self.etag = etag
        self.last_modified = last_modified
        self.fetched_at = fetched_at or time.time()
        self.status_code = status_code
        self.final_url = final_url or url

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "fetched_at": self.fetched_at,
            "status_code": self.status_code,
            "final_url": self.final_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CacheEntry":
        return cls(
            url=data["url"],
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            fetched_at=data.get("fetched_at", 0.0),
            status_code=data.get("status_code", 200),
            final_url=data.get("final_url", data["url"]),
        )


class ResponseCache:
    """Disk-based HTTP response cache.

    Stores fetched HTML with ETag/Last-Modified metadata for conditional
    requests on subsequent runs.
    """

    def __init__(self, cache_dir: Path, ttl_seconds: float = 3600.0):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self._hits = 0
        self._misses = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def _url_hash(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:24]

    def _html_path(self, url_hash: str) -> Path:
        return self.cache_dir / f"{url_hash}.html"

    def _meta_path(self, url_hash: str) -> Path:
        return self.cache_dir / f"{url_hash}.meta.json"

    def get(self, url: str) -> tuple[CacheEntry | None, str | None]:
        """Look up a cached response.

        Returns (entry, html) if cached and not expired, else (entry, None).
        The entry is returned even when expired so conditional headers can be sent.
        """
        url_hash = self._url_hash(url)
        meta_path = self._meta_path(url_hash)
        html_path = self._html_path(url_hash)

        if not meta_path.exists() or not html_path.exists():
            self._misses += 1
            return None, None

        try:
            entry = CacheEntry.from_dict(json.loads(meta_path.read_text()))
        except (json.JSONDecodeError, KeyError):
            self._misses += 1
            return None, None

        html = html_path.read_text(encoding="utf-8")

        # Check TTL (0 = no expiry)
        if self.ttl_seconds > 0:
            age = time.time() - entry.fetched_at
            if age > self.ttl_seconds:
                # Expired — return entry for conditional headers, but no html
                self._misses += 1
                return entry, None

        self._hits += 1
        return entry, html

    def conditional_headers(self, entry: CacheEntry | None) -> dict[str, str]:
        """Build conditional request headers from a cache entry."""
        headers: dict[str, str] = {}
        if entry:
            if entry.etag:
                headers["If-None-Match"] = entry.etag
            if entry.last_modified:
                headers["If-Modified-Since"] = entry.last_modified
        return headers

    def put(self, url: str, result: FetchResult) -> None:
        """Store a fetch result in the cache."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        url_hash = self._url_hash(url)

        entry = CacheEntry(
            url=url,
            etag=result.etag,
            last_modified=result.last_modified,
            status_code=result.status_code,
            final_url=result.final_url,
        )

        self._html_path(url_hash).write_text(result.html, encoding="utf-8")
        self._meta_path(url_hash).write_text(
            json.dumps(entry.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def make_cached_result(self, url: str, entry: CacheEntry, html: str) -> FetchResult:
        """Create a FetchResult from cached data."""
        return FetchResult(
            url=url,
            final_url=entry.final_url,
            html=html,
            status_code=entry.status_code,
            etag=entry.etag,
            last_modified=entry.last_modified,
        )
