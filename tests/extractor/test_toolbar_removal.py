"""Tests for CSS removal of PageActions toolbar elements from HTML."""

from doc_retrieval.config import ExtractorConfig
from doc_retrieval.extractor.main_content import ContentExtractor


def _make_extractor(**kwargs) -> ContentExtractor:
    return ContentExtractor(ExtractorConfig(**kwargs))


# HTML containing styled-component toolbar elements with hash suffixes.
TOOLBAR_HTML = """
<html><body>
<main>
  <article>
    <h1>API Reference</h1>
    <div class="PageActions__PageActionsWrapper-sc-abc123">
      <button class="PageActionsMenuItem__Wrapper-sc-def456">Copy</button>
      <div class="Dropdown__DropdownWrapper-sc-ghi789">
        <span>Copy for LLM</span>
      </div>
    </div>
    <p>This is the actual API documentation content that should be preserved through extraction.</p>
    <div class="Rating__RatingWrapper-sc-jkl012">
      <h3>Was this page helpful?</h3>
      <button>Yes</button>
      <button>No</button>
    </div>
    <nav class="PageNavigation__Wrapper-sc-mno345">
      <a href="/prev">Previous</a>
      <a href="/next">Next</a>
    </nav>
  </article>
</main>
</body></html>
"""


class TestToolbarRemoval:
    """Test that PageActions and related elements are removed by CSS selectors."""

    REMOVE_SELECTORS = [
        "aside",
        "nav",
        "header",
        "footer",
        '[class*="PageActions__"]',
        '[class*="PageActionsMenuItem__"]',
        '[class*="Dropdown__"]',
        '[class*="Rating__"]',
        '[class*="PageNavigation__"]',
    ]

    def test_page_actions_removed(self):
        ext = _make_extractor(
            content_selectors=["article", "main"],
            remove_selectors=self.REMOVE_SELECTORS,
            min_content_length=10,
        )
        result = ext.extract(TOOLBAR_HTML, url="https://example.com/api")
        assert result is not None
        assert "API Reference" in result.text
        assert "actual API documentation" in result.text
        # Toolbar elements should be gone
        assert "Copy for LLM" not in result.text

    def test_rating_removed(self):
        ext = _make_extractor(
            content_selectors=["article", "main"],
            remove_selectors=self.REMOVE_SELECTORS,
            min_content_length=10,
        )
        result = ext.extract(TOOLBAR_HTML, url="https://example.com/api")
        assert result is not None
        assert "Was this page helpful?" not in result.text

    def test_page_navigation_removed(self):
        ext = _make_extractor(
            content_selectors=["article", "main"],
            remove_selectors=self.REMOVE_SELECTORS,
            min_content_length=10,
        )
        result = ext.extract(TOOLBAR_HTML, url="https://example.com/api")
        assert result is not None
        assert "Previous" not in result.text
        assert "Next" not in result.text

    def test_content_preserved(self):
        ext = _make_extractor(
            content_selectors=["article", "main"],
            remove_selectors=self.REMOVE_SELECTORS,
            min_content_length=10,
        )
        result = ext.extract(TOOLBAR_HTML, url="https://example.com/api")
        assert result is not None
        assert "actual API documentation content" in result.text
