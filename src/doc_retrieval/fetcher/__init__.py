"""Page fetching with optional JavaScript rendering."""

from doc_retrieval.fetcher.base import BaseFetcher, FetchResult
from doc_retrieval.fetcher.http_fetcher import HttpFetcher
from doc_retrieval.fetcher.playwright_fetcher import PlaywrightFetcher

__all__ = [
    "BaseFetcher",
    "FetchResult",
    "PlaywrightFetcher",
    "HttpFetcher",
]
