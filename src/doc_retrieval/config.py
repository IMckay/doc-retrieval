"""Configuration management with Pydantic models."""

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class DiscoveryMode(str, Enum):
    """URL discovery strategy."""

    SITEMAP = "sitemap"
    CRAWL = "crawl"
    MANUAL = "manual"


class OutputMode(str, Enum):
    """Output format mode."""

    SINGLE = "single"
    MULTI = "multi"


class DiscoveryConfig(BaseModel):
    """Configuration for URL discovery."""

    mode: DiscoveryMode = DiscoveryMode.SITEMAP
    max_depth: int = Field(default=3, ge=1, le=10)
    max_pages: int = Field(default=0, ge=0)  # 0 = unlimited
    include_pattern: Optional[str] = None
    exclude_pattern: Optional[str] = None
    urls_file: Optional[Path] = None


class FetcherConfig(BaseModel):
    """Configuration for page fetching."""

    use_js: bool = True
    timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    user_agent: str = "DocRetrieval/0.1 (Documentation Scraper)"
    wait_after_load_ms: int = Field(default=1000, ge=0, le=10000)


class ExtractorConfig(BaseModel):
    """Configuration for content extraction."""

    content_selectors: list[str] = Field(
        default_factory=lambda: [
            "article",
            "main",
            '[role="main"]',
            ".content",
            ".documentation",
            ".docs-content",
            ".markdown-body",
        ]
    )
    remove_selectors: list[str] = Field(
        default_factory=lambda: [
            "nav",
            "header",
            "footer",
            ".navigation",
            ".nav",
            ".navbar",
            ".sidebar",
            ".toc",
            ".table-of-contents",
            ".breadcrumb",
            ".breadcrumbs",
            ".edit-page",
            ".edit-on-github",
            ".page-nav",
            ".pagination",
            ".comments",
            ".advertisement",
            "script",
            "style",
            "noscript",
            '[role="navigation"]',
            '[role="banner"]',
        ]
    )
    min_content_length: int = Field(default=100, ge=0)
    include_tables: bool = True
    include_images: bool = True
    include_links: bool = True


class OutputConfig(BaseModel):
    """Configuration for output."""

    mode: OutputMode = OutputMode.SINGLE
    path: Path = Path("./output/output.md")
    include_metadata: bool = True
    include_toc: bool = True


class RateLimitConfig(BaseModel):
    """Configuration for rate limiting."""

    delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    max_concurrent: int = Field(default=3, ge=1, le=10)


class AppConfig(BaseModel):
    """Main application configuration."""

    base_url: str
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    fetcher: FetcherConfig = Field(default_factory=FetcherConfig)
    extractor: ExtractorConfig = Field(default_factory=ExtractorConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    pattern: Optional[str] = None  # Site pattern preset name
    verbose: bool = False
