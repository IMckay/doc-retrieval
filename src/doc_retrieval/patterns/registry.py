"""Site-specific extraction pattern registry."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from doc_retrieval.config import AppConfig


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
    section_url_pattern: str | None = None
    section_selector_template: str | None = None
    section_url_patterns: list[str] = []
    markdown_cleanup_patterns: list[str] = []

    nav_selectors: list[str] = []

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
    nav_selectors=[
        ".navbar__items > .navbar__item:not(.dropdown) > a",
        ".dropdown__menu a",
    ],
    requires_js=True,
    wait_selector="article.markdown",
    click_tabs_selector='.openapi-tabs__code-container [role="tab"]',
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="docusaurus", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__docusaurus", weight=30),
        DetectionSignal(kind="html_substring", value="docMainContainer", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value="article.markdown", weight=20),
        Phase2Check(kind="css_present", value='[class*="docMainContainer"]', weight=20),
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
    nav_selectors=["nav[aria-label] a"],
    requires_js=True,
    wait_selector='[data-testid="page.contentEditor"], .markdown-section',
    phase1_signals=[
        DetectionSignal(kind="html_substring", value='data-testid="page.', weight=30),
        DetectionSignal(kind="html_substring", value="gitbook", weight=25, case_sensitive=False),
        DetectionSignal(kind="url_substring", value="gitbook.io", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value='[data-testid="page.contentEditor"]', weight=20),
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
    nav_selectors=[".wy-nav-side .toctree-l1 > a"],
    requires_js=False,
    phase1_signals=[
        DetectionSignal(kind="url_substring", value="readthedocs", weight=25),
        DetectionSignal(kind="url_substring", value=".rtfd.", weight=25),
        DetectionSignal(kind="html_substring", value="rst-content", weight=30),
        DetectionSignal(kind="html_substring", value="wy-nav-side", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".wy-nav-side", weight=20, required=True),
        Phase2Check(kind="css_absent", value=".sphinxsidebar", weight=15),
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
    nav_selectors=[
        ".md-tabs__link",
        ".md-nav--primary > .md-nav__list > .md-nav__item > a",
    ],
    requires_js=False,
    wait_selector='[role="main"]',
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="mkdocs", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value='class="md-content"', weight=30),
        DetectionSignal(kind="html_substring", value="md-sidebar", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".md-content", weight=20),
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
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="sphinx", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="sphinxsidebar", weight=30),
        DetectionSignal(kind="html_substring", value="sphinx.pocoo.org", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value='[role="main"]', weight=15),
        Phase2Check(kind="css_present", value=".document", weight=15),
    ],
)

DOCUSAURUS_OPENAPI_PATTERN = SitePattern(
    name="docusaurus-openapi",
    description="Docusaurus sites with docusaurus-openapi-docs plugin",
    parent="docusaurus",
    specificity=1,
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
    phase1_signals=[],  # Inherits candidacy from parent (docusaurus)
    phase2_checks=[
        Phase2Check(
            kind="css_present", value=".openapi-left-panel__container",
            weight=30, required=True,
        ),
        Phase2Check(
            kind="css_present", value=".openapi-schema__property", weight=20,
        ),
        Phase2Check(
            kind="script_src_regex",
            value="docusaurus-openapi|plugin-content-docs-api", weight=20,
        ),
        Phase2Check(kind="css_present", value=".openapi-explorer", weight=15),
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
    nav_selectors=[
        ".VPNavBarMenu a",
        ".VPSidebar .VPSidebarItem > a",
    ],
    requires_js=True,
    wait_selector=".vp-doc",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="vitepress", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="vp-doc", weight=30),
        DetectionSignal(kind="html_substring", value="VPSidebar", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".vp-doc", weight=20),
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
    nav_selectors=["nav a[href]"],
    requires_js=True,
    wait_selector="#content-area, article",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="mintlify", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="mintlify-", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value="#content-area", weight=20),
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
    nav_selectors=["nav a[href]"],
    requires_js=True,
    wait_selector="article, .nextra-content",
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="nextra-content", weight=30),
        DetectionSignal(kind="html_substring", value="nx-prose", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".nextra-content", weight=20),
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
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="swagger-ui", weight=30),
        DetectionSignal(kind="html_substring", value="swagger-ui-bundle", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".swagger-ui", weight=20),
        Phase2Check(kind="css_absent", value=".redoc-wrap", weight=10),
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
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="redoc-wrap", weight=30),
        DetectionSignal(
            kind="html_substring", value="redoc.standalone",
            weight=30, case_sensitive=False,
        ),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".redoc-wrap", weight=20),
        Phase2Check(kind="css_absent", value=".swagger-ui", weight=10),
    ],
)

REDOCLY_REALM_PATTERN = SitePattern(
    name="redocly-realm",
    description="Redocly Realm developer portals",
    content_selectors=[
        ".redoc-wrap .api-content",
        ".redoc-wrap",
        "main article",
        "article",
        "main",
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
        '[class*="Breadcrumb"]',
        '[class*="PageActions__"]',
        '[class*="PageActionsMenuItem__"]',
        '[class*="Dropdown__"]',
        '[class*="DropdownMenu__"]',
        'button[class*="Copy"]',
        '[class*="menu-content"]',
        '[class*="MenuItems"]',
        '[role="navigation"]',
        '[class*="Rating__"]',
        '[class*="PageNavigation__"]',
        '[class*="DocumentationLayout__LayoutBottom"]',
    ],
    nav_selectors=["nav a[href]", "header a[href]"],
    requires_js=True,
    wait_selector=".redoc-wrap .api-content, main article",
    wait_time_ms=1000,
    section_url_pattern=r"/references/.+?/api\.[^/]+/(.+)$",
    section_selector_template='[id="{section}"]',
    section_url_patterns=[
        r"/references/.+?/api\.[^/]+/(.+)$",
        r"/guides/.+?/api(?:-[^/]+)?/(.+)$",
    ],
    markdown_cleanup_patterns=[
        # FORMAT A: toolbar fused onto heading line
        r"(?m)(^#{1,6}\s+.+?)\s+Copy\s+-\s+Copy for LLM\b.*$",
        # FORMAT B: standalone toolbar block after heading
        (
            r"(?m)^Copy\n\n- Copy for LLM\n"
            r"(?:\n\s+Copy page as Markdown[^\n]*\n)*"
            r"(?:- \[(?:View as Markdown|Open in ChatGPT|Open in Claude)\b[^\n]*\n)*"
            r"(?:- Connect to (?:Cursor|VS Code)\b[^\n]*\n)*"
        ),
        # "Was this page helpful?" section
        r"(?m)^#{1,6}\s+Was this page helpful\?\s*$",
    ],
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="/runtime/browser-entry.js", weight=30),
        DetectionSignal(
            kind="html_substring", value="-redocly-", weight=25, case_sensitive=False
        ),
    ],
    phase2_checks=[],
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
    nav_selectors=["nav.sidebar a"],
    requires_js=False,
    wait_selector=".sl-markdown-content",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="starlight", weight=50, case_sensitive=False),
        DetectionSignal(kind="meta_generator", value="astro", weight=25, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="sl-markdown-content", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".sl-markdown-content", weight=20),
    ],
)


CONFIDENCE_NORMALIZER = 100

_META_GENERATOR_RE = re.compile(
    r'<meta\s+(?:'
    r'name=["\']generator["\']\s+content=["\']([^"\']+)["\']'
    r'|'
    r'content=["\']([^"\']+)["\']\s+name=["\']generator["\']'
    r')',
    re.IGNORECASE,
)


_DOC_PATH_RE = re.compile(
    r'href="(/(?:docs?|guide|api|reference|tutorial|getting-started)[^"]*)"',
    re.IGNORECASE,
)

_SAME_DOMAIN_HREF_RE = re.compile(r'href="(/[^"]*)"')


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

    _PHASE1_CANDIDATE_THRESHOLD = 15

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
    def apply_to_config(cls, pattern_name: str, config: AppConfig) -> AppConfig:
        """Apply pattern settings to config, filling defaults only.

        Pattern settings override default values but not explicit user settings.
        Returns a new AppConfig (original is not mutated).
        """
        pattern = cls.get(pattern_name)
        if not pattern:
            return config

        fetcher_updates: dict = {}
        if config.fetcher.wait_selector is None and pattern.wait_selector:
            fetcher_updates["wait_selector"] = pattern.wait_selector
        if config.fetcher.wait_time_ms == 0 and pattern.wait_time_ms > 0:
            fetcher_updates["wait_time_ms"] = pattern.wait_time_ms
        if config.fetcher.click_tabs_selector is None and pattern.click_tabs_selector:
            fetcher_updates["click_tabs_selector"] = pattern.click_tabs_selector
        if not config.fetcher.use_js and pattern.requires_js:
            fetcher_updates["use_js"] = True

        extractor_updates: dict = {}
        if pattern.content_selectors:
            extractor_updates["content_selectors"] = pattern.content_selectors
        if pattern.remove_selectors:
            extractor_updates["remove_selectors"] = pattern.remove_selectors
        if pattern.section_url_pattern and config.extractor.section_url_pattern is None:
            extractor_updates["section_url_pattern"] = pattern.section_url_pattern
        if pattern.section_selector_template and config.extractor.section_selector_template is None:
            extractor_updates["section_selector_template"] = pattern.section_selector_template
        if pattern.section_url_patterns and not config.extractor.section_url_patterns:
            extractor_updates["section_url_patterns"] = pattern.section_url_patterns
        if pattern.markdown_cleanup_patterns:
            extractor_updates["markdown_cleanup_patterns"] = pattern.markdown_cleanup_patterns

        updates: dict = {}
        if fetcher_updates:
            updates["fetcher"] = config.fetcher.model_copy(update=fetcher_updates)
        if extractor_updates:
            updates["extractor"] = config.extractor.model_copy(update=extractor_updates)

        if updates:
            return config.model_copy(update=updates)
        return config

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
    def _select_winner(
        cls, candidates: list[dict]
    ) -> DetectionResult | None:
        """Select the winning pattern from scored candidates.

        Each candidate dict has keys: pattern, phase1_score, phase2_score,
        disqualified, matched_signals.

        Rules:
        1. Disqualified patterns are excluded.
        2. Group by family (parent chain root).
        3. Within each family, most-specific wins.
        4. Across families, highest combined score wins.
        5. Ties broken by specificity.
        """
        # Filter out disqualified
        viable = [c for c in candidates if not c["disqualified"]]
        if not viable:
            return None

        # Group by family root
        families: dict[str, list[dict]] = {}
        for c in viable:
            root = c["pattern"].parent or c["pattern"].name
            families.setdefault(root, []).append(c)

        # Pick best per family (highest specificity)
        family_winners: list[dict] = []
        for members in families.values():
            members.sort(key=lambda c: c["pattern"].specificity, reverse=True)
            family_winners.append(members[0])

        # Pick overall winner: highest total score, ties broken by specificity
        family_winners.sort(
            key=lambda c: (
                c["phase1_score"] + c["phase2_score"],
                c["pattern"].specificity,
            ),
            reverse=True,
        )

        best = family_winners[0]
        total = best["phase1_score"] + best["phase2_score"]
        confidence = min(1.0, total / CONFIDENCE_NORMALIZER)

        all_matched = best["matched_signals"]

        return DetectionResult(
            pattern=best["pattern"],
            score=total,
            confidence=confidence,
            matched_signals=all_matched,
        )

    @classmethod
    def detect_two_phase(
        cls,
        url: str,
        html: str,
        headers: dict[str, str] | None = None,
    ) -> DetectionResult | None:
        """Two-phase pattern detection with hierarchy support."""
        if headers is None:
            headers = {}

        # Phase 1: score all patterns
        phase1_scores: dict[str, tuple[int, list[str]]] = {}
        for pattern in cls._patterns.values():
            if not pattern.phase1_signals:
                continue
            score, matched = cls._score_phase1(pattern, url, html, headers)
            if score >= cls._PHASE1_CANDIDATE_THRESHOLD:
                phase1_scores[pattern.name] = (score, matched)

        # Build candidate set: patterns that passed Phase 1 + children of passing parents
        candidate_names: set[str] = set(phase1_scores.keys())
        for pattern in cls._patterns.values():
            if pattern.parent and pattern.parent in candidate_names:
                candidate_names.add(pattern.name)

        if not candidate_names:
            return None

        # Phase 2: score candidates with DOM-aware checks
        candidates: list[dict] = []
        for name in candidate_names:
            pattern = cls._patterns[name]
            p1_score, p1_matched = phase1_scores.get(name, (0, []))
            p2_score, p2_matched, disqualified = cls._score_phase2(pattern, html)

            candidates.append({
                "pattern": pattern,
                "phase1_score": p1_score,
                "phase2_score": p2_score,
                "disqualified": disqualified,
                "matched_signals": p1_matched + p2_matched,
            })

        return cls._select_winner(candidates)

    @staticmethod
    def _should_probe_inner_pages(
        best_confidence: float,
        best_score: int,
        second_score: int,
    ) -> bool:
        """Determine if inner-page probing should be triggered."""
        if best_score == 0:
            return True
        if best_confidence < 0.5:
            return True
        if second_score >= best_score * 0.8:
            return True
        return False

    @staticmethod
    def _extract_probe_urls(html: str, base_url: str) -> list[str]:
        """Extract up to 3 internal URLs for probing, preferring doc-like paths."""
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc
        base_normalized = f"{parsed_base.scheme}://{base_domain}"

        # Prefer doc-like paths
        doc_hrefs = _DOC_PATH_RE.findall(html)
        # Fallback: any same-domain relative path
        all_hrefs = _SAME_DOMAIN_HREF_RE.findall(html)

        seen: set[str] = set()
        result: list[str] = []

        def _add(href: str) -> bool:
            # Strip fragment
            href = href.split("#")[0]
            if not href or href == "/":
                return False
            full = urljoin(base_normalized + "/", href)
            # Must be same domain
            if urlparse(full).netloc != base_domain:
                return False
            if full in seen:
                return False
            # Skip if it's the base URL itself
            if full.rstrip("/") == base_url.rstrip("/"):
                return False
            seen.add(full)
            result.append(full)
            return len(result) >= 3

        # Doc paths first
        for href in doc_hrefs:
            if _add(href):
                break

        # Fill remaining with any same-domain links
        if len(result) < 3:
            for href in all_hrefs:
                if _add(href):
                    break

        return result

    @classmethod
    def detect_with_confidence(
        cls, url: str, html: str
    ) -> DetectionResult | None:
        """Score all patterns and return the best match.

        Backward-compatible wrapper around detect_two_phase().
        """
        return cls.detect_two_phase(url, html, headers={})

    @classmethod
    def detect(cls, url: str, html: str) -> SitePattern | None:
        """Auto-detect site type from URL or HTML content.

        Backward-compatible wrapper around detect_two_phase().
        """
        result = cls.detect_two_phase(url, html, headers={})
        return result.pattern if result else None
