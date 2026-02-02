# tests/patterns/test_pattern_definitions.py
"""Tests verifying all built-in pattern definitions are valid."""

import pytest

from doc_retrieval.patterns.registry import PatternRegistry, SitePattern


class TestPatternDefinitions:
    def test_all_patterns_have_phase1_signals(self):
        """Every pattern (except children with no own signals) has phase1_signals."""
        for p in PatternRegistry.list_patterns():
            if p.parent:
                continue  # Children may inherit candidacy
            assert len(p.phase1_signals) > 0, f"{p.name} has no phase1_signals"

    def test_no_pattern_uses_old_detection_signals(self):
        """Old detection_signals field should be empty on all built-in patterns."""
        for p in PatternRegistry.list_patterns():
            assert p.detection_signals == [], (
                f"{p.name} still uses old detection_signals field"
            )

    def test_hierarchy_parents_exist(self):
        """Every pattern with a parent references an existing pattern."""
        names = {p.name for p in PatternRegistry.list_patterns()}
        for p in PatternRegistry.list_patterns():
            if p.parent:
                assert p.parent in names, (
                    f"{p.name} has parent '{p.parent}' which doesn't exist"
                )

    def test_child_specificity_greater_than_parent(self):
        patterns = {p.name: p for p in PatternRegistry.list_patterns()}
        for p in patterns.values():
            if p.parent:
                parent = patterns[p.parent]
                assert p.specificity > parent.specificity, (
                    f"{p.name} (specificity={p.specificity}) should be > "
                    f"parent {p.parent} (specificity={parent.specificity})"
                )

    def test_docusaurus_openapi_is_child_of_docusaurus(self):
        p = PatternRegistry.get("docusaurus-openapi")
        assert p is not None
        assert p.parent == "docusaurus"
        assert p.specificity == 1

    def test_docusaurus_openapi_has_required_check(self):
        p = PatternRegistry.get("docusaurus-openapi")
        assert p is not None
        required = [c for c in p.phase2_checks if c.required]
        assert len(required) >= 1, "docusaurus-openapi needs at least one required Phase 2 check"

    def test_all_patterns_registered(self):
        names = {p.name for p in PatternRegistry.list_patterns()}
        expected = {
            "docusaurus", "docusaurus-openapi", "gitbook", "readthedocs",
            "mkdocs", "sphinx", "vitepress", "mintlify", "nextra",
            "swagger-ui", "redoc", "redocly-realm", "starlight",
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

    @pytest.mark.parametrize("name", [
        "docusaurus", "gitbook", "readthedocs", "mkdocs", "sphinx",
        "vitepress", "mintlify", "nextra", "swagger-ui", "redoc",
        "redocly-realm", "starlight",
    ])
    def test_pattern_has_content_selectors(self, name: str):
        p = PatternRegistry.get(name)
        assert p is not None
        assert len(p.content_selectors) > 0

    @pytest.mark.parametrize("name", [
        "docusaurus", "gitbook", "readthedocs", "mkdocs", "sphinx",
        "vitepress", "mintlify", "nextra", "swagger-ui", "redoc",
        "redocly-realm", "starlight",
    ])
    def test_pattern_has_description(self, name: str):
        p = PatternRegistry.get(name)
        assert p is not None
        assert len(p.description) > 0

    def test_redocly_realm_requires_js(self):
        p = PatternRegistry.get("redocly-realm")
        assert p is not None
        assert p.requires_js is True

    def test_redocly_realm_has_api_content_selector(self):
        p = PatternRegistry.get("redocly-realm")
        assert p is not None
        assert ".redoc-wrap .api-content" in p.content_selectors

    def test_redocly_realm_has_section_fields(self):
        p = PatternRegistry.get("redocly-realm")
        assert p is not None
        assert p.section_url_pattern is not None
        assert p.section_selector_template is not None

    def test_redocly_realm_removes_page_actions_toolbar(self):
        p = PatternRegistry.get("redocly-realm")
        assert p is not None
        # Should have PageActions__ selectors (not old CopyForLlm)
        pa_selectors = [s for s in p.remove_selectors if "PageActions__" in s]
        assert len(pa_selectors) >= 1
        # Should not have old CopyForLlm selectors
        old_selectors = [s for s in p.remove_selectors if "CopyForLlm" in s]
        assert len(old_selectors) == 0

    def test_redocly_realm_removes_rating(self):
        p = PatternRegistry.get("redocly-realm")
        assert p is not None
        rating_selectors = [s for s in p.remove_selectors if "Rating__" in s]
        assert len(rating_selectors) >= 1

    def test_redocly_realm_has_markdown_cleanup_patterns(self):
        p = PatternRegistry.get("redocly-realm")
        assert p is not None
        assert len(p.markdown_cleanup_patterns) >= 2

    def test_redocly_realm_has_section_url_patterns(self):
        p = PatternRegistry.get("redocly-realm")
        assert p is not None
        assert len(p.section_url_patterns) >= 2
        # Should cover both /references/ and /guides/ paths
        patterns_joined = " ".join(p.section_url_patterns)
        assert "references" in patterns_joined
        assert "guides" in patterns_joined
