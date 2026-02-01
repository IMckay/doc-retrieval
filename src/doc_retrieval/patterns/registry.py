"""Site-specific extraction pattern registry."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field


class DetectionSignal(BaseModel):
    """A single signal used to detect a site pattern."""

    kind: str  # "url_substring" | "html_substring" | "meta_generator"
    value: str
    weight: int = 10
    case_sensitive: bool = True


class Phase2Check(BaseModel):
    """A DOM-aware check used in Phase 2 detection."""

    kind: str  # "css_present" | "css_absent" | "script_src_regex" | "content_min_length"
    value: str
    weight: int = 20
    required: bool = False


class DetectionResult(BaseModel):
    """Result of confidence-scored pattern detection."""

    pattern: SitePattern
    score: int
    confidence: float = Field(ge=0.0, le=1.0)
    matched_signals: list[str]


class SitePattern(BaseModel):
    """Configuration for a specific documentation site type."""

    name: str
    description: str
    parent: str | None = None
    specificity: int = 0

    content_selectors: list[str] = []
    remove_selectors: list[str] = []
    doc_url_patterns: list[str] = []
    exclude_url_patterns: list[str] = []
    requires_js: bool = True
    wait_selector: str | None = None
    wait_time_ms: int = 0
    click_tabs_selector: str | None = None

    detection_signals: list[DetectionSignal] = []
    phase1_signals: list[DetectionSignal] = []
    phase2_checks: list[Phase2Check] = []


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
    detection_signals=[
        DetectionSignal(kind="meta_generator", value="docusaurus", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__docusaurus", weight=30),
        DetectionSignal(kind="html_substring", value="docMainContainer", weight=30),
        DetectionSignal(kind="html_substring", value="docusaurus", weight=5, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="html_substring", value='data-testid="page.', weight=30),
        DetectionSignal(kind="html_substring", value="gitbook", weight=25, case_sensitive=False),
        DetectionSignal(kind="url_substring", value="gitbook.io", weight=25),
    ],
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
    detection_signals=[
        DetectionSignal(kind="url_substring", value="readthedocs", weight=25),
        DetectionSignal(kind="url_substring", value=".rtfd.", weight=25),
        DetectionSignal(kind="html_substring", value="rst-content", weight=30),
        DetectionSignal(kind="html_substring", value="wy-nav-side", weight=30),
        DetectionSignal(kind="meta_generator", value="sphinx", weight=25, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="meta_generator", value="mkdocs", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value='class="md-content"', weight=30),
        DetectionSignal(kind="html_substring", value="md-sidebar", weight=25),
        DetectionSignal(kind="html_substring", value="mkdocs", weight=5, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="meta_generator", value="sphinx", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="sphinxsidebar", weight=30),
        DetectionSignal(kind="html_substring", value="sphinx.pocoo.org", weight=30),
        DetectionSignal(kind="html_substring", value="sphinx", weight=5, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="meta_generator", value="docusaurus", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__docusaurus", weight=30),
        DetectionSignal(kind="html_substring", value="openapi-left-panel__container", weight=30),
        DetectionSignal(kind="html_substring", value="openapi-schema__property", weight=30),
        DetectionSignal(kind="html_substring", value="docusaurus-openapi", weight=30),
        DetectionSignal(kind="html_substring", value="docusaurus-plugin-openapi", weight=30),
        DetectionSignal(kind="html_substring", value="openapi-explorer", weight=25),
        DetectionSignal(kind="html_substring", value="plugin-content-docs-api", weight=25),
    ],
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
    detection_signals=[
        DetectionSignal(kind="meta_generator", value="vitepress", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="vp-doc", weight=30),
        DetectionSignal(kind="html_substring", value="VPSidebar", weight=25),
        DetectionSignal(kind="html_substring", value="vitepress", weight=5, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="meta_generator", value="mintlify", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="mintlify-", weight=30),
        DetectionSignal(kind="html_substring", value="mintlify", weight=5, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="html_substring", value="nextra-content", weight=30),
        DetectionSignal(kind="html_substring", value="nx-prose", weight=30),
        DetectionSignal(kind="html_substring", value="nextra", weight=10, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="html_substring", value="swagger-ui", weight=30),
        DetectionSignal(kind="html_substring", value="swagger-ui-bundle", weight=25),
    ],
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
    detection_signals=[
        DetectionSignal(kind="html_substring", value="redoc-wrap", weight=30),
        DetectionSignal(
            kind="html_substring", value="redoc.standalone", weight=30, case_sensitive=False
        ),
    ],
)

REDOCLY_REALM_PATTERN = SitePattern(
    name="redocly-realm",
    description="Redocly Realm developer portals",
    content_selectors=[
        "main",
        "article",
        '[role="main"]',
    ],
    remove_selectors=[
        "aside",
        "nav",
        "header",
        "footer",
        '[class*="Sidebar"]',
        '[class*="Navbar"]',
        '[class*="Footer"]',
        '[class*="CopyForLlm"]',
        '[class*="Breadcrumb"]',
    ],
    requires_js=False,
    wait_selector="main",
    detection_signals=[
        DetectionSignal(kind="html_substring", value="/runtime/browser-entry.js", weight=30),
        DetectionSignal(kind="html_substring", value="-redocly-", weight=25, case_sensitive=False),
    ],
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
    detection_signals=[
        DetectionSignal(kind="meta_generator", value="starlight", weight=50, case_sensitive=False),
        DetectionSignal(kind="meta_generator", value="astro", weight=25, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="sl-markdown-content", weight=30),
        DetectionSignal(kind="html_substring", value="starlight", weight=5, case_sensitive=False),
    ],
)


_DETECTION_THRESHOLD = 20

_META_GENERATOR_RE = re.compile(
    r'<meta\s+(?:'
    r'name=["\']generator["\']\s+content=["\']([^"\']+)["\']'
    r'|'
    r'content=["\']([^"\']+)["\']\s+name=["\']generator["\']'
    r')',
    re.IGNORECASE,
)


def _extract_meta_generators(html: str) -> list[str]:
    """Extract generator meta tag values from the first 5000 chars of HTML."""
    head = html[:5000]
    generators: list[str] = []
    for m in _META_GENERATOR_RE.finditer(head):
        value = m.group(1) or m.group(2)
        if value:
            generators.append(value)
    return generators


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
        "redocly-realm": REDOCLY_REALM_PATTERN,
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
    def _score_phase1(
        cls,
        pattern: SitePattern,
        url: str,
        html: str,
        headers: dict[str, str],
    ) -> tuple[int, list[str]]:
        """Score a pattern's Phase 1 signals against page data.

        Returns (score, list_of_matched_signal_descriptions).
        """
        url_lower = url.lower()
        html_lower = html.lower() if html else ""
        generators = _extract_meta_generators(html) if html else []
        generators_lower = [g.lower() for g in generators]
        headers_lower = {k.lower(): v.lower() for k, v in headers.items()}

        score = 0
        matched: list[str] = []

        for signal in pattern.phase1_signals:
            hit = False

            if signal.kind == "url_substring":
                target = url if signal.case_sensitive else url_lower
                value = signal.value if signal.case_sensitive else signal.value.lower()
                hit = value in target

            elif signal.kind == "html_substring":
                target = html if signal.case_sensitive else html_lower
                value = signal.value if signal.case_sensitive else signal.value.lower()
                hit = value in target

            elif signal.kind == "meta_generator":
                value = signal.value if signal.case_sensitive else signal.value.lower()
                source = generators if signal.case_sensitive else generators_lower
                hit = any(value in g for g in source)

            elif signal.kind == "http_header":
                if ":" in signal.value:
                    header_name, expected = signal.value.split(":", 1)
                    header_name_l = header_name.lower()
                    expected_l = expected.lower() if not signal.case_sensitive else expected
                    actual = headers_lower.get(header_name_l, "")
                    if not signal.case_sensitive:
                        hit = expected_l in actual
                    else:
                        raw_actual = headers.get(header_name, "")
                        hit = expected in raw_actual
                else:
                    hit = signal.value.lower() in headers_lower

            if hit:
                score += signal.weight
                matched.append(f"{signal.kind}:{signal.value}")

        return score, matched

    @classmethod
    def _score_phase2(
        cls,
        pattern: SitePattern,
        html: str,
    ) -> tuple[int, list[str], bool]:
        """Score a pattern's Phase 2 checks against parsed HTML.

        Returns (score, matched_descriptions, disqualified).
        disqualified is True if any required check failed.
        """
        if not pattern.phase2_checks:
            return 0, [], False

        soup = BeautifulSoup(html, "html.parser")
        score = 0
        matched: list[str] = []
        disqualified = False

        for check in pattern.phase2_checks:
            hit = False

            if check.kind == "css_present":
                hit = soup.select_one(check.value) is not None

            elif check.kind == "css_absent":
                hit = soup.select_one(check.value) is None

            elif check.kind == "script_src_regex":
                regex = re.compile(check.value)
                for script in soup.find_all("script", src=True):
                    src_val = script["src"]
                    src_str = src_val if isinstance(src_val, str) else src_val[0]
                    if regex.search(src_str):
                        hit = True
                        break

            elif check.kind == "content_min_length":
                threshold = int(check.value)
                main_el = soup.select_one("main") or soup.select_one("body")
                if main_el:
                    text = main_el.get_text(separator=" ", strip=True)
                    hit = len(text) >= threshold

            if hit:
                score += check.weight
                matched.append(f"{check.kind}:{check.value}")
            elif check.required:
                disqualified = True

        return score, matched, disqualified

    @classmethod
    def detect_with_confidence(
        cls, url: str, html: str
    ) -> DetectionResult | None:
        """Score all patterns and return the highest scorer above threshold.

        Returns None if no pattern scores at or above _DETECTION_THRESHOLD.
        """
        url_lower = url.lower()
        html_lower = html.lower() if html else ""
        generators = _extract_meta_generators(html) if html else []
        generators_lower = [g.lower() for g in generators]

        best: DetectionResult | None = None

        for pattern in cls._patterns.values():
            if not pattern.detection_signals:
                continue

            score = 0
            matched: list[str] = []
            max_possible = sum(s.weight for s in pattern.detection_signals)

            for signal in pattern.detection_signals:
                hit = False
                if signal.kind == "url_substring":
                    target = url if signal.case_sensitive else url_lower
                    value = signal.value if signal.case_sensitive else signal.value.lower()
                    hit = value in target
                elif signal.kind == "html_substring":
                    target = html if signal.case_sensitive else html_lower
                    value = signal.value if signal.case_sensitive else signal.value.lower()
                    hit = value in target
                elif signal.kind == "meta_generator":
                    value = signal.value if signal.case_sensitive else signal.value.lower()
                    source = generators if signal.case_sensitive else generators_lower
                    hit = any(value in g for g in source)

                if hit:
                    score += signal.weight
                    matched.append(f"{signal.kind}:{signal.value}")

            if score < _DETECTION_THRESHOLD:
                continue

            confidence = min(score / max(max_possible, 1), 1.0)

            if best is None or score > best.score:
                best = DetectionResult(
                    pattern=pattern,
                    score=score,
                    confidence=confidence,
                    matched_signals=matched,
                )

        return best

    @classmethod
    def detect(cls, url: str, html: str) -> SitePattern | None:
        """Auto-detect site type from URL or HTML content.

        Thin wrapper around detect_with_confidence() for backward compatibility.
        """
        result = cls.detect_with_confidence(url, html)
        return result.pattern if result else None
