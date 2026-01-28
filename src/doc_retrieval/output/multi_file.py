"""Multi-file output writer."""

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiofiles

from doc_retrieval.converter.llm_formatter import FormattedPage, LLMFormatter, SiteInfo


class MultiFileOutput:
    """Write each page to a separate Markdown file."""

    def __init__(
        self,
        output_dir: Path,
        include_metadata: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.formatter = LLMFormatter(include_metadata=include_metadata, include_toc=False)

    async def write(self, pages: list[FormattedPage], site_info: SiteInfo) -> Path:
        """Write each page to a separate file and create an index."""
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        written_files = []

        for page in pages:
            filepath = self._get_filepath(page.url, site_info.base_url)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            content = self.formatter.format_single_page_output(page)

            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(content)

            written_files.append((page, filepath))

        # Write index file
        await self._write_index(written_files, site_info)

        return self.output_dir

    def _get_filepath(self, url: str, base_url: str) -> Path:
        """Convert a URL to a file path."""
        parsed = urlparse(url)
        base_parsed = urlparse(base_url)

        # Get path relative to base
        path = parsed.path.strip("/")

        if not path:
            path = "index"

        # Remove file extensions that might be in the URL
        for ext in [".html", ".htm", ".php", ".asp", ".aspx"]:
            if path.endswith(ext):
                path = path[:-len(ext)]

        # Replace problematic characters
        path = path.replace(":", "_").replace("?", "_").replace("*", "_")
        path = path.replace("<", "_").replace(">", "_").replace("|", "_")
        path = path.replace('"', "_")

        # Ensure .md extension
        if not path.endswith(".md"):
            path = path + ".md"

        return self.output_dir / path

    async def _write_index(
        self,
        written_files: list[tuple[FormattedPage, Path]],
        site_info: SiteInfo,
    ) -> None:
        """Write an index file listing all pages."""
        index_path = self.output_dir / "index.md"

        parts = []
        parts.append(f"# {site_info.title or 'Documentation'}")
        parts.append("")
        parts.append(f"> Extracted from {site_info.base_url}")
        parts.append(f"> Extracted on: {site_info.extracted_at.isoformat()}")
        parts.append(f"> Total pages: {len(written_files)}")
        parts.append("")
        parts.append("## Pages")
        parts.append("")

        for page, filepath in written_files:
            relative_path = filepath.relative_to(self.output_dir)
            title = page.title or str(relative_path)
            parts.append(f"- [{title}]({relative_path})")

        parts.append("")

        async with aiofiles.open(index_path, "w", encoding="utf-8") as f:
            await f.write("\n".join(parts))
