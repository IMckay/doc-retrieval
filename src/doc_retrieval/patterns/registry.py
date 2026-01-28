"""Site-specific extraction pattern registry."""

from typing import Optional

from pydantic import BaseModel


class SitePattern(BaseModel):
    """Configuration for a specific documentation site type."""

    name: str
    description: str

    # Content selectors (in order of preference)
    content_selectors: list[str] = []

    # Elements to remove
    remove_selectors: list[str] = []

    # URL patterns
    doc_url_patterns: list[str] = []
    exclude_url_patterns: list[str] = []

    # JS rendering requirements
    requires_js: bool = True
    wait_selector: Optional[str] = None
    wait_time_ms: int = 0


# Built-in patterns for common documentation frameworks
DOCUSAURUS_PATTERN = SitePattern(
    name="docusaurus",
    description="Docusaurus documentation sites",
    content_selectors=[
        "article.markdown",
        ".docMainContent",
        "main .container article",
        '[class*="docItemContainer"]',
    ],
    remove_selectors=[
        ".theme-doc-sidebar-container",
        ".pagination-nav",
        ".theme-doc-toc-mobile",
        ".theme-doc-footer",
        ".theme-edit-this-page",
        '[class*="tocCollapsible"]',
    ],
    requires_js=True,
    wait_selector="article.markdown",
)

GITBOOK_PATTERN = SitePattern(
    name="gitbook",
    description="GitBook documentation sites",
    content_selectors=[
        '[data-testid="page.contentEditor"]',
        ".markdown-section",
        ".page-inner",
        "main",
    ],
    remove_selectors=[
        ".book-summary",
        ".navigation",
        ".page-footer",
        '[data-testid="page.tableOfContents"]',
    ],
    requires_js=True,
    wait_selector='[data-testid="page.contentEditor"], .markdown-section',
)

READTHEDOCS_PATTERN = SitePattern(
    name="readthedocs",
    description="Read the Docs sites",
    content_selectors=[
        '[role="main"]',
        ".document",
        ".rst-content",
        ".body",
    ],
    remove_selectors=[
        ".wy-nav-side",
        ".rst-versions",
        ".wy-breadcrumbs",
        ".headerlink",
        '[role="navigation"]',
    ],
    requires_js=False,
)

MKDOCS_PATTERN = SitePattern(
    name="mkdocs",
    description="MkDocs documentation sites",
    content_selectors=[
        '[role="main"]',
        ".md-content",
        "article",
        ".content",
    ],
    remove_selectors=[
        ".md-sidebar",
        ".md-header",
        ".md-footer",
        ".md-tabs",
        ".md-source",
    ],
    requires_js=False,
    wait_selector='[role="main"]',
)

SPHINX_PATTERN = SitePattern(
    name="sphinx",
    description="Sphinx documentation sites",
    content_selectors=[
        '[role="main"]',
        ".document",
        ".body",
        ".section",
    ],
    remove_selectors=[
        ".sphinxsidebar",
        ".related",
        ".footer",
        ".headerlink",
    ],
    requires_js=False,
)

VITEPRESS_PATTERN = SitePattern(
    name="vitepress",
    description="VitePress documentation sites",
    content_selectors=[
        ".vp-doc",
        "main .content",
        ".content-container",
    ],
    remove_selectors=[
        ".VPSidebar",
        ".VPNav",
        ".VPFooter",
        ".aside",
        ".edit-link",
        ".prev-next",
    ],
    requires_js=True,
    wait_selector=".vp-doc",
)


class PatternRegistry:
    """Registry of site-specific patterns."""

    _patterns: dict[str, SitePattern] = {
        "docusaurus": DOCUSAURUS_PATTERN,
        "gitbook": GITBOOK_PATTERN,
        "readthedocs": READTHEDOCS_PATTERN,
        "mkdocs": MKDOCS_PATTERN,
        "sphinx": SPHINX_PATTERN,
        "vitepress": VITEPRESS_PATTERN,
    }

    @classmethod
    def register(cls, pattern: SitePattern) -> None:
        """Register a new pattern."""
        cls._patterns[pattern.name] = pattern

    @classmethod
    def get(cls, name: str) -> Optional[SitePattern]:
        """Get a pattern by name."""
        return cls._patterns.get(name)

    @classmethod
    def list_patterns(cls) -> list[SitePattern]:
        """List all registered patterns."""
        return list(cls._patterns.values())

    @classmethod
    def detect(cls, url: str, html: str) -> Optional[SitePattern]:
        """Auto-detect site type from URL or HTML content."""
        url_lower = url.lower()
        html_lower = html.lower() if html else ""

        # Check URL patterns
        if "readthedocs" in url_lower or ".rtfd." in url_lower:
            return cls._patterns.get("readthedocs")

        # Check HTML content for framework signatures
        if "docusaurus" in html_lower or "__docusaurus" in html:
            return cls._patterns.get("docusaurus")

        if "gitbook" in html_lower or "data-testid=\"page." in html:
            return cls._patterns.get("gitbook")

        if "mkdocs" in html_lower or "md-content" in html:
            return cls._patterns.get("mkdocs")

        if "sphinx" in html_lower or "sphinxsidebar" in html:
            return cls._patterns.get("sphinx")

        if "vitepress" in html_lower or "vp-doc" in html:
            return cls._patterns.get("vitepress")

        return None
