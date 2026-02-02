"""Tests for PatternRegistry.apply_to_config()."""

from doc_retrieval.config import AppConfig, ExtractorConfig, FetcherConfig
from doc_retrieval.patterns.registry import PatternRegistry, SitePattern


def _register_test_pattern() -> SitePattern:
    p = SitePattern(
        name="_test_apply",
        description="Test apply",
        content_selectors=[".test-content", ".test-article"],
        remove_selectors=[".test-nav", ".test-footer"],
        requires_js=True,
        wait_selector=".test-main",
        wait_time_ms=500,
        click_tabs_selector='.test-tabs [role="tab"]',
    )
    PatternRegistry.register(p)
    return p


class TestApplyToConfig:
    def setup_method(self):
        self._original = dict(PatternRegistry._patterns)
        _register_test_pattern()

    def teardown_method(self):
        PatternRegistry._patterns = self._original

    def test_fills_default_fetcher_fields(self):
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.wait_selector == ".test-main"
        assert result.fetcher.wait_time_ms == 500
        assert result.fetcher.click_tabs_selector == '.test-tabs [role="tab"]'
        assert result.fetcher.use_js is True

    def test_does_not_override_explicit_wait_selector(self):
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(wait_selector=".user-custom"),
        )
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.wait_selector == ".user-custom"

    def test_does_not_override_explicit_wait_time(self):
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(wait_time_ms=2000),
        )
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.wait_time_ms == 2000

    def test_replaces_extractor_selectors(self):
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.extractor.content_selectors == [".test-content", ".test-article"]
        assert result.extractor.remove_selectors == [".test-nav", ".test-footer"]

    def test_unknown_pattern_returns_unchanged(self):
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("nonexistent", config)
        assert result.fetcher.wait_selector is None
        assert result.extractor.content_selectors == config.extractor.content_selectors

    def test_original_config_not_mutated(self):
        config = AppConfig(base_url="https://example.com")
        original_wait = config.fetcher.wait_selector
        PatternRegistry.apply_to_config("_test_apply", config)
        assert config.fetcher.wait_selector == original_wait

    def test_enables_js_when_pattern_requires_it(self):
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(use_js=False),
        )
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.use_js is True

    def test_no_js_pattern_preserves_user_choice(self):
        """A pattern that doesn't require JS shouldn't force it on."""
        no_js = SitePattern(
            name="_test_no_js",
            description="No JS",
            requires_js=False,
            content_selectors=[".static"],
        )
        PatternRegistry.register(no_js)
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(use_js=False),
        )
        result = PatternRegistry.apply_to_config("_test_no_js", config)
        assert result.fetcher.use_js is False

    def test_section_fields_propagate(self):
        """Section extraction fields from pattern fill into extractor config."""
        p = SitePattern(
            name="_test_section",
            description="Section test",
            content_selectors=[".api-content"],
            section_url_pattern=r"/api/(.+)$",
            section_selector_template='[id="{section}"]',
        )
        PatternRegistry.register(p)
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_section", config)
        assert result.extractor.section_url_pattern == r"/api/(.+)$"
        assert result.extractor.section_selector_template == '[id="{section}"]'

    def test_section_fields_not_overridden_when_set(self):
        """Explicit user section fields are not overridden by pattern."""
        p = SitePattern(
            name="_test_section2",
            description="Section test 2",
            content_selectors=[".api-content"],
            section_url_pattern=r"/api/(.+)$",
            section_selector_template='[id="{section}"]',
        )
        PatternRegistry.register(p)
        config = AppConfig(
            base_url="https://example.com",
            extractor=ExtractorConfig(
                section_url_pattern=r"/custom/(.+)$",
                section_selector_template='[data-id="{section}"]',
            ),
        )
        result = PatternRegistry.apply_to_config("_test_section2", config)
        assert result.extractor.section_url_pattern == r"/custom/(.+)$"
        assert result.extractor.section_selector_template == '[data-id="{section}"]'

    def test_pattern_without_section_fields_leaves_none(self):
        """Patterns without section fields leave extractor defaults (None)."""
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.extractor.section_url_pattern is None
        assert result.extractor.section_selector_template is None

    def test_section_url_patterns_propagate(self):
        """Multi-pattern section_url_patterns propagate through apply_to_config."""
        p = SitePattern(
            name="_test_multi_section",
            description="Multi-section test",
            content_selectors=[".api-content"],
            section_url_patterns=[
                r"/references/.+?/api\.[^/]+/(.+)$",
                r"/guides/.+?/api(?:-[^/]+)?/(.+)$",
            ],
            section_selector_template='[id="{section}"]',
        )
        PatternRegistry.register(p)
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_multi_section", config)
        assert result.extractor.section_url_patterns == [
            r"/references/.+?/api\.[^/]+/(.+)$",
            r"/guides/.+?/api(?:-[^/]+)?/(.+)$",
        ]

    def test_section_url_patterns_not_overridden_when_set(self):
        """Explicit user section_url_patterns are not overridden by pattern."""
        p = SitePattern(
            name="_test_multi_section2",
            description="Multi-section test 2",
            content_selectors=[".api-content"],
            section_url_patterns=[r"/pattern/(.+)$"],
        )
        PatternRegistry.register(p)
        config = AppConfig(
            base_url="https://example.com",
            extractor=ExtractorConfig(
                section_url_patterns=[r"/custom/(.+)$"],
            ),
        )
        result = PatternRegistry.apply_to_config("_test_multi_section2", config)
        assert result.extractor.section_url_patterns == [r"/custom/(.+)$"]

    def test_markdown_cleanup_patterns_propagate(self):
        """markdown_cleanup_patterns propagate through apply_to_config."""
        p = SitePattern(
            name="_test_cleanup",
            description="Cleanup test",
            content_selectors=[".content"],
            markdown_cleanup_patterns=[r"(?m)^REMOVE_ME$"],
        )
        PatternRegistry.register(p)
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_cleanup", config)
        assert result.extractor.markdown_cleanup_patterns == [r"(?m)^REMOVE_ME$"]

    def test_markdown_cleanup_patterns_always_override(self):
        """markdown_cleanup_patterns from pattern always apply (no guard on existing)."""
        p = SitePattern(
            name="_test_cleanup2",
            description="Cleanup test 2",
            content_selectors=[".content"],
            markdown_cleanup_patterns=[r"(?m)^PATTERN_VALUE$"],
        )
        PatternRegistry.register(p)
        config = AppConfig(
            base_url="https://example.com",
            extractor=ExtractorConfig(
                markdown_cleanup_patterns=[r"(?m)^USER_VALUE$"],
            ),
        )
        result = PatternRegistry.apply_to_config("_test_cleanup2", config)
        # Pattern always overrides for cleanup patterns
        assert result.extractor.markdown_cleanup_patterns == [r"(?m)^PATTERN_VALUE$"]
