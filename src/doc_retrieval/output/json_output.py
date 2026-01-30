"""JSON and JSONL output writers."""

import json
from pathlib import Path

import aiofiles  # type: ignore[import-untyped]

from doc_retrieval.converter.llm_formatter import FormattedPage, SiteInfo


class JsonOutput:
    """Write all pages to a single JSON file."""

    def __init__(self, output_path: Path):
        self.output_path = Path(output_path)

    async def write(self, pages: list[FormattedPage], site_info: SiteInfo) -> Path:
        """Write all pages as a JSON array."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.output_path.suffix != ".json":
            self.output_path = self.output_path.with_suffix(".json")

        data = {
            "metadata": {
                "base_url": site_info.base_url,
                "title": site_info.title,
                "total_pages": site_info.total_pages,
                "extracted_at": site_info.extracted_at.isoformat(),
            },
            "pages": [_page_to_dict(page) for page in pages],
        }

        async with aiofiles.open(self.output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))

        return self.output_path


class JsonlOutput:
    """Write each page as a JSONL line."""

    def __init__(self, output_path: Path):
        self.output_path = Path(output_path)

    async def write(self, pages: list[FormattedPage], site_info: SiteInfo) -> Path:
        """Write each page as a single JSON line."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.output_path.suffix not in (".jsonl", ".ndjson"):
            self.output_path = self.output_path.with_suffix(".jsonl")

        async with aiofiles.open(self.output_path, "w", encoding="utf-8") as f:
            for page in pages:
                line = json.dumps(_page_to_dict(page), ensure_ascii=False)
                await f.write(line + "\n")

        return self.output_path


def _page_to_dict(page: FormattedPage) -> dict:
    """Convert a FormattedPage to a dict for JSON serialization."""
    d: dict = {
        "url": page.url,
        "title": page.title,
        "content": page.markdown,
    }
    if page.api_version:
        d["api_version"] = page.api_version
    return d
