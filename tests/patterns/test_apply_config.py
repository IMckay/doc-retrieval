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
