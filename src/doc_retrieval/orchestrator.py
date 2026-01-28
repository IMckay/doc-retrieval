"""Main orchestrator that coordinates the extraction pipeline."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from doc_retrieval.config import (
    AppConfig,
    DiscoveryMode,
    OutputMode,
)
from doc_retrieval.converter.llm_formatter import FormattedPage, LLMFormatter, SiteInfo
from doc_retrieval.discovery import (
    BaseDiscoverer,
    CrawlerDiscoverer,
    DiscoveredURL,
    ManualDiscoverer,
    SitemapDiscoverer,
)
from doc_retrieval.extractor import ContentExtractor, ExtractedContent
from doc_retrieval.fetcher import BaseFetcher, HttpFetcher, PlaywrightFetcher
from doc_retrieval.output.multi_file import MultiFileOutput
from doc_retrieval.output.single_file import SingleFileOutput
from doc_retrieval.patterns import PatternRegistry, SitePattern
from doc_retrieval.utils.rate_limiter import RateLimiter


class ExtractionResult:
    """Result of the extraction process."""

    def __init__(self):
        self.pages: list[FormattedPage] = []
        self.errors: list[tuple[str, str]] = []  # (url, error message)
        self.skipped: list[str] = []

    @property
    def success_count(self) -> int:
        return len(self.pages)

    @property
    def error_count(self) -> int:
        return len(self.errors)


class Orchestrator:
    """Coordinates the documentation extraction pipeline."""

    def __init__(self, config: AppConfig, console: Optional[Console] = None):
        self.config = config
        self.console = console or Console()
        self.rate_limiter = RateLimiter(config.rate_limit.delay_seconds)

    async def run(self) -> ExtractionResult:
        """Execute the full extraction pipeline."""
        result = ExtractionResult()

        # Get site pattern if specified
        pattern = self._get_pattern()

        # Apply pattern overrides to config
        if pattern:
            self._apply_pattern(pattern)

        # Create components
        discoverer = self._create_discoverer()
        fetcher = self._create_fetcher()
        extractor = ContentExtractor(self.config.extractor)
        formatter = LLMFormatter(
            include_metadata=self.config.output.include_metadata,
            include_toc=self.config.output.include_toc,
        )

        # Discover URLs first (to get count for progress bar)
        self.console.print(f"[blue]Discovering pages from {self.config.base_url}...[/blue]")

        urls = []
        async for discovered in discoverer.discover():
            urls.append(discovered)
            if self.config.verbose:
                self.console.print(f"  Found: {discovered.url}")

        if not urls:
            self.console.print("[yellow]No pages found to extract.[/yellow]")
            return result

        self.console.print(f"[green]Found {len(urls)} pages to extract.[/green]")

        # Fetch and extract
        async with fetcher:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=self.console,
            ) as progress:
                task = progress.add_task("Extracting...", total=len(urls))

                for discovered in urls:
                    url = discovered.url

                    try:
                        # Rate limit
                        await self.rate_limiter.acquire()

                        # Fetch
                        fetch_result = await fetcher.fetch(url)

                        if not fetch_result.success:
                            result.errors.append((url, fetch_result.error or "Fetch failed"))
                            progress.update(task, advance=1)
                            continue

                        # Extract
                        content = extractor.extract(fetch_result.html, url)

                        if not content:
                            result.skipped.append(url)
                            progress.update(task, advance=1)
                            continue

                        # Format
                        page = formatter.format_page(content, url)
                        result.pages.append(page)

                    except Exception as e:
                        result.errors.append((url, str(e)))

                    progress.update(task, advance=1)

        # Write output
        if result.pages:
            site_info = SiteInfo(
                base_url=self.config.base_url,
                total_pages=len(result.pages),
                extracted_at=datetime.now(),
            )

            output_path = await self._write_output(result.pages, site_info)
            self.console.print(f"[green]Output written to: {output_path}[/green]")

        # Summary
        self.console.print()
        self.console.print(f"[bold]Extraction complete:[/bold]")
        self.console.print(f"  Extracted: {result.success_count} pages")
        if result.error_count > 0:
            self.console.print(f"  Errors: {result.error_count}")
        if result.skipped:
            self.console.print(f"  Skipped (no content): {len(result.skipped)}")

        return result

    def _get_pattern(self) -> Optional[SitePattern]:
        """Get the site pattern if specified."""
        if self.config.pattern:
            pattern = PatternRegistry.get(self.config.pattern)
            if pattern:
                return pattern
            else:
                self.console.print(
                    f"[yellow]Warning: Unknown pattern '{self.config.pattern}', using defaults.[/yellow]"
                )
        return None

    def _apply_pattern(self, pattern: SitePattern) -> None:
        """Apply pattern settings to config."""
        if pattern.content_selectors:
            self.config.extractor.content_selectors = (
                pattern.content_selectors + self.config.extractor.content_selectors
            )
        if pattern.remove_selectors:
            self.config.extractor.remove_selectors = (
                pattern.remove_selectors + self.config.extractor.remove_selectors
            )
        # Don't override JS setting if explicitly set to False
        if pattern.requires_js and self.config.fetcher.use_js:
            self.config.fetcher.use_js = True

    def _create_discoverer(self) -> BaseDiscoverer:
        """Create the appropriate discoverer."""
        mode = self.config.discovery.mode

        if mode == DiscoveryMode.SITEMAP:
            return SitemapDiscoverer(self.config.base_url, self.config.discovery)
        elif mode == DiscoveryMode.CRAWL:
            return CrawlerDiscoverer(self.config.base_url, self.config.discovery)
        elif mode == DiscoveryMode.MANUAL:
            return ManualDiscoverer(self.config.base_url, self.config.discovery)
        else:
            raise ValueError(f"Unknown discovery mode: {mode}")

    def _create_fetcher(self) -> BaseFetcher:
        """Create the appropriate fetcher."""
        if self.config.fetcher.use_js:
            return PlaywrightFetcher(self.config.fetcher)
        else:
            return HttpFetcher(self.config.fetcher)

    async def _write_output(
        self, pages: list[FormattedPage], site_info: SiteInfo
    ) -> Path:
        """Write the output files."""
        if self.config.output.mode == OutputMode.SINGLE:
            writer = SingleFileOutput(
                self.config.output.path,
                include_metadata=self.config.output.include_metadata,
                include_toc=self.config.output.include_toc,
            )
        else:
            writer = MultiFileOutput(
                self.config.output.path,
                include_metadata=self.config.output.include_metadata,
            )

        return await writer.write(pages, site_info)
