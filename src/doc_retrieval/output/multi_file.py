"""Multi-file output writer."""

import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiofiles  # type: ignore[import-untyped]

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

        await self._rewrite_internal_links(written_files)
        await self._write_index(written_files, site_info)

        return self.output_dir

    def _get_filepath(self, url: str, base_url: str) -> Path:
        """Convert a URL to a file path."""
        parsed = urlparse(url)
        path = parsed.path.strip("/")

        if not path:
            path = "index"

        # Remove file extensions that might be in the URL
        for ext in [".html", ".htm", ".php", ".asp", ".aspx"]:
            if path.endswith(ext):
                path = path[:-len(ext)]

        path = path.replace(":", "_").replace("?", "_").replace("*", "_")
        path = path.replace("<", "_").replace(">", "_").replace("|", "_")
        path = path.replace('"', "_")

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
        title = site_info.title or self._site_name_from_url(site_info.base_url)
        parts.append(f"# {title}")
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

    async def _rewrite_internal_links(
        self, written_files: list[tuple[FormattedPage, Path]]
    ) -> None:
        """Rewrite markdown links that point to other extracted pages."""
        url_to_path: dict[str, Path] = {}
        for page, filepath in written_files:
            url_to_path[self._normalize_url_for_matching(page.url)] = filepath

        link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

        for page, filepath in written_files:
            async with aiofiles.open(filepath, encoding="utf-8") as f:
                content = await f.read()

            page_base_url = page.url
            modified = False

            def replace_link(match: re.Match[str]) -> str:
                nonlocal modified
                text = match.group(1)
                href = match.group(2)

                if href.startswith(("#", "mailto:", "tel:")):
                    return match.group(0)

                resolved = urljoin(page_base_url, href)
                resolved_no_frag = resolved.split("#")[0]
                fragment = ""
                if "#" in resolved:
                    fragment = "#" + resolved.split("#", 1)[1]

                normalized = self._normalize_url_for_matching(resolved_no_frag)

                page_domain = urlparse(page_base_url).netloc
                resolved_domain = urlparse(resolved_no_frag).netloc
                if resolved_domain and resolved_domain != page_domain:
                    return match.group(0)

                if normalized in url_to_path:
                    target_path = url_to_path[normalized]
                    rel = Path(os.path.relpath(target_path, filepath.parent))
                    modified = True
                    return f"[{text}]({rel}{fragment})"

                return match.group(0)

            new_content = link_pattern.sub(replace_link, content)

            if modified:
                async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                    await f.write(new_content)

    @staticmethod
    def _normalize_url_for_matching(url: str) -> str:
        """Normalize a URL for matching purposes (strip trailing slash, fragments, query)."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        for ext in (".html", ".htm", ".php", ".asp", ".aspx"):
            if path.endswith(ext):
                path = path[: -len(ext)]
        return f"{parsed.scheme}://{parsed.netloc}{path}".lower()

    @staticmethod
    def _site_name_from_url(url: str) -> str:
        """Derive a site name from the base URL."""
        parsed = urlparse(url)
        domain = parsed.netloc

        domain_prefixes = [
            "www.", "docs.", "developers.", "developer.",
            "documentation.", "help.", "support.",
        ]
        for prefix in domain_prefixes:
            if domain.startswith(prefix):
                domain = domain[len(prefix):]

        parts = domain.split(".")
        if len(parts) >= 2:
            return parts[0].title() + " Documentation"

        return domain.title() + " Documentation"
