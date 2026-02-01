"""Tests for pattern detection models."""

from doc_retrieval.patterns.registry import (
    DetectionSignal,
    Phase2Check,
    SitePattern,
)


class TestPhase2Check:
    def test_create_css_present(self):
        check = Phase2Check(kind="css_present", value=".my-class", weight=20)
        assert check.kind == "css_present"
        assert check.value == ".my-class"
        assert check.weight == 20
        assert check.required is False

    def test_create_required_check(self):
        check = Phase2Check(kind="css_present", value=".must-have", required=True)
        assert check.required is True

    def test_css_absent_kind(self):
        check = Phase2Check(kind="css_absent", value=".sphinxsidebar")
        assert check.kind == "css_absent"

    def test_script_src_regex_kind(self):
        check = Phase2Check(kind="script_src_regex", value=r"redoc\.standalone")
        assert check.kind == "script_src_regex"

    def test_content_min_length_kind(self):
        check = Phase2Check(kind="content_min_length", value="500")
        assert check.kind == "content_min_length"


class TestSitePatternHierarchy:
    def test_default_no_parent(self):
        p = SitePattern(name="test", description="Test pattern")
        assert p.parent is None
        assert p.specificity == 0

    def test_parent_field(self):
        p = SitePattern(
            name="test-child", description="Child", parent="test-parent"
        )
        assert p.parent == "test-parent"

    def test_phase_fields_default_empty(self):
        p = SitePattern(name="test", description="Test")
        assert p.phase1_signals == []
        assert p.phase2_checks == []

    def test_phase1_signals(self):
        p = SitePattern(
            name="test",
            description="Test",
            phase1_signals=[
                DetectionSignal(kind="meta_generator", value="test", weight=50),
            ],
        )
        assert len(p.phase1_signals) == 1

    def test_phase2_checks(self):
        p = SitePattern(
            name="test",
            description="Test",
            phase2_checks=[
                Phase2Check(kind="css_present", value=".test", weight=20),
            ],
        )
        assert len(p.phase2_checks) == 1

    def test_backward_compat_detection_signals_still_works(self):
        """Old detection_signals field should still be accepted."""
        p = SitePattern(
            name="test",
            description="Test",
            detection_signals=[
                DetectionSignal(kind="html_substring", value="test", weight=10),
            ],
        )
        assert len(p.detection_signals) == 1
