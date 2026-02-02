"""Tests for NavScanner — orchestration of parsing and enrichment."""

import re

from doc_retrieval.interactive import InteractiveExtractor
from doc_retrieval.patterns.registry import SitePattern
from doc_retrieval.scanner.models import NavSection, NavSubSection, SiteStructure
from doc_retrieval.scanner.nav_scanner import (
    NavScanner,
    _humanize_label,
    auto_expand_sections,
    derive_sub_sections,
)

BASE = "https://docs.example.com"


MULTI_SECTION_HTML = """
<html><body>
<header>
  <nav>
    <a href="/docs/">Docs</a>
    <a href="/guides/">Guides</a>
    <a href="/api-reference/">API Reference</a>
  </nav>
</header>
<main><p>Content</p></main>
</body></html>
"""

SINGLE_SECTION_HTML = """
<html><body>
<header>
  <nav>
    <a href="/docs/">Docs</a>
  </nav>
</header>
</body></html>
"""

EMPTY_HTML = """
<html><body><main><p>No nav</p></main></body></html>
"""

PATTERN_SPECIFIC_HTML = """
<html><body>
<nav>
  <div class="custom-nav">
    <a href="/docs/">Docs</a>
    <a href="/tutorials/">Tutorials</a>
  </div>
</nav>
<!-- These should be ignored when using pattern selectors -->
<aside><nav>
    <a href="/sidebar-only/">Sidebar</a>
</nav></aside>
</body></html>
"""


class TestNavScannerScan:
    def test_multi_section_generic(self):
        scanner = NavScanner(BASE)
        structure = scanner.scan(MULTI_SECTION_HTML)
        assert len(structure.sections) == 3
        assert structure.source == "generic"
        prefixes = {s.path_prefix for s in structure.sections}
        assert "/docs/" in prefixes
        assert "/guides/" in prefixes
        assert "/api-reference/" in prefixes

    def test_empty_html_returns_fallback(self):
        scanner = NavScanner(BASE)
        structure = scanner.scan(EMPTY_HTML)
        assert structure.sections == []
        assert structure.source == "fallback"
        assert structure.raw_nav_links == 0

    def test_pattern_specific_selectors(self):
        pattern = SitePattern(
            name="test",
            description="Test",
            nav_selectors=[".custom-nav a"],
        )
        scanner = NavScanner(BASE, pattern)
        structure = scanner.scan(PATTERN_SPECIFIC_HTML)
        assert structure.source == "pattern"
        urls = {s.url for s in structure.sections}
        # Should have docs and tutorials from pattern selector
        assert f"{BASE}/docs/" in urls
        assert f"{BASE}/tutorials/" in urls

    def test_falls_back_to_generic_when_pattern_selectors_empty(self):
        pattern = SitePattern(
            name="test",
            description="Test",
            nav_selectors=[".nonexistent a"],
        )
        scanner = NavScanner(BASE, pattern)
        structure = scanner.scan(MULTI_SECTION_HTML)
        assert structure.source == "generic"
        assert len(structure.sections) >= 1

    def test_raw_nav_links_count(self):
        scanner = NavScanner(BASE)
        structure = scanner.scan(MULTI_SECTION_HTML)
        assert structure.raw_nav_links == 3


class TestNavScannerEnrich:
    def test_enrich_sets_estimated_pages(self):
        scanner = NavScanner(BASE)
        structure = SiteStructure(
            sections=[
                NavSection(label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/"),
                NavSection(label="API", url=f"{BASE}/api/", path_prefix="/api/"),
            ],
        )
        sitemap_urls = [
            f"{BASE}/docs/intro",
            f"{BASE}/docs/install",
            f"{BASE}/docs/config",
            f"{BASE}/api/rest",
        ]
        enriched = scanner.enrich_with_sitemap(structure, sitemap_urls)
        docs = [s for s in enriched.sections if s.path_prefix == "/docs/"][0]
        api = [s for s in enriched.sections if s.path_prefix == "/api/"][0]
        assert docs.estimated_pages == 3
        assert api.estimated_pages == 1

    def test_enrich_with_empty_urls(self):
        scanner = NavScanner(BASE)
        structure = SiteStructure(
            sections=[
                NavSection(label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/"),
            ],
        )
        enriched = scanner.enrich_with_sitemap(structure, [])
        assert enriched.sections[0].estimated_pages is None

    def test_enrich_no_matching_urls(self):
        scanner = NavScanner(BASE)
        structure = SiteStructure(
            sections=[
                NavSection(label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/"),
            ],
        )
        enriched = scanner.enrich_with_sitemap(structure, [f"{BASE}/api/rest"])
        assert enriched.sections[0].estimated_pages is None


class TestNavScannerSubsections:
    def test_scan_subsections(self):
        scanner = NavScanner(BASE)
        parent = NavSection(
            label="Docs",
            url=f"{BASE}/docs/",
            path_prefix="/docs/",
        )
        html = """
        <html><body>
        <header><nav>
            <a href="/docs/intro/">Intro</a>
            <a href="/docs/advanced/">Advanced</a>
            <a href="/api/rest/">REST</a>
        </nav></header>
        </body></html>
        """
        links = scanner.scan_subsections(html, parent)
        urls = {lnk.url for lnk in links}
        assert f"{BASE}/docs/intro/" in urls
        assert f"{BASE}/docs/advanced/" in urls
        # REST is under /api/, not /docs/
        assert f"{BASE}/api/rest/" not in urls


class TestEnrichRetainsSitemapUrls:
    def test_enrich_stores_sitemap_urls(self):
        scanner = NavScanner(BASE)
        structure = SiteStructure(
            sections=[
                NavSection(label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/"),
            ],
        )
        sitemap_urls = [f"{BASE}/docs/page{i}" for i in range(10)]
        enriched = scanner.enrich_with_sitemap(structure, sitemap_urls)
        assert enriched.sitemap_urls == sitemap_urls


class TestHumanizeLabel:
    def test_hyphenated(self):
        assert _humanize_label("api-reference") == "Api Reference"

    def test_underscored(self):
        assert _humanize_label("getting_started") == "Getting Started"

    def test_single_word(self):
        assert _humanize_label("build") == "Build"


class TestDeriveSubSections:
    def _make_urls(self, prefix: str, segments: dict[str, int]) -> list[str]:
        """Build fake sitemap URLs: segments maps segment name → page count."""
        urls: list[str] = []
        for seg, count in segments.items():
            for i in range(count):
                urls.append(f"{BASE}{prefix}{seg}/page{i}")
        return urls

    def test_basic_grouping(self):
        section = NavSection(
            label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/",
        )
        urls = self._make_urls("/docs/", {"build": 10, "messenger": 5, "references": 20})
        subs = derive_sub_sections(section, urls)
        labels = {s.label for s in subs}
        assert "Build" in labels
        assert "Messenger" in labels
        assert "References" in labels
        # Sorted by count descending
        assert subs[0].estimated_pages == 20

    def test_filters_below_3_pages(self):
        section = NavSection(
            label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/",
        )
        urls = self._make_urls("/docs/", {"big": 10, "tiny": 2})
        subs = derive_sub_sections(section, urls)
        labels = {s.label for s in subs}
        assert "Big" in labels
        assert "Tiny" not in labels

    def test_caps_at_15(self):
        section = NavSection(
            label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/",
        )
        segments = {f"seg{i}": 5 for i in range(20)}
        urls = self._make_urls("/docs/", segments)
        subs = derive_sub_sections(section, urls)
        assert len(subs) <= 15

    def test_no_urls_under_prefix(self):
        section = NavSection(
            label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/",
        )
        urls = [f"{BASE}/api/page{i}" for i in range(10)]
        subs = derive_sub_sections(section, urls)
        assert subs == []

    def test_path_prefix_construction(self):
        section = NavSection(
            label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/",
        )
        urls = self._make_urls("/docs/", {"build": 5})
        subs = derive_sub_sections(section, urls)
        assert subs[0].path_prefix == "/docs/build/"


class TestAutoExpandSections:
    def _make_urls(self, prefix: str, segments: dict[str, int]) -> list[str]:
        urls: list[str] = []
        for seg, count in segments.items():
            for i in range(count):
                urls.append(f"{BASE}{prefix}{seg}/page{i}")
        return urls

    def test_expands_when_few_sections(self):
        """≤4 sections triggers expansion."""
        urls = self._make_urls("/docs/", {"build": 10, "api": 8, "guides": 5})
        structure = SiteStructure(
            sections=[
                NavSection(
                    label="Docs", url=f"{BASE}/docs/",
                    path_prefix="/docs/", estimated_pages=23,
                ),
            ],
            sitemap_urls=urls,
        )
        result = auto_expand_sections(structure)
        assert len(result.sections[0].sub_sections) == 3

    def test_expands_when_section_over_500_pages(self):
        """Section with >500 pages triggers expansion even with >4 sections."""
        urls = self._make_urls("/big/", {f"seg{i}": 100 for i in range(6)})
        sections = [
            NavSection(
                label=f"S{i}", url=f"{BASE}/s{i}/",
                path_prefix=f"/s{i}/", estimated_pages=10,
            )
            for i in range(6)
        ]
        # Make the first section the big one
        sections[0] = NavSection(
            label="Big", url=f"{BASE}/big/",
            path_prefix="/big/", estimated_pages=600,
        )
        structure = SiteStructure(sections=sections, sitemap_urls=urls)
        result = auto_expand_sections(structure)
        assert len(result.sections[0].sub_sections) == 6
        # Other sections should remain unchanged
        assert result.sections[1].sub_sections == []

    def test_skips_when_fewer_than_2_subs(self):
        """Don't attach sub-sections if only 1 would be derived."""
        urls = self._make_urls("/docs/", {"only": 10})
        structure = SiteStructure(
            sections=[
                NavSection(
                    label="Docs", url=f"{BASE}/docs/",
                    path_prefix="/docs/", estimated_pages=10,
                ),
            ],
            sitemap_urls=urls,
        )
        result = auto_expand_sections(structure)
        assert result.sections[0].sub_sections == []

    def test_no_sitemap_urls_returns_unchanged(self):
        structure = SiteStructure(
            sections=[
                NavSection(
                    label="Docs", url=f"{BASE}/docs/", path_prefix="/docs/",
                ),
            ],
        )
        result = auto_expand_sections(structure)
        assert result.sections[0].sub_sections == []

    def test_uses_explicit_urls_param(self):
        """sitemap_urls parameter overrides structure.sitemap_urls."""
        urls = self._make_urls("/docs/", {"a": 5, "b": 5})
        structure = SiteStructure(
            sections=[
                NavSection(
                    label="Docs", url=f"{BASE}/docs/",
                    path_prefix="/docs/", estimated_pages=10,
                ),
            ],
            # Empty on structure
            sitemap_urls=[],
        )
        result = auto_expand_sections(structure, sitemap_urls=urls)
        assert len(result.sections[0].sub_sections) == 2


class TestSectionsToPatterns:
    """Test InteractiveExtractor._sections_to_patterns with sub-sections."""

    def test_all_selected_returns_none(self):
        sections = [
            NavSection(label="A", url="", path_prefix="/a/", selected=True),
            NavSection(label="B", url="", path_prefix="/b/", selected=True),
        ]
        inc, exc = InteractiveExtractor._sections_to_patterns(sections)
        assert inc is None and exc is None

    def test_partial_section_selection(self):
        sections = [
            NavSection(label="A", url="", path_prefix="/a/", selected=True),
            NavSection(label="B", url="", path_prefix="/b/", selected=False),
        ]
        inc, exc = InteractiveExtractor._sections_to_patterns(sections)
        assert inc is not None
        # Pattern should match URLs under /a/
        assert re.match(inc, "/a/foo")
        assert exc is None

    def test_all_subs_selected_uses_parent_prefix(self):
        sections = [
            NavSection(
                label="Docs", url="", path_prefix="/docs/", selected=True,
                sub_sections=[
                    NavSubSection(label="Build", path_prefix="/docs/build/", selected=True),
                    NavSubSection(label="API", path_prefix="/docs/api/", selected=True),
                ],
            ),
            NavSection(label="Other", url="", path_prefix="/other/", selected=False),
        ]
        inc, exc = InteractiveExtractor._sections_to_patterns(sections)
        assert inc is not None
        # Should match /docs/ paths via parent prefix
        assert re.search(inc, "/docs/build/page1")
        assert re.search(inc, "/docs/api/page1")
        # Should NOT contain sub-section-specific prefixes (uses parent)
        assert "build" not in inc

    def test_partial_sub_selection_uses_sub_prefixes(self):
        sections = [
            NavSection(
                label="Docs", url="", path_prefix="/docs/", selected=True,
                sub_sections=[
                    NavSubSection(
                        label="Build", path_prefix="/docs/build/", selected=True,
                    ),
                    NavSubSection(
                        label="API", path_prefix="/docs/api/", selected=False,
                    ),
                ],
            ),
        ]
        inc, exc = InteractiveExtractor._sections_to_patterns(sections)
        assert inc is not None
        assert re.search(inc, "/docs/build/page1")
        assert not re.search(inc, "/docs/api/page1")

    def test_no_subs_selected_returns_none(self):
        sections = [
            NavSection(
                label="Docs", url="", path_prefix="/docs/", selected=False,
                sub_sections=[
                    NavSubSection(
                        label="Build", path_prefix="/docs/build/", selected=False,
                    ),
                    NavSubSection(
                        label="API", path_prefix="/docs/api/", selected=False,
                    ),
                ],
            ),
        ]
        inc, exc = InteractiveExtractor._sections_to_patterns(sections)
        assert inc is None


class TestSubSectionAddressParsing:
    """Test the 2a-style address parsing in InteractiveExtractor."""

    def setup_method(self):
        self.extractor = InteractiveExtractor()

    def test_valid_address(self):
        result = self.extractor._parse_sub_section_address("2a")
        assert result == (1, 0)

    def test_second_sub(self):
        result = self.extractor._parse_sub_section_address("1c")
        assert result == (0, 2)

    def test_double_digit_section(self):
        result = self.extractor._parse_sub_section_address("12b")
        assert result == (11, 1)

    def test_plain_number_returns_none(self):
        result = self.extractor._parse_sub_section_address("3")
        assert result is None

    def test_invalid_returns_none(self):
        result = self.extractor._parse_sub_section_address("abc")
        assert result is None

    def test_uppercase_returns_none(self):
        result = self.extractor._parse_sub_section_address("2A")
        assert result is None
