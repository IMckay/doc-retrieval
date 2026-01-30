"""Format content for optimal LLM consumption."""

import re
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from doc_retrieval.converter.markdown import html_to_markdown
from doc_retrieval.extractor.api_schema import extract_api_schema, is_api_doc_page
from doc_retrieval.extractor.main_content import ExtractedContent


class FormattedPage(BaseModel):
    """A page formatted for output."""

    url: str
    title: str | None = None
    markdown: str
    api_version: str | None = None


class SiteInfo(BaseModel):
    """Information about the documentation site."""

    base_url: str
    title: str | None = None
    total_pages: int = 0
    extracted_at: datetime = Field(default_factory=datetime.now)


class LLMFormatter:
    """Format content for optimal LLM consumption."""

    def __init__(self, include_metadata: bool = True, include_toc: bool = True):
        self.include_metadata = include_metadata
        self.include_toc = include_toc

    def format_page(
        self,
        content: ExtractedContent,
        url: str,
        raw_html: str | None = None,
    ) -> FormattedPage:
        """Format a single page with metadata.

        Args:
            content: Extracted content (post-cleaned HTML).
            url: Page URL.
            raw_html: Original fetched HTML before content extraction/cleaning.
                      Used for API schema detection which needs uncleaned DOM.
        """
        markdown = None
        api_title: str | None = None

        # For API doc pages, try structured schema extraction first.
        # Use raw_html (pre-cleaning) so _clean_content() empty-element
        # removal doesn't strip schema containers before detection.
        api_html = raw_html or content.html
        if is_api_doc_page(url, api_html):
            schema_result = extract_api_schema(api_html)
            if schema_result:
                markdown = schema_result.markdown
                api_title = schema_result.title

        # Fall back to generic HTML-to-Markdown conversion
        if not markdown:
            markdown = html_to_markdown(content.html)

        # Clean up the markdown
        markdown = self._clean_markdown(markdown)

        # Prefer the API schema title (from .openapi__heading) over the
        # generic <title> tag which often falls back to the site name.
        title = api_title or (self._clean_title(content.title) if content.title else None)

        api_version = self._detect_api_version(url, markdown)

        return FormattedPage(
            url=url,
            title=title,
            markdown=markdown,
            api_version=api_version,
        )

    def format_single_page_output(self, page: FormattedPage) -> str:
        """Format a single page for standalone output."""
        parts = []

        if self.include_metadata:
            parts.append("---")
            parts.append(f"source: {page.url}")
            if page.title:
                parts.append(f"title: {page.title}")
            if page.api_version:
                parts.append(f"api_version: {page.api_version}")
            parts.append("---")
            parts.append("")

        # Only add title header if markdown doesn't already contain a matching H1
        if page.title:
            has_h1 = any(
                line.strip().removeprefix("# ").strip() == page.title
                for line in page.markdown.split("\n")
                if line.strip().startswith("# ") and not line.strip().startswith("## ")
            )
            if not has_h1:
                parts.append(f"# {page.title}")
                parts.append("")

        parts.append(page.markdown)

        return "\n".join(parts)

    def format_combined_output(
        self,
        pages: list[FormattedPage],
        site_info: SiteInfo,
    ) -> str:
        """Combine multiple pages into a single document."""
        parts = []

        # Document header
        site_title = site_info.title or self._extract_site_name(site_info.base_url)
        parts.append(f"# {site_title}")
        parts.append("")

        if self.include_metadata:
            parts.append(f"> Documentation extracted from {site_info.base_url}")
            parts.append(f"> Extracted on: {site_info.extracted_at.isoformat()}")
            parts.append(f"> Total pages: {len(pages)}")
            parts.append("")

        # Table of contents
        if self.include_toc and len(pages) > 1:
            parts.append("## Table of Contents")
            parts.append("")
            for i, page in enumerate(pages, 1):
                title = page.title or f"Page {i}"
                anchor = self._make_anchor(title)
                parts.append(f"- [{title}](#{anchor})")
            parts.append("")

        parts.append("---")
        parts.append("")

        # Each page
        for page in pages:
            if page.api_version:
                parts.append(f"<!-- Page: {page.url} | api_version: {page.api_version} -->")
            else:
                parts.append(f"<!-- Page: {page.url} -->")

            # Page title — only add if markdown doesn't already start with this H1
            if page.title:
                md_first_line = page.markdown.lstrip().split("\n", 1)[0].strip()
                if md_first_line != f"# {page.title}":
                    parts.append(f"# {page.title}")
                    parts.append("")

            parts.append(page.markdown)
            parts.append("")
            parts.append("---")
            parts.append("")

        return "\n".join(parts)

    @staticmethod
    def _detect_api_version(url: str, markdown: str) -> str | None:
        """Detect API version from the URL path or markdown content."""
        # Check URL for version patterns like /api/v1/, /api/v2/, /api/1.0/
        url_match = re.search(r"/api/(v?\d+(?:\.\d+)?)/", url, re.IGNORECASE)
        if url_match:
            version = url_match.group(1)
            if not version.startswith("v"):
                version = f"v{version}"
            return version

        # Fall back to scanning content for versioned API paths
        content_match = re.search(
            r"(?:public_api|/api)/(v\d+)/", markdown, re.IGNORECASE
        )
        if content_match:
            return content_match.group(1)

        return None

    def _clean_markdown(self, markdown: str) -> str:
        """Clean up markdown content."""
        # Remove zero-width spaces, joiners, and BOM
        markdown = re.sub(r"[\u200B\u200C\u200D\uFEFF]", "", markdown)

        # Remove documentation emoji icons (Docusaurus page icons, folder emoji, etc.)
        markdown = re.sub(
            r"[\U0001F300-\U0001F9FF]\uFE0F?",
            "",
            markdown,
        )

        # Remove empty/broken markdown links like [](url) or links with only whitespace
        markdown = re.sub(r"\[\s*\]\([^)]+\)", "", markdown)

        # Clean leading whitespace inside link text (e.g. from removed emoji)
        markdown = re.sub(r"\[\s+", "[", markdown)

        # Collapse multiple spaces (but not at start of line for indentation)
        markdown = re.sub(r"([^\n]) {2,}", r"\1 ", markdown)

        markdown = re.sub(r"\n{3,}", "\n\n", markdown)

        # Ensure space after closing link/image parenthesis before word characters
        markdown = re.sub(r"(\])\(([^)]*)\)(\w)", r"\1(\2) \3", markdown)

        # Fix orphaned heading markers
        markdown = re.sub(r"(^|\n)(#{1,6})\s*\n+", r"\1\2 ", markdown)

        markdown = self._deduplicate_h1(markdown)

        return markdown.strip()

    def _deduplicate_h1(self, markdown: str) -> str:
        """Remove duplicate H1 headings and body paragraphs matching the H1."""
        lines = markdown.split("\n")
        h1_text: str | None = None
        result: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = stripped[2:].strip()
                if h1_text is None:
                    h1_text = title
                    result.append(line)
                elif title == h1_text:
                    continue
                else:
                    result.append(line)
            elif h1_text and stripped == h1_text:
                # Body paragraph that exactly matches H1 text — skip
                continue
            else:
                result.append(line)

        return "\n".join(result)

    def _clean_title(self, title: str) -> str:
        """Strip common site name suffixes from page titles."""
        title = re.sub(r"\s*[|–—\-]\s*[^|–—\-]+$", "", title)
        return title.strip()

    def _make_anchor(self, title: str) -> str:
        """Create a markdown anchor from a title."""
        anchor = title.lower()
        anchor = re.sub(r"[^\w\s-]", "", anchor)
        anchor = re.sub(r"\s+", "-", anchor)
        return anchor

    def _extract_site_name(self, url: str) -> str:
        """Extract a site name from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc

        for prefix in ["www.", "docs.", "documentation.", "help.", "support."]:
            if domain.startswith(prefix):
                domain = domain[len(prefix):]

        # Get the main domain part
        parts = domain.split(".")
        if len(parts) >= 2:
            return parts[0].title() + " Documentation"

        return domain.title() + " Documentation"
