"""HTML to Markdown conversion."""

import re

from bs4 import BeautifulSoup, Tag
from markdownify import ATX
from markdownify import MarkdownConverter as BaseMarkdownConverter


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
        # Special case: OpenAPI method endpoint block wraps a heading
        # inside <pre>, which would otherwise render as a code block.
        raw_classes: str | list[str] = el.get("class") or []
        classes: list[str] = (
            raw_classes.split() if isinstance(raw_classes, str) else list(raw_classes)
        )
        if any("openapi" in c and "method-endpoint" in c for c in classes):
            badge = el.select_one(".badge")
            endpoint = el.select_one(
                ".openapi__method-endpoint-path, h2, h3"
            )
            if badge and endpoint:
                method = badge.get_text(strip=True).upper()
                path = endpoint.get_text(strip=True)
                return f"\n**{method}** `{path}`\n\n"

        code = el.find("code")
        if code:
            lang = self._extract_language(code)
            code_text = code.get_text()
            if not code_text.startswith("\n"):
                code_text = "\n" + code_text
            if not code_text.endswith("\n"):
                code_text = code_text + "\n"
            return f"\n```{lang}{code_text}```\n\n"
        return super().convert_pre(el, text, parent_tags=parent_tags, **kwargs)  # type: ignore[misc,no-any-return]

    def convert_code(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Handle inline code."""
        # Check if this is inside a pre tag (already handled)
        if el.parent and el.parent.name == "pre":
            return text
        code_text = el.get_text()
        if "`" in code_text:
            return f"`` {code_text} ``"
        return f"`{code_text}`"

    def convert_a(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Handle links, flattening headings inside links to inline format."""
        href = el.get("href", "")
        # If the link wraps a heading element, flatten it
        heading = el.find(re.compile(r"^h[1-6]$"))
        if heading:
            title_text = heading.get_text(strip=True)
            # Collect any remaining text (description) outside the heading
            desc_parts = []
            for child in el.children:
                if child == heading:
                    continue
                if hasattr(child, "get_text"):
                    t = child.get_text(strip=True)
                    if t:
                        desc_parts.append(t)
                elif isinstance(child, str) and child.strip():
                    desc_parts.append(child.strip())
            desc = " ".join(desc_parts)
            if desc:
                return f"\n- **[{title_text}]({href})** - {desc}\n"
            return f"\n- **[{title_text}]({href})**\n"
        return super().convert_a(el, text, parent_tags=parent_tags, **kwargs)  # type: ignore[misc,no-any-return]

    def _extract_language(self, code_elem: Tag) -> str:
        """Extract programming language from class names."""
        raw_classes: str | list[str] = code_elem.get("class") or []
        classes: list[str] = (
            raw_classes.split() if isinstance(raw_classes, str) else list(raw_classes)
        )

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

        thead = el.find("thead")
        if thead:
            header_row = thead.find("tr")
        else:
            # First row might be header
            first_row = el.find("tr")
            if first_row and first_row.find("th"):
                header_row = first_row

        if header_row:
            headers = [self._cell_text(cell) for cell in header_row.find_all(["th", "td"])]
            if headers:
                rows.append("| " + " | ".join(headers) + " |")
                rows.append("| " + " | ".join(["---"] * len(headers)) + " |")

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
        """Get clean text from a table cell, preserving list structure."""
        list_elem = cell.find(["ul", "ol"])
        if list_elem:
            items = list_elem.find_all("li")
            if items:
                item_texts = [
                    li.get_text(strip=True).replace("|", "\\|") for li in items
                ]
                return "<br>".join(f"- {t}" for t in item_texts if t)

        text = cell.get_text(separator=" ", strip=True)
        text = text.replace("\n", " ").replace("|", "\\|")
        return text

    def convert_img(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Convert images to Markdown."""
        src = el.get("src", "") or ""
        alt = el.get("alt", "") or ""
        title = el.get("title", "") or ""

        if isinstance(src, list):
            src = src[0] if src else ""
        if isinstance(alt, list):
            alt = " ".join(alt)
        if isinstance(title, list):
            title = " ".join(title)

        if not src:
            return ""

        # Truncate excessively long alt text (e.g. decorative image descriptions)
        if len(alt) > 100:
            alt = alt[:97] + "..."

        if title:
            return f'![{alt}]({src} "{title}")'
        return f"![{alt}]({src})"

    def convert_svg(self, el: Tag, text: str, parent_tags=None, **kwargs) -> str:
        """Suppress inline SVG icons — they produce meaningless text output."""
        return ""


def html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown."""
    if not html:
        return ""

    # Parse and clean HTML first
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    converter = MarkdownConverter()
    markdown = converter.convert_soup(soup)

    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = markdown.strip()

    return markdown
