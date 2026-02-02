"""Tests for scanner.parsers — navigation extraction logic."""

from doc_retrieval.scanner.parsers import (
    _is_nav_worthy,
    group_links_into_sections,
    parse_generic_nav,
    parse_header_nav,
    parse_sidebar_nav,
    parse_subsection_links,
    parse_with_selectors,
)

BASE = "https://docs.example.com"


# ---------------------------------------------------------------------------
# Fixtures: HTML snippets
# ---------------------------------------------------------------------------

HEADER_NAV_HTML = """
<html>
<head><title>Example Docs</title></head>
<body>
<header>
  <nav>
    <a href="/docs/">Docs</a>
    <a href="/guides/">Guides</a>
    <a href="/api-reference/">API Reference</a>
    <a href="/pricing/">Pricing</a>
    <a href="https://other.com/external">External</a>
    <a href="#">Empty Hash</a>
    <a href="javascript:void(0)">JS Link</a>
  </nav>
</header>
<main><p>Content</p></main>
</body>
</html>
"""

SIDEBAR_NAV_HTML = """
<html><body>
<aside>
  <nav>
    <a href="/docs/getting-started/">Getting Started</a>
    <a href="/docs/installation/">Installation</a>
    <a href="/docs/configuration/">Configuration</a>
  </nav>
</aside>
<main><p>Content</p></main>
</body></html>
"""

SIDEBAR_CLASS_HTML = """
<html><body>
<div class="sidebar-container">
  <a href="/docs/intro/">Intro</a>
  <a href="/docs/advanced/">Advanced</a>
</div>
<main><p>Content</p></main>
</body></html>
"""

DOCUSAURUS_NAV_HTML = """
<html><body>
<nav>
  <div class="navbar__items">
    <div class="navbar__item"><a href="/docs/">Docs</a></div>
    <div class="navbar__item dropdown">
      <a>API</a>
      <div class="dropdown__menu">
        <a href="/api/rest/">REST API</a>
        <a href="/api/graphql/">GraphQL API</a>
      </div>
    </div>
  </div>
</nav>
<main><p>Content</p></main>
</body></html>
"""

EMPTY_NAV_HTML = """
<html><body>
<header><nav></nav></header>
<main><p>Only content here</p></main>
</body></html>
"""


# ---------------------------------------------------------------------------
# _is_nav_worthy
# ---------------------------------------------------------------------------

class TestIsNavWorthy:
    def test_same_domain_doc_url(self):
        assert _is_nav_worthy("https://docs.example.com/docs/intro/", BASE)

    def test_cross_domain_rejected(self):
        assert not _is_nav_worthy("https://other.com/docs/", BASE)

    def test_asset_url_rejected(self):
        assert not _is_nav_worthy("https://docs.example.com/static/image.png", BASE)

    def test_login_rejected(self):
        assert not _is_nav_worthy("https://docs.example.com/login/", BASE)

    def test_pricing_rejected(self):
        assert not _is_nav_worthy("https://docs.example.com/pricing/", BASE)

    def test_empty_path_rejected(self):
        assert not _is_nav_worthy("https://docs.example.com/", BASE)

    def test_blog_rejected(self):
        assert not _is_nav_worthy("https://docs.example.com/blog/post-1", BASE)


# ---------------------------------------------------------------------------
# parse_header_nav
# ---------------------------------------------------------------------------

class TestParseHeaderNav:
    def test_extracts_same_domain_links(self):
        links = parse_header_nav(HEADER_NAV_HTML, BASE)
        urls = {lnk.url for lnk in links}
        assert f"{BASE}/docs/" in urls
        assert f"{BASE}/guides/" in urls
        assert f"{BASE}/api-reference/" in urls

    def test_skips_external_links(self):
        links = parse_header_nav(HEADER_NAV_HTML, BASE)
        urls = {lnk.url for lnk in links}
        assert not any("other.com" in u for u in urls)

    def test_skips_pricing(self):
        links = parse_header_nav(HEADER_NAV_HTML, BASE)
        urls = {lnk.url for lnk in links}
        assert not any("pricing" in u for u in urls)

    def test_skips_hash_and_js(self):
        links = parse_header_nav(HEADER_NAV_HTML, BASE)
        labels = {lnk.label for lnk in links}
        assert "Empty Hash" not in labels
        assert "JS Link" not in labels

    def test_empty_nav_returns_empty(self):
        links = parse_header_nav(EMPTY_NAV_HTML, BASE)
        assert links == []


# ---------------------------------------------------------------------------
# parse_sidebar_nav
# ---------------------------------------------------------------------------

class TestParseSidebarNav:
    def test_extracts_aside_nav_links(self):
        links = parse_sidebar_nav(SIDEBAR_NAV_HTML, BASE)
        assert len(links) == 3
        labels = {lnk.label for lnk in links}
        assert "Getting Started" in labels
        assert "Installation" in labels

    def test_extracts_sidebar_class_links(self):
        links = parse_sidebar_nav(SIDEBAR_CLASS_HTML, BASE)
        assert len(links) == 2


# ---------------------------------------------------------------------------
# parse_with_selectors
# ---------------------------------------------------------------------------

class TestParseWithSelectors:
    def test_docusaurus_selectors(self):
        selectors = [
            ".navbar__items > .navbar__item:not(.dropdown) > a",
            ".dropdown__menu a",
        ]
        links = parse_with_selectors(DOCUSAURUS_NAV_HTML, BASE, selectors)
        # Should find /docs/, /api/rest/, /api/graphql/ but not the dropdown trigger
        urls = {lnk.url for lnk in links}
        assert f"{BASE}/docs/" in urls
        assert f"{BASE}/api/rest/" in urls
        assert f"{BASE}/api/graphql/" in urls

    def test_empty_selectors_returns_empty(self):
        links = parse_with_selectors(HEADER_NAV_HTML, BASE, [])
        assert links == []


# ---------------------------------------------------------------------------
# parse_generic_nav
# ---------------------------------------------------------------------------

class TestParseGenericNav:
    def test_combines_header_and_sidebar(self):
        html = """
        <html><body>
        <header><nav>
            <a href="/docs/">Docs</a>
        </nav></header>
        <aside><nav>
            <a href="/guides/">Guides</a>
        </nav></aside>
        </body></html>
        """
        links = parse_generic_nav(html, BASE)
        urls = {lnk.url for lnk in links}
        assert f"{BASE}/docs/" in urls
        assert f"{BASE}/guides/" in urls

    def test_deduplicates(self):
        html = """
        <html><body>
        <header><nav>
            <a href="/docs/">Docs</a>
        </nav></header>
        <aside><nav>
            <a href="/docs/">Docs Again</a>
        </nav></aside>
        </body></html>
        """
        links = parse_generic_nav(html, BASE)
        doc_links = [lnk for lnk in links if lnk.url == f"{BASE}/docs/"]
        assert len(doc_links) == 1


# ---------------------------------------------------------------------------
# group_links_into_sections
# ---------------------------------------------------------------------------

class TestGroupLinksIntoSections:
    def test_groups_by_first_segment(self):
        from doc_retrieval.scanner.models import NavLink
        links = [
            NavLink(label="Intro", url=f"{BASE}/docs/intro/", path="/docs/intro/"),
            NavLink(label="API", url=f"{BASE}/api/rest/", path="/api/rest/"),
            NavLink(label="Advanced", url=f"{BASE}/docs/advanced/", path="/docs/advanced/"),
        ]
        sections = group_links_into_sections(links)
        prefixes = {s.path_prefix for s in sections}
        assert "/docs/" in prefixes
        assert "/api/" in prefixes

    def test_empty_input(self):
        sections = group_links_into_sections([])
        assert sections == []

    def test_section_uses_root_as_label(self):
        from doc_retrieval.scanner.models import NavLink
        links = [
            NavLink(label="Docs Home", url=f"{BASE}/docs/", path="/docs/"),
            NavLink(label="Intro", url=f"{BASE}/docs/intro/", path="/docs/intro/"),
        ]
        sections = group_links_into_sections(links)
        docs_section = [s for s in sections if s.path_prefix == "/docs/"][0]
        assert docs_section.label == "Docs Home"
        assert len(docs_section.children) == 1


# ---------------------------------------------------------------------------
# parse_subsection_links
# ---------------------------------------------------------------------------

class TestParseSubsectionLinks:
    def test_filters_to_parent_prefix(self):
        html = """
        <html><body>
        <header><nav>
            <a href="/docs/intro/">Intro</a>
            <a href="/api/rest/">REST API</a>
        </nav></header>
        </body></html>
        """
        links = parse_subsection_links(html, BASE, "/docs/")
        urls = {lnk.url for lnk in links}
        assert f"{BASE}/docs/intro/" in urls
        assert f"{BASE}/api/rest/" not in urls
