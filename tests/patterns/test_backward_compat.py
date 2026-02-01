# tests/patterns/test_backward_compat.py
"""Tests for backward compatibility wrappers."""

from doc_retrieval.patterns import Phase2Check
from doc_retrieval.patterns.registry import PatternRegistry


class TestBackwardCompat:
    def test_detect_with_confidence_wraps_two_phase(self):
        """Old API should still work."""
        html = '<html><head><meta name="generator" content="MkDocs"></head>'
        html += '<body><div class="md-content"><p>Content</p></div></body></html>'
        result = PatternRegistry.detect_with_confidence(
            "https://example.com", html
        )
        # Should detect mkdocs via the old API
        assert result is not None
        assert result.pattern.name == "mkdocs"

    def test_detect_wraps_two_phase(self):
        """Old detect() should return pattern or None."""
        html = '<html><head><meta name="generator" content="MkDocs"></head>'
        html += '<body><div class="md-content"><p>Content</p></div></body></html>'
        pattern = PatternRegistry.detect("https://example.com", html)
        assert pattern is not None
        assert pattern.name == "mkdocs"

    def test_detect_returns_none_for_unknown(self):
        result = PatternRegistry.detect(
            "https://example.com", "<html><body>Generic</body></html>"
        )
        assert result is None


class TestPhase2CheckExport:
    def test_phase2check_importable_from_patterns_package(self):
        """Phase2Check should be importable from doc_retrieval.patterns."""
        assert Phase2Check is not None
