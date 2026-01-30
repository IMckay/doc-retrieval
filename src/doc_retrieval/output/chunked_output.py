"""Chunked JSONL output writer for LLM context windows."""

import json
import re
from pathlib import Path

import aiofiles  # type: ignore[import-untyped]

from doc_retrieval.converter.llm_formatter import FormattedPage, SiteInfo

# Rough approximation: 1 token ≈ 4 characters for English text.
CHARS_PER_TOKEN = 4


class ChunkedOutput:
    """Split pages into token-limited chunks and write as JSONL."""

    def __init__(
        self,
        output_path: Path,
        max_tokens: int = 4000,
        overlap_tokens: int = 200,
    ):
        self.output_path = Path(output_path)
        self.max_chars = max_tokens * CHARS_PER_TOKEN
        self.overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    async def write(self, pages: list[FormattedPage], site_info: SiteInfo) -> Path:
        """Chunk all pages and write as JSONL."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.output_path.suffix not in (".jsonl", ".ndjson"):
            self.output_path = self.output_path.with_suffix(".jsonl")

        async with aiofiles.open(self.output_path, "w", encoding="utf-8") as f:
            for page in pages:
                chunks = self._chunk_page(page)
                total = len(chunks)
                for i, chunk_text in enumerate(chunks):
                    record = {
                        "url": page.url,
                        "title": page.title,
                        "chunk_index": i,
                        "total_chunks": total,
                        "content": chunk_text,
                    }
                    if page.api_version:
                        record["api_version"] = page.api_version
                    line = json.dumps(record, ensure_ascii=False)
                    await f.write(line + "\n")

        return self.output_path

    def _chunk_page(self, page: FormattedPage) -> list[str]:
        """Split a page's markdown into chunks respecting heading boundaries."""
        text = page.markdown
        if len(text) <= self.max_chars:
            return [text]

        sections = self._split_by_headings(text)
        return self._merge_sections_into_chunks(sections)

    def _split_by_headings(self, text: str) -> list[str]:
        """Split markdown at heading boundaries."""
        # Split at lines starting with # (any level)
        parts: list[str] = []
        current: list[str] = []

        for line in text.split("\n"):
            if re.match(r"^#{1,6}\s", line) and current:
                parts.append("\n".join(current))
                current = [line]
            else:
                current.append(line)

        if current:
            parts.append("\n".join(current))

        return parts

    def _merge_sections_into_chunks(self, sections: list[str]) -> list[str]:
        """Merge small sections and split large ones to fit max_chars."""
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_len = 0

        for section in sections:
            section_len = len(section)

            # If a single section exceeds max_chars, split it by paragraphs
            if section_len > self.max_chars:
                # Flush current chunk first
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_len = 0

                chunks.extend(self._split_large_section(section))
                continue

            # Would adding this section exceed the limit?
            separator_len = 2 if current_chunk else 0  # "\n\n" between sections
            if current_len + separator_len + section_len > self.max_chars and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                # Add overlap: take trailing text from previous chunk
                if self.overlap_chars > 0:
                    prev_text = chunks[-1]
                    overlap = prev_text[-self.overlap_chars:]
                    current_chunk = [overlap, section]
                    current_len = len(overlap) + 2 + section_len
                else:
                    current_chunk = [section]
                    current_len = section_len
            else:
                current_chunk.append(section)
                current_len += separator_len + section_len

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks if chunks else ["\n\n".join(sections)]

    def _split_large_section(self, section: str) -> list[str]:
        """Split an oversized section by paragraphs."""
        paragraphs = re.split(r"\n\n+", section)
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para)
            separator_len = 2 if current else 0

            if current_len + separator_len + para_len > self.max_chars and current:
                chunks.append("\n\n".join(current))
                if self.overlap_chars > 0:
                    prev_text = chunks[-1]
                    overlap = prev_text[-self.overlap_chars:]
                    current = [overlap, para]
                    current_len = len(overlap) + 2 + para_len
                else:
                    current = [para]
                    current_len = para_len
            else:
                current.append(para)
                current_len += separator_len + para_len

        if current:
            chunks.append("\n\n".join(current))

        # If a single paragraph still exceeds max_chars, hard-split it
        result: list[str] = []
        for chunk in chunks:
            if len(chunk) > self.max_chars:
                for i in range(0, len(chunk), self.max_chars - self.overlap_chars):
                    result.append(chunk[i : i + self.max_chars])
            else:
                result.append(chunk)

        return result
