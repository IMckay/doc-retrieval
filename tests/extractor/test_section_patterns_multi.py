"""Tests for multi-pattern section narrowing in ContentExtractor."""

from doc_retrieval.config import ExtractorConfig
from doc_retrieval.extractor.main_content import ContentExtractor


def _make_extractor(**kwargs) -> ContentExtractor:
    return ContentExtractor(ExtractorConfig(**kwargs))


# HTML with section containers for both /references/ and /guides/ URL structures.
MULTI_SECTION_HTML = """
<html><body>
<div class="redoc-wrap">
  <div class="api-content">
    <div id="contacts/listcontacts">
      <h2>List Contacts</h2>
      <p>Returns a list of contacts. Enough text to pass min_content_length threshold easily.</p>
    </div>
    <div id="messages/sendmessage">
      <h2>Send Message</h2>
      <p>Sends a message to a contact. Enough text to pass min_content_length threshold easily.</p>
    </div>
  </div>
</div>
</body></html>
"""


class TestMultiPatternSectionNarrowing:
    def test_references_url_matches_first_pattern(self):
        """A /references/ URL matches the first section_url_patterns entry."""
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_patterns=[
                r"/references/.+?/api\.[^/]+/(.+)$",
                r"/guides/.+?/api(?:-[^/]+)?/(.+)$",
            ],
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        result = ext.extract(
            MULTI_SECTION_HTML,
            url="https://example.com/references/rest/api.v1/contacts/listcontacts",
        )
        assert result is not None
        assert "List Contacts" in result.text
        assert "Send Message" not in result.text

    def test_guides_url_matches_second_pattern(self):
        """A /guides/ URL matches the second section_url_patterns entry."""
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_patterns=[
                r"/references/.+?/api\.[^/]+/(.+)$",
                r"/guides/.+?/api(?:-[^/]+)?/(.+)$",
            ],
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        result = ext.extract(
            MULTI_SECTION_HTML,
            url="https://example.com/guides/fin-custom-helpdesk/api-helpdesk/messages/sendmessage",
        )
        assert result is not None
        assert "Send Message" in result.text
        assert "List Contacts" not in result.text

    def test_no_url_match_returns_full_container(self):
        """When no pattern matches the URL, full container is returned."""
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_patterns=[
                r"/references/.+?/api\.[^/]+/(.+)$",
                r"/guides/.+?/api(?:-[^/]+)?/(.+)$",
            ],
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        result = ext.extract(
            MULTI_SECTION_HTML,
            url="https://example.com/docs/getting-started",
        )
        assert result is not None
        assert "List Contacts" in result.text
        assert "Send Message" in result.text

    def test_legacy_singular_field_backward_compat(self):
        """Legacy section_url_pattern (singular) is used when section_url_patterns is empty."""
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_pattern=r"/references/.+?/api\.[^/]+/(.+)$",
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        result = ext.extract(
            MULTI_SECTION_HTML,
            url="https://example.com/references/rest/api.v1/contacts/listcontacts",
        )
        assert result is not None
        assert "List Contacts" in result.text
        assert "Send Message" not in result.text

    def test_legacy_singular_appended_when_not_in_list(self):
        """Legacy singular field is appended to patterns list if not already present."""
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_patterns=[
                r"/guides/.+?/api(?:-[^/]+)?/(.+)$",
            ],
            section_url_pattern=r"/references/.+?/api\.[^/]+/(.+)$",
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        # The /references/ pattern comes from the legacy field, appended after the list
        result = ext.extract(
            MULTI_SECTION_HTML,
            url="https://example.com/references/rest/api.v1/contacts/listcontacts",
        )
        assert result is not None
        assert "List Contacts" in result.text
        assert "Send Message" not in result.text

    def test_no_template_is_noop(self):
        """Without section_selector_template, narrowing is a no-op regardless of patterns."""
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_patterns=[
                r"/references/.+?/api\.[^/]+/(.+)$",
            ],
            min_content_length=10,
        )
        result = ext.extract(
            MULTI_SECTION_HTML,
            url="https://example.com/references/rest/api.v1/contacts/listcontacts",
        )
        assert result is not None
        # Without template, both sections are returned
        assert "List Contacts" in result.text
        assert "Send Message" in result.text
