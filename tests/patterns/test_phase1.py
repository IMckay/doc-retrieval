"""Tests for Phase 1 signal scoring."""

from doc_retrieval.patterns.registry import (
    DetectionSignal,
    PatternRegistry,
    SitePattern,
)

# Minimal test pattern for Phase 1 scoring
_TEST_PATTERN = SitePattern(
    name="_test_phase1",
    description="Test pattern for Phase 1",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="testgen", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__test_marker", weight=30),
        DetectionSignal(kind="url_substring", value="testdocs.io", weight=25),
        DetectionSignal(kind="http_header", value="x-test-engine", weight=40),
    ],
)


class TestPhase1Scoring:
    def test_meta_generator_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html='<meta name="generator" content="TestGen v2.0">',
            headers={},
        )
        assert score >= 50
        assert any("meta_generator" in m for m in matched)

    def test_html_substring_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html="<div>__test_marker</div>",
            headers={},
        )
        assert score >= 30
        assert any("html_substring" in m for m in matched)

    def test_url_substring_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://testdocs.io/guide",
            html="<html></html>",
            headers={},
        )
        assert score >= 25
        assert any("url_substring" in m for m in matched)

    def test_http_header_match_presence(self):
        """Header name only (no colon) -- checks presence."""
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html="<html></html>",
            headers={"x-test-engine": "v1.0"},
        )
        assert score >= 40
        assert any("http_header" in m for m in matched)

    def test_http_header_match_value(self):
        """Header with colon -- checks header value contains substring."""
        pattern = SitePattern(
            name="_test_hdr",
            description="Test",
            phase1_signals=[
                DetectionSignal(
                    kind="http_header",
                    value="x-powered-by:mintlify",
                    weight=40,
                    case_sensitive=False,
                ),
            ],
        )
        score, matched = PatternRegistry._score_phase1(
            pattern=pattern,
            url="https://example.com",
            html="<html></html>",
            headers={"x-powered-by": "Mintlify/3.0"},
        )
        assert score >= 40

    def test_http_header_no_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html="<html></html>",
            headers={},
        )
        assert not any("http_header:x-test-engine" in m for m in matched)

    def test_case_insensitive_meta_generator(self):
        score, _ = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html='<meta name="generator" content="TESTGEN">',
            headers={},
        )
        assert score >= 50

    def test_no_signals_returns_zero(self):
        empty = SitePattern(name="_empty", description="No signals")
        score, matched = PatternRegistry._score_phase1(
            pattern=empty,
            url="https://example.com",
            html="<html></html>",
            headers={},
        )
        assert score == 0
        assert matched == []

    def test_multiple_signals_sum(self):
        """All signals matching should sum their weights."""
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://testdocs.io/guide",
            html='<meta name="generator" content="testgen"><div>__test_marker</div>',
            headers={"x-test-engine": "v1"},
        )
        assert score == 50 + 30 + 25 + 40
        assert len(matched) == 4
