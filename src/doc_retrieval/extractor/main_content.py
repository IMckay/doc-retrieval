"""Main content extraction from HTML pages."""

from typing import Optional

import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel
from readability import Document

from doc_retrieval.config import ExtractorConfig
from doc_retrieval.extractor.api_schema import is_api_doc_page


class ExtractedContent(BaseModel):
    """Extracted content from a page."""

    html: str
    title: Optional[str] = None
    description: Optional[str] = None
    text: Optional[str] = None  # Plain text version


class ContentExtractor:
    """Extract main content from HTML pages."""

    def __init__(self, config: ExtractorConfig):
        self.config = config

    def extract(self, html: str, url: str) -> Optional[ExtractedContent]:
        """Extract main content from HTML."""
        if not html or len(html.strip()) == 0:
            return None

        # For API doc pages, use soup extraction to preserve schema structure
        # (trafilatura strips field names and type info from API schemas)
        if is_api_doc_page(url, html):
            content = self._extract_with_soup(html)
            if content and content.text and len(content.text) >= self.config.min_content_length:
                content = self._clean_content(content)
                return content

        # Try trafilatura first (best for articles/docs)
        content = self._extract_with_trafilatura(html, url)

        if not content or (content.text and len(content.text) < self.config.min_content_length):
            # Fallback to readability
            content = self._extract_with_readability(html)

        if not content or (content.text and len(content.text) < self.config.min_content_length):
            # Final fallback: custom extraction with BeautifulSoup
            content = self._extract_with_soup(html)

        if content:
            # Clean the extracted HTML
            content = self._clean_content(content)

        return content

    def _extract_with_trafilatura(self, html: str, url: str) -> Optional[ExtractedContent]:
        """Extract using trafilatura."""
        try:
            result = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=self.config.include_tables,
                include_images=self.config.include_images,
                include_links=self.config.include_links,
                output_format="html",
                favor_precision=False,
                deduplicate=True,
            )

            if result:
                metadata = trafilatura.extract_metadata(html, default_url=url)
                text = trafilatura.extract(
                    html,
                    url=url,
                    include_comments=False,
                    output_format="txt",
                )

                return ExtractedContent(
                    html=result,
                    title=metadata.title if metadata else None,
                    description=metadata.description if metadata else None,
                    text=text,
                )
        except Exception:
            pass

        return None

    def _extract_with_readability(self, html: str) -> Optional[ExtractedContent]:
        """Extract using readability-lxml."""
        try:
            doc = Document(html)
            content_html = doc.summary()
            title = doc.title()

            if content_html:
                # Get plain text
                soup = BeautifulSoup(content_html, "lxml")
                text = soup.get_text(separator=" ", strip=True)

                return ExtractedContent(
                    html=content_html,
                    title=title,
                    text=text,
                )
        except Exception:
            pass

        return None

    def _extract_with_soup(self, html: str) -> Optional[ExtractedContent]:
        """Custom extraction with BeautifulSoup."""
        try:
            soup = BeautifulSoup(html, "lxml")

            title = None
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)

            for selector in self.config.remove_selectors:
                for elem in soup.select(selector):
                    elem.decompose()

            main = None
            for selector in self.config.content_selectors:
                main = soup.select_one(selector)
                if main:
                    break

            if not main:
                main = soup.find("body")

            if not main:
                return None

            content_html = str(main)
            text = main.get_text(separator=" ", strip=True)

            return ExtractedContent(
                html=content_html,
                title=title,
                text=text,
            )
        except Exception:
            pass

        return None

    def _clean_content(self, content: ExtractedContent) -> ExtractedContent:
        """Additional cleaning of extracted content."""
        if not content.html:
            return content

        soup = BeautifulSoup(content.html, "lxml")

        for selector in self.config.remove_selectors:
            for elem in soup.select(selector):
                elem.decompose()

        for elem in soup.find_all():
            if not elem.get_text(strip=True) and elem.name not in ["img", "br", "hr"]:
                # Check if it has meaningful children
                if not elem.find(["img", "video", "audio", "iframe"]):
                    elem.decompose()

        content.html = str(soup)
        content.text = soup.get_text(separator=" ", strip=True)

        return content
