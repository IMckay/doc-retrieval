"""Site-specific extraction pattern registry."""


from pydantic import BaseModel


class SitePattern(BaseModel):
    """Configuration for a specific documentation site type."""

    name: str
    description: str

    content_selectors: list[str] = []
    remove_selectors: list[str] = []
    doc_url_patterns: list[str] = []
    exclude_url_patterns: list[str] = []
    requires_js: bool = True
    wait_selector: str | None = None
    wait_time_ms: int = 0
    click_tabs_selector: str | None = None


DOCUSAURUS_PATTERN = SitePattern(
    name="docusaurus",
    description="Docusaurus documentation sites",
    content_selectors=[
        "article.markdown",
        ".docMainContent",
        'main[class*="docMainContainer"]',
        "main .col",
        "main .container article",
        '[class*="docItemContainer"]',
    ],
    remove_selectors=[
        ".theme-doc-sidebar-container",
        '[class*="docSidebarContainer"]',
        "aside",
        'nav[aria-label="Main"]',
        ".navbar",
        ".theme-doc-breadcrumbs",
        ".pagination-nav",
        ".theme-doc-toc-mobile",
        ".theme-doc-footer",
        ".theme-edit-this-page",
        '[class*="tocCollapsible"]',
        "footer",
    ],
    requires_js=True,
    wait_selector="article.markdown",
    click_tabs_selector='.openapi-tabs__code-container [role="tab"]',
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

DOCUSAURUS_OPENAPI_PATTERN = SitePattern(
    name="docusaurus-openapi",
    description="Docusaurus sites with docusaurus-openapi-docs plugin",
    content_selectors=[
        "article .theme-doc-markdown",
        "article.markdown",
        'main[class*="docMainContainer"]',
        "main .col",
        "article",
    ],
    remove_selectors=[
        ".openapi-explorer__request-form",
        ".openapi-explorer__response-container",
        ".theme-doc-sidebar-container",
        '[class*="docSidebarContainer"]',
        "aside",
        'nav[aria-label="Main"]',
        ".navbar",
        ".theme-doc-breadcrumbs",
        ".pagination-nav",
        ".theme-doc-toc-mobile",
        ".theme-doc-footer",
        ".theme-edit-this-page",
        ".breadcrumbs",
        '[class*="tocCollapsible"]',
        "footer",
    ],
    requires_js=True,
    wait_selector=".openapi-left-panel__container, article.markdown",
    wait_time_ms=500,
    click_tabs_selector='.openapi-tabs__code-container [role="tab"]',
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

MINTLIFY_PATTERN = SitePattern(
    name="mintlify",
    description="Mintlify documentation sites",
    content_selectors=[
        "#content-area",
        "article",
        ".prose",
        "main",
    ],
    remove_selectors=[
        "#sidebar",
        '[class*="Sidebar"]',
        "nav",
        "header",
        "footer",
        ".on-this-page",
        '[class*="TableOfContents"]',
        '[class*="Pagination"]',
        '[class*="FeedbackButtons"]',
    ],
    requires_js=True,
    wait_selector="#content-area, article",
)

NEXTRA_PATTERN = SitePattern(
    name="nextra",
    description="Nextra (Next.js) documentation sites",
    content_selectors=[
        "article",
        ".nextra-content",
        "main .nx-prose",
        "main",
    ],
    remove_selectors=[
        "aside",
        "nav",
        ".nextra-sidebar-container",
        '[class*="nx-sidebar"]',
        ".nextra-toc",
        ".nextra-breadcrumb",
        "footer",
        ".nx-mt-auto",
    ],
    requires_js=True,
    wait_selector="article, .nextra-content",
)

SWAGGER_UI_PATTERN = SitePattern(
    name="swagger-ui",
    description="Swagger UI API documentation",
    content_selectors=[
        ".swagger-ui",
        "#swagger-ui",
    ],
    remove_selectors=[
        ".topbar",
        ".auth-wrapper",
        ".scheme-container",
    ],
    requires_js=True,
    wait_selector=".swagger-ui .information-container, .swagger-ui .opblock",
    wait_time_ms=1000,
)

REDOC_PATTERN = SitePattern(
    name="redoc",
    description="Redoc API documentation",
    content_selectors=[
        ".redoc-wrap",
        "#redoc",
        "[data-role='redoc']",
    ],
    remove_selectors=[
        ".menu-content",
        '[role="navigation"]',
    ],
    requires_js=True,
    wait_selector=".redoc-wrap, .api-content",
    wait_time_ms=1000,
)

STARLIGHT_PATTERN = SitePattern(
    name="starlight",
    description="Starlight (Astro) documentation sites",
    content_selectors=[
        ".sl-markdown-content",
        "[data-pagefind-body]",
        "main",
    ],
    remove_selectors=[
        "nav",
        "header.header",
        ".sidebar",
        '[class*="sidebar"]',
        "starlight-toc",
        ".right-sidebar",
        "footer",
        ".pagination-links",
    ],
    requires_js=False,
    wait_selector=".sl-markdown-content",
)


class PatternRegistry:
    """Registry of site-specific patterns."""

    _patterns: dict[str, SitePattern] = {
        "docusaurus": DOCUSAURUS_PATTERN,
        "docusaurus-openapi": DOCUSAURUS_OPENAPI_PATTERN,
        "gitbook": GITBOOK_PATTERN,
        "readthedocs": READTHEDOCS_PATTERN,
        "mkdocs": MKDOCS_PATTERN,
        "sphinx": SPHINX_PATTERN,
        "vitepress": VITEPRESS_PATTERN,
        "mintlify": MINTLIFY_PATTERN,
        "nextra": NEXTRA_PATTERN,
        "swagger-ui": SWAGGER_UI_PATTERN,
        "redoc": REDOC_PATTERN,
        "starlight": STARLIGHT_PATTERN,
    }

    @classmethod
    def register(cls, pattern: SitePattern) -> None:
        """Register a new pattern."""
        cls._patterns[pattern.name] = pattern

    @classmethod
    def get(cls, name: str) -> SitePattern | None:
        """Get a pattern by name."""
        return cls._patterns.get(name)

    @classmethod
    def list_patterns(cls) -> list[SitePattern]:
        """List all registered patterns."""
        return list(cls._patterns.values())

    @classmethod
    def detect(cls, url: str, html: str) -> SitePattern | None:
        """Auto-detect site type from URL or HTML content."""
        url_lower = url.lower()
        html_lower = html.lower() if html else ""

        if "readthedocs" in url_lower or ".rtfd." in url_lower:
            return cls._patterns.get("readthedocs")

        # Check HTML content for framework signatures
        # Docusaurus OpenAPI must be checked before generic Docusaurus
        if "docusaurus" in html_lower or "__docusaurus" in html:
            # Check for OpenAPI plugin markers (rendered content or plugin assets)
            openapi_markers = [
                "openapi-schema__property",
                "openapi-left-panel__container",
                "openapi-markdown__details",
                "docusaurus-openapi",
                "openapi-explorer",
                # Static HTML markers present even before JS renders
                "docusaurus-plugin-openapi",
                "plugin-content-docs-api",
            ]
            if any(marker in html for marker in openapi_markers):
                return cls._patterns.get("docusaurus-openapi")

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

        if "mintlify" in html_lower or "mintlify-" in html:
            return cls._patterns.get("mintlify")

        if "nextra" in html_lower or "nx-prose" in html or "nextra-content" in html:
            return cls._patterns.get("nextra")

        # Swagger UI: look for its characteristic container
        if "swagger-ui" in html:
            return cls._patterns.get("swagger-ui")

        # Redoc: look for its wrapper or bundle
        if "redoc-wrap" in html or "redoc.standalone" in html_lower:
            return cls._patterns.get("redoc")

        # Starlight (Astro): look for its content class prefix
        if "sl-markdown-content" in html or "starlight" in html_lower:
            return cls._patterns.get("starlight")

        return None
