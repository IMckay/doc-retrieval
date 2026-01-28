"""Format content for optimal LLM consumption."""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel

from doc_retrieval.converter.markdown import html_to_markdown
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
        # Convert HTML to Markdown
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

        if page.title:
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
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)

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
