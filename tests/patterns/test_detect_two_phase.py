# tests/patterns/test_detect_two_phase.py
"""Integration tests for two-phase detection."""

import pytest

from doc_retrieval.patterns.registry import (
    DetectionSignal,
    PatternRegistry,
    Phase2Check,
    SitePattern,
)

_PARENT = SitePattern(
    name="_integ_parent",
    description="Integration parent",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="integtest", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__integtest", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".integ-content", weight=20),
    ],
)

_CHILD = SitePattern(
    name="_integ_child",
    description="Integration child",
    parent="_integ_parent",
    specificity=1,
    phase1_signals=[],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".integ-special", weight=30, required=True),
        Phase2Check(kind="css_present", value=".integ-content", weight=20),
    ],
)

_OTHER = SitePattern(
    name="_integ_other",
    description="Integration other",
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="__other_marker", weight=40),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".other-content", weight=20),
    ],
)


class TestDetectTwoPhase:
    def setup_method(self):
        self._original = dict(PatternRegistry._patterns)
        PatternRegistry._patterns.clear()
        PatternRegistry.register(_PARENT)
        PatternRegistry.register(_CHILD)
        PatternRegistry.register(_OTHER)

    def teardown_method(self):
        PatternRegistry._patterns = self._original

    def test_parent_detected_when_child_disqualified(self):
        html = """
        <html>
        <head><meta name="generator" content="IntegTest v1"></head>
        <body><main>
            <div class="integ-content">
                <p>Enough content to be meaningful for detection.</p>
            </div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is not None
        assert result.pattern.name == "_integ_parent"

    def test_child_wins_when_special_element_present(self):
        html = """
        <html>
        <head><meta name="generator" content="IntegTest v1"></head>
        <body><main>
            <div class="integ-content">
                <div class="integ-special">Special child content</div>
                <p>Main content here.</p>
            </div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is not None
        assert result.pattern.name == "_integ_child"

    def test_unrelated_pattern_detected(self):
        html = """
        <html><body><main>
            <div>__other_marker</div>
            <div class="other-content">Content</div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is not None
        assert result.pattern.name == "_integ_other"

    def test_no_match_returns_none(self):
        html = "<html><body><p>Generic page</p></body></html>"
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is None

    def test_http_header_contributes_to_detection(self):
        header_pattern = SitePattern(
            name="_integ_header",
            description="Header-detected",
            phase1_signals=[
                DetectionSignal(kind="http_header", value="x-custom-engine", weight=50),
            ],
            phase2_checks=[],
        )
        PatternRegistry.register(header_pattern)
        result = PatternRegistry.detect_two_phase(
            url="https://example.com",
            html="<html><body></body></html>",
            headers={"x-custom-engine": "v2.0"},
        )
        assert result is not None
        assert result.pattern.name == "_integ_header"

    def test_child_auto_candidacy_from_parent(self):
        """Child with no phase1_signals still becomes candidate when parent matches."""
        html = """
        <html>
        <head><meta name="generator" content="IntegTest"></head>
        <body><main>
            <div class="integ-content">
                <div class="integ-special">API docs</div>
            </div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is not None
        assert result.pattern.name == "_integ_child"
