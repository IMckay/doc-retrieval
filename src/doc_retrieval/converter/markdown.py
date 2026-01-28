"""HTML to Markdown conversion."""

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter as BaseMarkdownConverter, ATX


class MarkdownConverter(BaseMarkdownConverter):
    """Custom Markdown converter optimized for documentation."""

    def __init__(self, **kwargs):
        super().__init__(
            heading_style=ATX,
            bullets="-",
            strong_em_symbol="*",
            **kwargs,
        )

    def convert_pre(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Handle code blocks with language detection."""
        code = el.find("code")
        if code:
            lang = self._extract_language(code)
            code_text = code.get_text()
            # Ensure proper newlines
            if not code_text.startswith("\n"):
                code_text = "\n" + code_text
            if not code_text.endswith("\n"):
                code_text = code_text + "\n"
            return f"\n```{lang}{code_text}```\n\n"
        return super().convert_pre(el, text, parent_tags=parent_tags, **kwargs)

    def convert_code(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Handle inline code."""
        # Check if this is inside a pre tag (already handled)
        if el.parent and el.parent.name == "pre":
            return text
        code_text = el.get_text()
        if "`" in code_text:
            return f"`` {code_text} ``"
        return f"`{code_text}`"

    def _extract_language(self, code_elem: Tag) -> str:
        """Extract programming language from class names."""
        classes = code_elem.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()

        for cls in classes:
            if cls.startswith("language-"):
                return cls[9:]
            if cls.startswith("lang-"):
                return cls[5:]
            if cls.startswith("highlight-"):
                return cls[10:]
            # Common short forms
            if cls in ["python", "py", "javascript", "js", "typescript", "ts",
                       "ruby", "go", "rust", "java", "cpp", "c", "bash", "shell",
                       "json", "yaml", "xml", "html", "css", "sql", "graphql"]:
                return cls

        return ""

    def convert_table(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Convert HTML tables to Markdown tables."""
        rows = []
        header_row = None

        # Find header row
        thead = el.find("thead")
        if thead:
            header_row = thead.find("tr")
        else:
            # First row might be header
            first_row = el.find("tr")
            if first_row and first_row.find("th"):
                header_row = first_row

        # Process header
        if header_row:
            headers = [self._cell_text(cell) for cell in header_row.find_all(["th", "td"])]
            if headers:
                rows.append("| " + " | ".join(headers) + " |")
                rows.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Process body rows
        tbody = el.find("tbody")
        body_rows = tbody.find_all("tr") if tbody else el.find_all("tr")

        for tr in body_rows:
            if tr == header_row:
                continue
            cells = [self._cell_text(cell) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append("| " + " | ".join(cells) + " |")

        if rows:
            return "\n\n" + "\n".join(rows) + "\n\n"
        return ""

    def _cell_text(self, cell: Tag) -> str:
        """Get clean text from a table cell."""
        text = cell.get_text(strip=True)
        # Replace newlines and pipes
        text = text.replace("\n", " ").replace("|", "\\|")
        return text

    def convert_img(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Convert images to Markdown."""
        src = el.get("src", "")
        alt = el.get("alt", "")
        title = el.get("title", "")

        if not src:
            return ""

        if title:
            return f'![{alt}]({src} "{title}")'
        return f"![{alt}]({src})"


def html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown."""
    if not html:
        return ""

    # Parse and clean HTML first
    soup = BeautifulSoup(html, "lxml")

    # Remove script and style tags
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Convert
    converter = MarkdownConverter()
    markdown = converter.convert_soup(soup)

    # Clean up excessive whitespace
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = markdown.strip()

    return markdown
