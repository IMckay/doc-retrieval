"""Single file output writer."""

from pathlib import Path

import aiofiles

from doc_retrieval.converter.llm_formatter import FormattedPage, LLMFormatter, SiteInfo


class SingleFileOutput:
    """Write all pages to a single Markdown file."""

    def __init__(
        self,
        output_path: Path,
        include_metadata: bool = True,
        include_toc: bool = True,
    ):
        self.output_path = Path(output_path)
        self.formatter = LLMFormatter(
            include_metadata=include_metadata,
            include_toc=include_toc,
        )

    async def write(self, pages: list[FormattedPage], site_info: SiteInfo) -> Path:
        """Write all pages to a single file."""
        # Ensure parent directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure .md extension
        if self.output_path.suffix != ".md":
            self.output_path = self.output_path.with_suffix(".md")

        # Format combined content
        content = self.formatter.format_combined_output(pages, site_info)

        # Write to file
        async with aiofiles.open(self.output_path, "w", encoding="utf-8") as f:
            await f.write(content)

        return self.output_path
