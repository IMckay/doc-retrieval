"""Tests for section narrowing in ContentExtractor."""

from doc_retrieval.config import ExtractorConfig
from doc_retrieval.extractor.main_content import ContentExtractor


def _make_extractor(**kwargs) -> ContentExtractor:
    return ContentExtractor(ExtractorConfig(**kwargs))


# Minimal HTML with a section container holding multiple endpoint sections.
REDOC_HTML = """
<html><body>
<div class="redoc-wrap">
  <div class="api-content">
    <div id="contacts/listcontacts">
      <h2>List Contacts</h2>
      <p>Returns a list of contacts. Enough text to pass min_content_length threshold easily.</p>
    </div>
    <div id="contacts/createcontact">
      <h2>Create Contact</h2>
      <p>Creates a new contact. Enough text to pass min_content_length threshold easily.</p>
    </div>
  </div>
</div>
</body></html>
"""


class TestSectionNarrowing:
    def test_url_match_extracts_section(self):
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_pattern=r"/references/.+?/api\.[^/]+/(.+)$",
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        result = ext.extract(
            REDOC_HTML,
            url="https://example.com/references/rest/api.v1/contacts/listcontacts",
        )
        assert result is not None
        assert "List Contacts" in result.text
        assert "Create Contact" not in result.text

    def test_url_no_match_returns_full_container(self):
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_pattern=r"/references/.+?/api\.[^/]+/(.+)$",
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        result = ext.extract(
            REDOC_HTML,
            url="https://example.com/docs/getting-started",
        )
        assert result is not None
        assert "List Contacts" in result.text
        assert "Create Contact" in result.text

    def test_no_section_fields_is_noop(self):
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            min_content_length=10,
        )
        result = ext.extract(
            REDOC_HTML,
            url="https://example.com/references/rest/api.v1/contacts/listcontacts",
        )
        assert result is not None
        # Without section fields, both sections are returned
        assert "List Contacts" in result.text
        assert "Create Contact" in result.text

    def test_section_id_not_in_dom_returns_full_container(self):
        ext = _make_extractor(
            content_selectors=[".redoc-wrap .api-content"],
            section_url_pattern=r"/references/.+?/api\.[^/]+/(.+)$",
            section_selector_template='[id="{section}"]',
            min_content_length=10,
        )
        result = ext.extract(
            REDOC_HTML,
            url="https://example.com/references/rest/api.v1/nonexistent/endpoint",
        )
        assert result is not None
        # Falls back to full container when section ID not found
        assert "List Contacts" in result.text
        assert "Create Contact" in result.text
