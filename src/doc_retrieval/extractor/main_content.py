"""Main content extraction from HTML pages."""

import logging
import re

import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel
from readability import Document  # type: ignore[import-untyped]

from doc_retrieval.config import ExtractorConfig

logger = logging.getLogger(__name__)


class ExtractedContent(BaseModel):
    """Extracted content from a page."""

    html: str
    title: str | None = None
    description: str | None = None
    text: str | None = None  # Plain text version
    extraction_method: str | None = None


class ContentExtractor:
    """Extract main content from HTML pages."""

    def __init__(self, config: ExtractorConfig):
        self.config = config

    def extract(self, html: str, url: str) -> ExtractedContent | None:
        """Extract main content from HTML."""
        if not html or len(html.strip()) == 0:
            return None

        cleaned_html = self._pre_clean_html(html)

        # Try targeted soup extraction first when we have content selectors.
        # Soup preserves spacing and structure better than trafilatura for
        # sites where our CSS selectors match (e.g. Docusaurus, ReadTheDocs).
        content = self._extract_with_soup(cleaned_html, require_selector=True)
        if content and content.text and len(content.text) >= self.config.min_content_length:
            content = self._clean_content(content)
            content.extraction_method = "css_selector"
            return content

        # Fall back to trafilatura (best for articles/docs without known selectors)
        method = "trafilatura"
        content = self._extract_with_trafilatura(cleaned_html, url)

        if not content or (content.text and len(content.text) < self.config.min_content_length):
            method = "readability"
            content = self._extract_with_readability(cleaned_html)

        if not content or (content.text and len(content.text) < self.config.min_content_length):
            # Final fallback: soup with body-level extraction
            method = "beautifulsoup"
            content = self._extract_with_soup(cleaned_html)

        if content:
            content = self._clean_content(content)
            content.extraction_method = method
            return content

        logger.warning("All extraction methods failed for %s", url)
        return None

    def _pre_clean_html(self, html: str) -> str:
        """Remove navigation, sidebar, and footer elements before extraction.

        Applying remove_selectors upfront ensures all extraction methods
        (trafilatura, readability, BeautifulSoup) work with clean HTML
        free of navigation chrome.
        """
        soup = BeautifulSoup(html, "lxml")
        for selector in self.config.remove_selectors:
            for elem in soup.select(selector):
                elem.decompose()
        return str(soup)

    # Skip trafilatura for very large HTML documents — its heuristics and
    # deduplication are O(n²)-ish and can take 100+ seconds on big API ref pages.
    # Readability / BeautifulSoup handle large docs much faster.
    _TRAFILATURA_SIZE_LIMIT = 500_000  # characters (~500 KB)

    _TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
    _DESC_RE = re.compile(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
        re.IGNORECASE,
    )
    _DESC_RE_ALT = re.compile(
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
        re.IGNORECASE,
    )

    def _extract_with_trafilatura(self, html: str, url: str) -> ExtractedContent | None:
        """Extract using trafilatura.

        Uses a single trafilatura.extract() call (HTML output) and derives
        plain text + metadata cheaply, instead of the previous 3-call approach
        (extract HTML + extract_metadata + extract text).
        """
        if len(html) > self._TRAFILATURA_SIZE_LIMIT:
            logger.debug(
                "Skipping trafilatura for %s (HTML size %d > %d)",
                url, len(html), self._TRAFILATURA_SIZE_LIMIT,
            )
            return None

        try:
            html_result = trafilatura.extract(
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

            if html_result:
                # Derive text from the (smaller) extracted HTML — much cheaper
                # than re-running trafilatura with output_format="txt".
                soup = BeautifulSoup(html_result, "lxml")
                text = soup.get_text(separator=" ", strip=True)

                # Extract title/description from the <head> of the original HTML
                # using regex on the first 10 KB (these tags are always near the top).
                head = html[:10_000]
                m = self._TITLE_RE.search(head)
                title = m.group(1).strip() if m else None
                m = self._DESC_RE.search(head) or self._DESC_RE_ALT.search(head)
                description = m.group(1).strip() if m else None

                return ExtractedContent(
                    html=html_result,
                    title=title,
                    description=description,
                    text=text,
                )
        except Exception:
            logger.debug("Trafilatura extraction failed", exc_info=True)

        return None

    def _extract_with_readability(self, html: str) -> ExtractedContent | None:
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
            logger.debug("Readability extraction failed", exc_info=True)

        return None

    def _extract_with_soup(
        self, html: str, require_selector: bool = False
    ) -> ExtractedContent | None:
        """Custom extraction with BeautifulSoup.

        Args:
            html: The HTML to extract from.
            require_selector: If True, only return content when a configured
                content_selector matches. Do not fall back to <body>.
                This allows callers to try targeted extraction first and
                fall back to other methods when selectors don't match.
        """
        try:
            soup = BeautifulSoup(html, "lxml")

            title = None
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)

            # remove_selectors already applied in _pre_clean_html()

            main = None
            for selector in self.config.content_selectors:
                main = soup.select_one(selector)
                if main:
                    break

            # Docusaurus category/index page fallbacks
            if not main:
                for selector in [
                    'main[class*="docMainContainer"]',
                    ".docPage main",
                    "main .container",
                    "main .col",
                ]:
                    main = soup.select_one(selector)
                    if main:
                        break

            if not main:
                if require_selector:
                    return None
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
            logger.debug("BeautifulSoup extraction failed", exc_info=True)

        return None

    # Elements that should never be removed even if they appear empty
    # (their children or attributes carry semantic meaning).
    _PRESERVE_TAGS = frozenset({
        "details", "summary",
        "table", "thead", "tbody", "tfoot", "tr", "th", "td",
        "ul", "ol", "li", "dl", "dt", "dd",
        "pre", "code",
        "svg", "path",
    })

    def _clean_content(self, content: ExtractedContent) -> ExtractedContent:
        """Additional cleaning of extracted content."""
        if not content.html:
            return content

        soup = BeautifulSoup(content.html, "lxml")

        for selector in self.config.remove_selectors:
            for elem in soup.select(selector):
                elem.decompose()

        # Bottom-up empty element removal: process leaf nodes first so
        # parent containers are only removed if ALL children were empty,
        # preventing the cascade that strips schema/details containers.
        for elem in reversed(soup.find_all()):
            if elem.name in self._PRESERVE_TAGS:
                continue
            if elem.name in ("img", "br", "hr"):
                continue
            if not elem.get_text(strip=True):
                if not elem.find(["img", "video", "audio", "iframe"]):
                    elem.decompose()

        content.html = str(soup)
        content.text = soup.get_text(separator=" ", strip=True)

        # Post-clean content length check: reject near-empty pages
        if content.text and len(content.text) < self.config.min_content_length:
            return ExtractedContent(html="", title=content.title, text="")

        return content
