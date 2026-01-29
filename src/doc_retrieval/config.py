"""Configuration management with Pydantic models."""

from enum import Enum
from pathlib import Path

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
    include_pattern: str | None = None
    exclude_pattern: str | None = None
    urls_file: Path | None = None


class FetcherConfig(BaseModel):
    """Configuration for page fetching."""

    use_js: bool = True
    timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    user_agent: str = "DocRetrieval/0.1 (Documentation Scraper)"
    wait_after_load_ms: int = Field(default=1000, ge=0, le=10000)
    wait_selector: str | None = None
    wait_time_ms: int = Field(default=0, ge=0, le=30000)
    click_tabs_selector: str | None = None
    page_pool_size: int = Field(default=5, ge=1, le=20)


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
            '[class*="skipToContent"]',
            'a[href="#__docusaurus_skipToContent_fallback"]',
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

    delay_seconds: float = Field(default=0.1, ge=0.0, le=60.0)
    max_concurrent: int = Field(default=5, ge=1, le=20)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_base_delay: float = Field(default=1.0, ge=0.1, le=30.0)


class AppConfig(BaseModel):
    """Main application configuration."""

    base_url: str
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    fetcher: FetcherConfig = Field(default_factory=FetcherConfig)
    extractor: ExtractorConfig = Field(default_factory=ExtractorConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    pattern: str | None = None  # Site pattern preset name
    verbose: bool = False
    skip_urls: Path | None = None

    @classmethod
    def from_toml(cls, path: Path) -> "AppConfig":
        """Load config from a TOML file."""
        try:
            import tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[import-not-found]
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data)

    def to_toml(self) -> str:
        """Serialize config to TOML format."""
        data = self.model_dump(mode="json", exclude_defaults=True)
        return _dict_to_toml(data)


def _toml_value(v: object) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v}"
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, list):
        items = ", ".join(_toml_value(i) for i in v)
        return f"[{items}]"
    return f'"{v}"'


def _dict_to_toml(data: dict, prefix: str = "") -> str:
    """Convert a nested dict to TOML string (2 levels deep max)."""
    lines: list[str] = []
    # Emit top-level scalar keys first
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_value(v)}")
    # Emit table sections
    for k, v in data.items():
        if isinstance(v, dict):
            section = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            lines.append(f"\n[{section}]")
            for sk, sv in v.items():
                lines.append(f"{sk} = {_toml_value(sv)}")
    return "\n".join(lines) + "\n"
