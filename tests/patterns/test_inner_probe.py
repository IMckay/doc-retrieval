"""Tests for inner-page probing utilities."""

from doc_retrieval.patterns.registry import PatternRegistry


class TestExtractProbeUrls:
    def test_extracts_doc_paths(self):
        html = """
        <html><body>
        <a href="/docs/getting-started">Start</a>
        <a href="/guide/intro">Guide</a>
        <a href="/api/reference">API</a>
        <a href="/blog/post-1">Blog</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        assert len(urls) <= 3
        # Doc paths should be preferred over blog
        paths = [u.split("example.com")[1] for u in urls]
        assert "/blog/post-1" not in paths
        assert any("/docs/" in p or "/guide/" in p or "/api/" in p for p in paths)

    def test_limits_to_3(self):
        html = """
        <html><body>
        <a href="/docs/a">A</a>
        <a href="/docs/b">B</a>
        <a href="/guide/c">C</a>
        <a href="/api/d">D</a>
        <a href="/reference/e">E</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        assert len(urls) == 3

    def test_falls_back_to_same_domain_links(self):
        html = """
        <html><body>
        <a href="/about">About</a>
        <a href="/features">Features</a>
        <a href="https://other.com/page">External</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        # Should pick same-domain links, not external
        assert all("example.com" in u for u in urls)

    def test_deduplicates(self):
        html = """
        <html><body>
        <a href="/docs/intro">Intro</a>
        <a href="/docs/intro">Intro again</a>
        <a href="/docs/intro#section">Intro with hash</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        # /docs/intro and /docs/intro#section should deduplicate to 1
        assert len(urls) == 1

    def test_skips_root_url(self):
        html = """
        <html><body>
        <a href="/">Home</a>
        <a href="/docs/intro">Intro</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        assert "https://example.com/" not in urls
        assert "https://example.com" not in urls

    def test_empty_html(self):
        urls = PatternRegistry._extract_probe_urls(
            html="<html></html>", base_url="https://example.com"
        )
        assert urls == []


class TestShouldProbeInnerPages:
    def test_confident_result_no_probe(self):
        assert not PatternRegistry._should_probe_inner_pages(
            best_confidence=0.7, best_score=80, second_score=30
        )

    def test_low_confidence_triggers_probe(self):
        assert PatternRegistry._should_probe_inner_pages(
            best_confidence=0.3, best_score=30, second_score=0
        )

    def test_ambiguous_scores_trigger_probe(self):
        assert PatternRegistry._should_probe_inner_pages(
            best_confidence=0.6, best_score=60, second_score=50
        )

    def test_no_result_triggers_probe(self):
        assert PatternRegistry._should_probe_inner_pages(
            best_confidence=0.0, best_score=0, second_score=0
        )
