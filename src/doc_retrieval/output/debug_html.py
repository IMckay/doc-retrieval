"""Debug HTML output — saves raw fetched HTML alongside extraction results."""

import json
from pathlib import Path

import aiofiles  # type: ignore[import-untyped]

from doc_retrieval.utils.url_utils import url_to_filename


class DebugHtmlWriter:
    """Save raw HTML and extraction metadata for debugging."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir / "_debug_html"

    async def save(
        self,
        url: str,
        base_url: str,
        html: str,
        extraction_method: str | None = None,
        content_length: int = 0,
    ) -> None:
        """Save raw HTML and a sidecar JSON metadata file for one page."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        filename = url_to_filename(url, base_url)
        # Replace .md with .html
        if filename.endswith(".md"):
            filename = filename[:-3]

        html_path = self.output_dir / (filename + ".html")
        meta_path = self.output_dir / (filename + ".meta.json")

        html_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(html_path, "w", encoding="utf-8") as f:
            await f.write(html)

        metadata = {
            "url": url,
            "extraction_method": extraction_method,
            "html_length": len(html),
            "extracted_content_length": content_length,
        }
        async with aiofiles.open(meta_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(metadata, indent=2, ensure_ascii=False))
