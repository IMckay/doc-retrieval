"""Format content for optimal LLM consumption."""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel

from doc_retrieval.converter.markdown import html_to_markdown
from doc_retrieval.extractor.api_schema import extract_api_schema, is_api_doc_page
from doc_retrieval.extractor.main_content import ExtractedContent


class FormattedPage(BaseModel):
    """A page formatted for output."""

    url: str
    title: Optional[str] = None
    markdown: str


class SiteInfo(BaseModel):
    """Information about the documentation site."""

    base_url: str
    title: Optional[str] = None
    total_pages: int = 0
    extracted_at: datetime = datetime.now()


class LLMFormatter:
    """Format content for optimal LLM consumption."""

    def __init__(self, include_metadata: bool = True, include_toc: bool = True):
        self.include_metadata = include_metadata
        self.include_toc = include_toc

    def format_page(
        self,
        content: ExtractedContent,
        url: str,
    ) -> FormattedPage:
        """Format a single page with metadata."""
        markdown = None

        # For API doc pages, try structured schema extraction first
        if is_api_doc_page(url, content.html):
            markdown = extract_api_schema(content.html)

        # Fall back to generic HTML-to-Markdown conversion
        if not markdown:
            markdown = html_to_markdown(content.html)

        # Clean up the markdown
        markdown = self._clean_markdown(markdown)

        return FormattedPage(
            url=url,
            title=content.title,
            markdown=markdown,
        )

    def format_single_page_output(self, page: FormattedPage) -> str:
        """Format a single page for standalone output."""
        parts = []

        if self.include_metadata:
            parts.append("---")
            parts.append(f"source: {page.url}")
            if page.title:
                parts.append(f"title: {page.title}")
            parts.append("---")
            parts.append("")

        # Only add title header if markdown doesn't already start with one
        if page.title:
            first_line = page.markdown.lstrip().split("\n", 1)[0]
            # Skip if markdown already starts with any H1 heading
            if not first_line.startswith("# "):
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
            # Page header comment for navigation
            parts.append(f"<!-- Page: {page.url} -->")

            # Page title
            if page.title:
                parts.append(f"# {page.title}")
                parts.append("")

            # Page content
            parts.append(page.markdown)
            parts.append("")
            parts.append("---")
            parts.append("")

        return "\n".join(parts)

    def _clean_markdown(self, markdown: str) -> str:
        """Clean up markdown content."""
        # Remove zero-width spaces, joiners, and BOM
        markdown = re.sub(r"[\u200B\u200C\u200D\uFEFF]", "", markdown)

        # Remove documentation emoji icons (Docusaurus page icons, etc.)
        markdown = re.sub(
            r"[\U0001F4C4\U0001F4C1\U0001F4C2\U0001F517\U0001F4DD\U0001F527\U0001F4A1\U0001F4CC]\uFE0F?",
            "",
            markdown,
        )

        # Remove empty/broken markdown links like [](url) or links with only whitespace
        markdown = re.sub(r"\[\s*\]\([^)]+\)", "", markdown)

        # Collapse multiple spaces (but not at start of line for indentation)
        markdown = re.sub(r"([^\n]) {2,}", r"\1 ", markdown)

        # Collapse excessive newlines
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)

        # Fix orphaned heading markers
        markdown = re.sub(r"(^|\n)(#{1,6})\s*\n+", r"\1\2 ", markdown)

        return markdown.strip()

    def _make_anchor(self, title: str) -> str:
        """Create a markdown anchor from a title."""
        anchor = title.lower()
        # Remove special characters
        anchor = re.sub(r"[^\w\s-]", "", anchor)
        # Replace spaces with hyphens
        anchor = re.sub(r"\s+", "-", anchor)
        return anchor

    def _extract_site_name(self, url: str) -> str:
        """Extract a site name from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc

        # Remove common prefixes
        for prefix in ["www.", "docs.", "documentation.", "help.", "support."]:
            if domain.startswith(prefix):
                domain = domain[len(prefix):]

        # Get the main domain part
        parts = domain.split(".")
        if len(parts) >= 2:
            return parts[0].title() + " Documentation"

        return domain.title() + " Documentation"
