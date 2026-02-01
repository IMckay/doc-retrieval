# tests/patterns/test_phase2.py
"""Tests for Phase 2 DOM-aware scoring."""

import pytest

from doc_retrieval.patterns.registry import (
    PatternRegistry,
    Phase2Check,
    SitePattern,
)


def _make_pattern(checks: list[Phase2Check]) -> SitePattern:
    return SitePattern(
        name="_test_p2", description="Test", phase2_checks=checks
    )


SIMPLE_HTML = """
<html>
<head><script src="/assets/redoc.standalone.js"></script></head>
<body>
<main>
  <article class="markdown">
    <div class="openapi-left-panel__container">
        <p>Some API documentation content that is long enough to pass length checks
        and contains meaningful text about endpoints and parameters.</p>
    </div>
  </article>
</main>
</body>
</html>
"""


class TestPhase2CssPresent:
    def test_css_present_hit(self):
        p = _make_pattern([Phase2Check(kind="css_present", value="article.markdown", weight=20)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 20
        assert len(matched) == 1
        assert not disqualified

    def test_css_present_miss(self):
        p = _make_pattern([Phase2Check(kind="css_present", value=".nonexistent-class", weight=20)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0
        assert matched == []
        assert not disqualified

    def test_css_present_required_miss_disqualifies(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value=".nonexistent", weight=30, required=True),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert disqualified

    def test_css_present_required_hit_does_not_disqualify(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value="article.markdown", weight=30, required=True),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 30
        assert not disqualified


class TestPhase2CssAbsent:
    def test_css_absent_hit(self):
        """Element NOT present -> css_absent scores."""
        p = _make_pattern([Phase2Check(kind="css_absent", value=".sphinxsidebar", weight=15)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 15

    def test_css_absent_miss(self):
        """Element IS present -> css_absent does NOT score."""
        p = _make_pattern([Phase2Check(kind="css_absent", value="article.markdown", weight=15)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0

    def test_css_absent_required_miss_disqualifies(self):
        """Element IS present when it shouldn't be -> disqualify."""
        p = _make_pattern([
            Phase2Check(kind="css_absent", value="article.markdown", weight=15, required=True),
        ])
        _, _, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert disqualified


class TestPhase2ScriptSrcRegex:
    def test_script_src_regex_hit(self):
        p = _make_pattern([
            Phase2Check(kind="script_src_regex", value=r"redoc\.standalone", weight=25),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 25

    def test_script_src_regex_miss(self):
        p = _make_pattern([
            Phase2Check(kind="script_src_regex", value=r"swagger-ui-bundle", weight=25),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0


class TestPhase2ContentMinLength:
    def test_content_min_length_pass(self):
        p = _make_pattern([Phase2Check(kind="content_min_length", value="10", weight=10)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 10

    def test_content_min_length_fail(self):
        short_html = "<html><body><main><p>Hi</p></main></body></html>"
        p = _make_pattern([Phase2Check(kind="content_min_length", value="5000", weight=10)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, short_html)
        assert score == 0


class TestPhase2MultipleChecks:
    def test_scores_sum(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value="article.markdown", weight=20),
            Phase2Check(kind="css_absent", value=".sphinxsidebar", weight=15),
            Phase2Check(kind="script_src_regex", value=r"redoc\.standalone", weight=25),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 20 + 15 + 25
        assert len(matched) == 3
        assert not disqualified

    def test_one_required_fail_disqualifies_all(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value="article.markdown", weight=20),
            Phase2Check(kind="css_present", value=".nonexistent", weight=30, required=True),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert disqualified

    def test_empty_checks(self):
        p = _make_pattern([])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0
        assert matched == []
        assert not disqualified
