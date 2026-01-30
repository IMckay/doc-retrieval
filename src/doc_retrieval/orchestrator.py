"""Main orchestrator that coordinates the extraction pipeline."""

import asyncio
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from doc_retrieval.config import (
    AppConfig,
    DiscoveryMode,
    OutputMode,
)
from doc_retrieval.converter.llm_formatter import FormattedPage, LLMFormatter, SiteInfo
from doc_retrieval.discovery import (
    BaseDiscoverer,
    CrawlerDiscoverer,
    ManualDiscoverer,
    SitemapDiscoverer,
)
from doc_retrieval.extractor import ContentExtractor
from doc_retrieval.extractor.main_content import ExtractedContent
from doc_retrieval.fetcher import BaseFetcher, HttpFetcher, PlaywrightFetcher
from doc_retrieval.fetcher.base import FetchResult
from doc_retrieval.output.multi_file import MultiFileOutput
from doc_retrieval.output.single_file import SingleFileOutput
from doc_retrieval.patterns import PatternRegistry, SitePattern
from doc_retrieval.utils.rate_limiter import RateLimiter
from doc_retrieval.utils.url_utils import normalize_url

logger = logging.getLogger(__name__)


class PageStatus(str, Enum):
    """Status of a page in the pipeline."""

    QUEUED = "queued"
    FETCHING = "fetching"
    EXTRACTING = "extracting"
    CONVERTING = "converting"
    DONE = "done"
    SKIPPED = "skipped"
    ERROR = "error"


class ErrorCategory(str, Enum):
    """Category of an error for summary reporting."""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"
    CONNECTION = "connection"
    EXTRACTION = "extraction"
    UNKNOWN = "unknown"


_ERROR_SUGGESTIONS: dict[ErrorCategory, str] = {
    ErrorCategory.TIMEOUT: "Try --delay 2.0 or increase --timeout",
    ErrorCategory.RATE_LIMITED: "Try --delay 2.0 and reduce --max-concurrent",
    ErrorCategory.CLIENT_ERROR: "Check the URL is accessible in a browser",
    ErrorCategory.SERVER_ERROR: "The server may be overloaded — try again later",
    ErrorCategory.CONNECTION: "Check your network connection and the site URL",
    ErrorCategory.EXTRACTION: "Try a different --pattern or use --verbose to debug",
    ErrorCategory.UNKNOWN: "Rerun with --verbose for details",
}


@dataclass
class PageTiming:
    """Timing data for a single page through the pipeline."""

    url: str
    status: PageStatus = PageStatus.QUEUED
    fetch_start: float = 0.0
    fetch_end: float = 0.0
    extract_start: float = 0.0
    extract_end: float = 0.0
    convert_start: float = 0.0
    convert_end: float = 0.0
    error: str = ""
    retry_attempts: int = 1
    extraction_method: str = ""

    @property
    def fetch_duration(self) -> float:
        if self.fetch_start and self.fetch_end:
            return self.fetch_end - self.fetch_start
        return 0.0

    @property
    def extract_duration(self) -> float:
        if self.extract_start and self.extract_end:
            return self.extract_end - self.extract_start
        return 0.0

    @property
    def convert_duration(self) -> float:
        if self.convert_start and self.convert_end:
            return self.convert_end - self.convert_start
        return 0.0

    @property
    def total_duration(self) -> float:
        start = self.fetch_start
        end = self.convert_end or self.extract_end or self.fetch_end
        if start and end:
            return end - start
        return 0.0


class ExtractionResult:
    """Result of the extraction process."""

    def __init__(self):
        self.pages: list[FormattedPage] = []
        self.errors: list[tuple[str, str, ErrorCategory]] = []  # (url, msg, category)
        self.skipped: list[str] = []
        self.skipped_categories: list[str] = []
        self.page_timings: list[PageTiming] = []
        self.pipeline_start: float = 0.0
        self.pipeline_end: float = 0.0
        self.discovery_duration: float = 0.0
        self.output_duration: float = 0.0

    @property
    def success_count(self) -> int:
        return len(self.pages)

    @property
    def error_count(self) -> int:
        return len(self.errors)


class Orchestrator:
    """Coordinates the documentation extraction pipeline."""

    def __init__(self, config: AppConfig, console: Console | None = None):
        self.config = config
        self.console = console or Console()
        self.rate_limiter = RateLimiter(
            config.rate_limit.delay_seconds,
            config.rate_limit.max_concurrent,
        )

    async def run(self) -> ExtractionResult:
        """Execute the full extraction pipeline."""
        result = ExtractionResult()
        result.pipeline_start = time.monotonic()

        # Get explicit site pattern (auto-detection happens after first fetch)
        pattern = self._get_pattern()
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

        discovery_start = time.monotonic()
        urls = []
        async for discovered in discoverer.discover():
            urls.append(discovered)
            if self.config.verbose:
                self.console.print(f"  Found: {discovered.url}")

        if not urls:
            self.console.print("[yellow]No pages found to extract.[/yellow]")
            result.pipeline_end = time.monotonic()
            return result

        # Deduplicate URLs by normalized form (handles trailing-slash variants)
        original_count = len(urls)
        seen: set[str] = set()
        unique_urls: list = []
        for discovered in urls:
            norm = normalize_url(discovered.url)
            if norm not in seen:
                seen.add(norm)
                unique_urls.append(discovered)
        urls = unique_urls
        if self.config.verbose and len(urls) < original_count:
            self.console.print(
                f"[dim]Deduplicated: {original_count} → {len(urls)} unique URLs[/dim]"
            )

        if self.config.skip_urls and self.config.skip_urls.exists():
            with open(self.config.skip_urls) as f:
                skip_set = {
                    normalize_url(line.strip())
                    for line in f
                    if line.strip() and not line.startswith("#")
                }
            before_skip = len(urls)
            urls = [u for u in urls if normalize_url(u.url) not in skip_set]
            skipped_count = before_skip - len(urls)
            if skipped_count:
                self.console.print(
                    f"[dim]Skipped {skipped_count} URLs from skip file[/dim]"
                )

        result.discovery_duration = time.monotonic() - discovery_start
        disc_rate = len(urls) / result.discovery_duration if result.discovery_duration > 0 else 0
        self.console.print(
            f"[green]Found {len(urls)} pages to extract[/green]"
            f" [dim]({disc_rate:.1f} pages/sec)[/dim]"
        )

        for discovered in urls:
            result.page_timings.append(PageTiming(url=discovered.url))

        async with fetcher:
            # Auto-detect pattern from the first page if none specified
            probe_result: FetchResult | None = None
            if not pattern:
                first_url = urls[0].url
                try:
                    probe_result = await fetcher.fetch(first_url)
                    if probe_result.html:
                        detected = PatternRegistry.detect(
                            first_url, probe_result.html
                        )
                        if detected:
                            pattern = detected
                            self._apply_pattern(pattern)
                            if self.config.verbose:
                                self.console.print(
                                    f"[blue]Auto-detected pattern:"
                                    f" {pattern.name}[/blue]"
                                )
                except Exception:
                    logger.debug("Pattern auto-detection probe failed", exc_info=True)
                    probe_result = None

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TextColumn("•"),
                TimeRemainingColumn(),
                console=self.console,
            )
            progress_task = progress.add_task("Extracting...", total=len(urls))

            live = Live(
                self._build_live_display(progress, result),
                console=self.console,
                refresh_per_second=4,
            )

            with live:
                refresh_stop = asyncio.Event()

                async def refresh_display():
                    while not refresh_stop.is_set():
                        live.update(self._build_live_display(progress, result))
                        try:
                            await asyncio.wait_for(refresh_stop.wait(), timeout=0.25)
                        except asyncio.TimeoutError:
                            pass

                refresh_task = asyncio.create_task(refresh_display())

                tasks = [
                    self._process_page(
                        discovered, fetcher, extractor, formatter,
                        result, progress, progress_task, probe_result,
                        result.page_timings[i],
                    )
                    for i, discovered in enumerate(urls)
                ]
                await asyncio.gather(*tasks)

                refresh_stop.set()
                await refresh_task
                # Final update
                live.update(self._build_live_display(progress, result))

            # Sort pages by URL for deterministic output
            result.pages.sort(key=lambda p: p.url)

        # Write output
        if result.pages:
            site_info = SiteInfo(
                base_url=self.config.base_url,
                total_pages=len(result.pages),
                extracted_at=datetime.now(),
            )

            output_start = time.monotonic()
            output_path = await self._write_output(result.pages, site_info)
            result.output_duration = time.monotonic() - output_start

            if self.config.output.mode == OutputMode.SINGLE:
                size = output_path.stat().st_size
                self.console.print(
                    f"[green]Written to {output_path}"
                    f" ({_format_size(size)}, {len(result.pages)} pages)[/green]"
                )
            else:
                md_files = list(output_path.glob("*.md"))
                total_size = sum(f.stat().st_size for f in md_files)
                self.console.print(
                    f"[green]Written to {output_path}/"
                    f" ({len(md_files)} files, {_format_size(total_size)} total)[/green]"
                )

        result.pipeline_end = time.monotonic()

        self._print_summary(result)

        if result.errors:
            failed_path = self.config.output.path.parent / ".failed-urls.txt"
            with open(failed_path, "w") as f:
                f.write("# Failed URLs from doc-retrieval run\n")
                f.write(f"# {datetime.now().isoformat()}\n")
                for err_url, _msg, _cat in result.errors:
                    f.write(f"{err_url}\n")
            self.console.print(f"[yellow]Failed URLs: {failed_path}[/yellow]")
            self.console.print(
                f"[dim]Rerun with --skip-urls {failed_path} to skip these[/dim]"
            )

        return result

    def _build_live_display(self, progress: Progress, result: ExtractionResult) -> Group:
        """Build the live display with progress bar and status table."""
        now = time.monotonic()

        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Status", width=12)
        table.add_column("URL", min_width=40, overflow="ellipsis", no_wrap=True)
        table.add_column("Elapsed", width=8, justify="right")

        active_statuses = {PageStatus.FETCHING, PageStatus.EXTRACTING, PageStatus.CONVERTING}
        active = [
            t for t in result.page_timings if t.status in active_statuses
        ]
        done = [
            t for t in result.page_timings
            if t.status in {PageStatus.DONE, PageStatus.SKIPPED, PageStatus.ERROR}
        ]

        status_styles = {
            PageStatus.FETCHING: "cyan",
            PageStatus.EXTRACTING: "yellow",
            PageStatus.CONVERTING: "magenta",
            PageStatus.DONE: "green",
            PageStatus.SKIPPED: "dim",
            PageStatus.ERROR: "red",
        }

        for timing in active:
            start = timing.fetch_start or now
            elapsed = now - start
            style = status_styles.get(timing.status, "white")
            url_display = _truncate_url(timing.url, 60)
            table.add_row(
                Text(timing.status.value, style=style),
                url_display,
                f"{elapsed:.1f}s",
            )

        # Show last 3 completed pages
        for timing in done[-3:]:
            style = status_styles.get(timing.status, "white")
            url_display = _truncate_url(timing.url, 60)
            table.add_row(
                Text(timing.status.value, style=style),
                url_display,
                f"{timing.total_duration:.1f}s",
            )

        elements: list[Progress | Text | Table] = [progress]
        done_count = len(done)
        if done_count > 0 and result.pipeline_start:
            elapsed = now - result.pipeline_start
            if elapsed > 0:
                rate = done_count / elapsed
                elements.append(Text(f"  {rate:.1f} pages/sec", style="dim"))
        if self.rate_limiter.is_throttled:
            elements.append(
                Text(
                    f"  Throttled: delay {self.rate_limiter.delay_seconds:.1f}s"
                    f" (configured {self.rate_limiter._original_delay:.1f}s)"
                    f" — {self.rate_limiter.backoff_count} backoff(s)",
                    style="bold yellow",
                )
            )
        elements.append(table)
        return Group(*elements)

    def _print_summary(self, result: ExtractionResult) -> None:
        """Print a detailed post-run summary report."""
        self.console.print()
        total_time = result.pipeline_end - result.pipeline_start

        # Header
        self.console.print("[bold]Extraction complete[/bold]")
        self.console.print()

        # Counts
        self.console.print(f"  Pages extracted: [green]{result.success_count}[/green]")
        if result.error_count:
            self.console.print(f"  Errors:          [red]{result.error_count}[/red]")
        if result.skipped:
            self.console.print(f"  Skipped:         [yellow]{len(result.skipped)}[/yellow]")
        if result.skipped_categories:
            self.console.print(
                f"  Category pages:  [yellow]{len(result.skipped_categories)}[/yellow]"
            )
        self.console.print()

        # Timing breakdown
        done_timings = [
            t for t in result.page_timings if t.status == PageStatus.DONE
        ]

        self.console.print("[bold]Timing[/bold]")
        self.console.print(f"  Total:     {total_time:.1f}s")
        if result.discovery_duration:
            self.console.print(f"  Discovery: {result.discovery_duration:.1f}s")
        if result.output_duration:
            self.console.print(f"  Output:    {result.output_duration:.1f}s")

        if done_timings:
            fetch_times = [t.fetch_duration for t in done_timings if t.fetch_duration]
            extract_times = [t.extract_duration for t in done_timings if t.extract_duration]
            convert_times = [t.convert_duration for t in done_timings if t.convert_duration]

            if fetch_times:
                avg = sum(fetch_times) / len(fetch_times)
                total = sum(fetch_times)
                self.console.print(f"  Fetch:     avg {avg:.2f}s, total {total:.1f}s")
            if extract_times:
                avg = sum(extract_times) / len(extract_times)
                total = sum(extract_times)
                self.console.print(f"  Extract:   avg {avg:.2f}s, total {total:.1f}s")
            if convert_times:
                avg = sum(convert_times) / len(convert_times)
                total = sum(convert_times)
                self.console.print(f"  Convert:   avg {avg:.2f}s, total {total:.1f}s")

        # Throughput
        if total_time > 0 and result.success_count > 0:
            throughput = result.success_count / total_time
            self.console.print()
            self.console.print(f"  [bold]Throughput: {throughput:.1f} pages/sec[/bold]")

        # Top 5 slowest pages
        if done_timings:
            slowest = sorted(done_timings, key=lambda t: t.total_duration, reverse=True)[:5]
            self.console.print()
            self.console.print("[bold]Slowest pages[/bold]")
            for timing in slowest:
                url_short = _truncate_url(timing.url, 50)
                parts = []
                if timing.fetch_duration:
                    parts.append(f"fetch {timing.fetch_duration:.1f}s")
                if timing.extract_duration:
                    parts.append(f"extract {timing.extract_duration:.1f}s")
                if timing.convert_duration:
                    parts.append(f"convert {timing.convert_duration:.1f}s")
                breakdown = ", ".join(parts)
                self.console.print(
                    f"  {url_short}  [dim]{timing.total_duration:.1f}s[/dim]"
                    f" ({breakdown})"
                )

        # Extraction methods
        if done_timings:
            method_counts: Counter[str] = Counter()
            for t in done_timings:
                if t.extraction_method:
                    method_counts[t.extraction_method] += 1
            if method_counts:
                self.console.print()
                self.console.print("[bold]Extraction methods[/bold]")
                for method, count in method_counts.most_common():
                    self.console.print(f"  {method:<15s} {count}")

        # Content quality
        if result.pages:
            page_sizes = [len(p.markdown) for p in result.pages]
            total_output = sum(page_sizes)
            avg_size = total_output // len(page_sizes)
            tiny = sum(1 for s in page_sizes if s < 1024)
            small = sum(1 for s in page_sizes if 1024 <= s < 5120)
            normal = sum(1 for s in page_sizes if 5120 <= s < 20480)
            large = sum(1 for s in page_sizes if s >= 20480)

            self.console.print()
            self.console.print("[bold]Content quality[/bold]")
            self.console.print(f"  Total output:    {_format_size(total_output)}")
            self.console.print(f"  Avg page size:   {_format_size(avg_size)}")
            self.console.print(
                f"  Size distribution: {tiny} tiny (<1KB), {small} small,"
                f" {normal} normal, {large} large (>20KB)"
            )
            if len(page_sizes) > 0 and tiny / len(page_sizes) > 0.3:
                self.console.print(
                    "  [yellow]Warning: >30% of pages are tiny — check extraction quality[/yellow]"
                )

        # Rate limiting
        if self.rate_limiter.backoff_count > 0:
            self.console.print()
            self.console.print("[bold]Rate limiting[/bold]")
            self.console.print(
                f"  429 backoffs:    {self.rate_limiter.backoff_count}"
            )
            self.console.print(
                f"  Peak delay:      {self.rate_limiter.peak_delay:.1f}s"
            )
            self.console.print(
                f"  Final delay:     {self.rate_limiter.delay_seconds:.1f}s"
                f" (configured {self.rate_limiter._original_delay:.1f}s)"
            )

        # Retries
        retried = [t for t in result.page_timings if t.retry_attempts > 1]
        if retried:
            total_retries = sum(t.retry_attempts - 1 for t in retried)
            most_retried = max(retried, key=lambda t: t.retry_attempts)
            self.console.print()
            self.console.print("[bold]Retries[/bold]")
            self.console.print(f"  Pages retried:   {len(retried)}")
            self.console.print(f"  Total retries:   {total_retries}")
            self.console.print(
                f"  Most retried:    {_truncate_url(most_retried.url, 40)}"
                f" ({most_retried.retry_attempts} attempts)"
            )

        # Errors
        if result.errors:
            self.console.print()
            # Category breakdown
            category_counts: Counter[ErrorCategory] = Counter()
            for _url, _msg, cat in result.errors:
                category_counts[cat] += 1
            self.console.print("[bold red]Errors[/bold red]")
            for cat, count in category_counts.most_common():
                self.console.print(f"  {cat.value:<15s} {count}")
            top_cat = category_counts.most_common(1)[0][0]
            suggestion = _ERROR_SUGGESTIONS.get(top_cat)
            if suggestion:
                self.console.print(f"  [dim]Suggestion: {suggestion}[/dim]")
            self.console.print()
            for url, error, _cat in result.errors[:10]:
                url_short = _truncate_url(url, 50)
                self.console.print(f"  [red]{url_short}[/red]: {error}")
            if len(result.errors) > 10:
                self.console.print(
                    f"  [dim]... and {len(result.errors) - 10} more errors[/dim]"
                )

    async def _process_page(
        self,
        discovered,
        fetcher: BaseFetcher,
        extractor: ContentExtractor,
        formatter: LLMFormatter,
        result: ExtractionResult,
        progress: Progress,
        task_id,
        cached_probe: FetchResult | None,
        timing: PageTiming,
    ) -> None:
        """Fetch, extract, and format a single page with rate limiting."""
        url = discovered.url

        # Pre-filter obvious category pages by URL before expensive fetch
        if self._is_likely_category_url(url):
            result.skipped_categories.append(url)
            timing.status = PageStatus.SKIPPED
            progress.update(task_id, advance=1)
            return

        try:
            await self.rate_limiter.acquire()
            try:
                timing.status = PageStatus.FETCHING
                timing.fetch_start = time.monotonic()

                # Reuse the probe result if this is the same URL
                if cached_probe and url == cached_probe.url:
                    fetch_result = cached_probe
                else:
                    fetch_result = await fetcher.fetch_with_retry(
                        url,
                        self.config.rate_limit.max_retries,
                        self.config.rate_limit.retry_base_delay,
                    )

                timing.fetch_end = time.monotonic()
                timing.retry_attempts = fetch_result.attempts

                if not fetch_result.success:
                    if fetch_result.status_code == 429:
                        self.rate_limiter.back_off()
                        if self.config.verbose:
                            self.console.print(
                                f"[yellow]429 backoff: {url}"
                                f" → delay {self.rate_limiter.delay_seconds:.1f}s[/yellow]"
                            )
                    error_msg = fetch_result.error or f"HTTP {fetch_result.status_code}"
                    category = self._categorize_error(
                        fetch_result.status_code, error_msg, "fetch"
                    )
                    result.errors.append((url, error_msg, category))
                    timing.status = PageStatus.ERROR
                    timing.error = error_msg
                    return

                # Use final URL (accounts for client-side redirects)
                effective_url = fetch_result.final_url or url

                timing.status = PageStatus.EXTRACTING
                timing.extract_start = time.monotonic()

                content = extractor.extract(fetch_result.html, effective_url)

                timing.extract_end = time.monotonic()
                timing.extraction_method = (content.extraction_method or "") if content else ""

                if not content or not content.html:
                    result.skipped.append(url)
                    timing.status = PageStatus.SKIPPED
                    return

                if self._is_login_gated(content):
                    result.skipped.append(url)
                    timing.status = PageStatus.SKIPPED
                    return

                timing.status = PageStatus.CONVERTING
                timing.convert_start = time.monotonic()

                # Format — pass raw HTML so API schema detection
                # operates on the full, uncleaned page DOM
                page = formatter.format_page(
                    content, effective_url, raw_html=fetch_result.html
                )

                timing.convert_end = time.monotonic()

                if self._is_category_page(page):
                    result.skipped_categories.append(url)
                    timing.status = PageStatus.SKIPPED
                    return

                result.pages.append(page)
                timing.status = PageStatus.DONE
                self.rate_limiter.ease_off()

            finally:
                self.rate_limiter.release()
        except Exception as e:
            error_msg = str(e)
            category = self._categorize_error(0, error_msg, "pipeline")
            result.errors.append((url, error_msg, category))
            timing.status = PageStatus.ERROR
            timing.error = error_msg
        finally:
            progress.update(task_id, advance=1)

    @staticmethod
    def _categorize_error(
        status_code: int, error_msg: str, stage: str
    ) -> ErrorCategory:
        """Classify an error into a reporting category."""
        if status_code == 429:
            return ErrorCategory.RATE_LIMITED
        if status_code >= 500:
            return ErrorCategory.SERVER_ERROR
        if 400 <= status_code < 500:
            return ErrorCategory.CLIENT_ERROR
        msg_lower = error_msg.lower()
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return ErrorCategory.TIMEOUT
        if any(
            kw in msg_lower
            for kw in ("connect", "refused", "dns", "network", "socket")
        ):
            return ErrorCategory.CONNECTION
        if stage == "extract" or stage == "pipeline":
            return ErrorCategory.EXTRACTION
        return ErrorCategory.UNKNOWN

    def _get_pattern(self) -> SitePattern | None:
        """Get the site pattern if specified."""
        if self.config.pattern:
            pattern = PatternRegistry.get(self.config.pattern)
            if pattern:
                return pattern
            else:
                self.console.print(
                    f"[yellow]Warning: Unknown pattern "
                    f"'{self.config.pattern}', using defaults.[/yellow]"
                )
        return None

    def _apply_pattern(self, pattern: SitePattern) -> None:
        """Apply pattern settings to config (creates new sub-config objects)."""
        parts: list[str] = []
        if pattern.content_selectors:
            parts.append(f"{len(pattern.content_selectors)} content selectors")
        if pattern.remove_selectors:
            parts.append(f"{len(pattern.remove_selectors)} remove selectors")
        if pattern.requires_js:
            parts.append("requires JS")
        if parts:
            self.console.print(
                f"[blue]Applied pattern '{pattern.name}': {', '.join(parts)}[/blue]"
            )

        extractor_updates: dict = {}
        if pattern.content_selectors:
            extractor_updates["content_selectors"] = (
                pattern.content_selectors + self.config.extractor.content_selectors
            )
        if pattern.remove_selectors:
            extractor_updates["remove_selectors"] = (
                pattern.remove_selectors + self.config.extractor.remove_selectors
            )
        if extractor_updates:
            self.config.extractor = self.config.extractor.model_copy(
                update=extractor_updates
            )

        fetcher_updates: dict = {}
        if pattern.requires_js:
            fetcher_updates["use_js"] = True
        if pattern.wait_selector:
            fetcher_updates["wait_selector"] = pattern.wait_selector
        if pattern.wait_time_ms:
            fetcher_updates["wait_time_ms"] = pattern.wait_time_ms
        if pattern.click_tabs_selector:
            fetcher_updates["click_tabs_selector"] = pattern.click_tabs_selector
        if fetcher_updates:
            self.config.fetcher = self.config.fetcher.model_copy(
                update=fetcher_updates
            )

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

    @staticmethod
    def _is_category_page(page: FormattedPage) -> bool:
        """Detect if a page is predominantly a link list (category/index page).

        Returns True if link-list items make up >70% of content lines
        (excluding headings and blank/separator lines).
        """
        lines = page.markdown.split("\n")
        link_list_count = 0
        content_count = 0

        for line in lines:
            stripped = line.strip()
            # Skip blank lines, separators, and headings
            if not stripped or stripped.startswith("#") or stripped == "---":
                continue
            content_count += 1
            # Match list items that are primarily links:
            # - **[text](url)** or - [text](url) or * [text](url)
            if re.match(
                r"^[-*]\s+(\*\*)?(\[.+?\]\(.+?\))(\*\*)?\s*$",
                stripped,
            ):
                link_list_count += 1

        if content_count == 0:
            return False

        return link_list_count / content_count > 0.7

    @staticmethod
    def _is_likely_category_url(url: str) -> bool:
        """Heuristic: detect obvious category/index pages by URL pattern.

        Docusaurus generates /category/ URLs for sidebar section pages.
        These are link lists with no substantive content.
        """
        parsed = urlparse(url)
        return "/category/" in parsed.path.lower()

    @staticmethod
    def _is_login_gated(content: ExtractedContent) -> bool:
        """Detect if the page is a login/auth gate with no real content."""
        text = content.text or ""
        if len(text) >= 500:
            return False

        login_keywords = [
            "please login",
            "please log in",
            "please sign in",
            "sign in to",
            "authentication required",
            "log in to continue",
            "sign in to continue",
            "you must be logged in",
            "you need to sign in",
            "login required",
        ]
        text_lower = text.lower()
        return any(kw in text_lower for kw in login_keywords)

    async def _write_output(
        self, pages: list[FormattedPage], site_info: SiteInfo
    ) -> Path:
        """Write the output files."""
        writer: SingleFileOutput | MultiFileOutput
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


def _format_size(size_bytes: int) -> str:
    """Format a byte size as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _truncate_url(url: str, max_len: int) -> str:
    """Truncate a URL for display, keeping the path visible."""
    parsed = urlparse(url)
    path = parsed.path
    if len(path) > max_len:
        return "..." + path[-(max_len - 3):]
    return path or url[:max_len]
