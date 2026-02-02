"""Main orchestrator that coordinates the extraction pipeline."""

import asyncio
import hashlib
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
from rich.panel import Panel
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
    JsCrawlerDiscoverer,
    ManualDiscoverer,
    SitemapDiscoverer,
)
from doc_retrieval.extractor import ContentExtractor
from doc_retrieval.extractor.main_content import ExtractedContent
from doc_retrieval.fetcher import BaseFetcher, HttpFetcher, PlaywrightFetcher
from doc_retrieval.fetcher.base import FetchResult
from doc_retrieval.fetcher.cache import ResponseCache
from doc_retrieval.output.chunked_output import ChunkedOutput
from doc_retrieval.output.debug_html import DebugHtmlWriter
from doc_retrieval.output.json_output import JsonlOutput, JsonOutput
from doc_retrieval.output.metrics import write_metrics
from doc_retrieval.output.multi_file import MultiFileOutput
from doc_retrieval.output.single_file import SingleFileOutput
from doc_retrieval.patterns import PatternRegistry, SitePattern
from doc_retrieval.pipeline import HookPoint, Pipeline
from doc_retrieval.state import StateManager
from doc_retrieval.utils.rate_limiter import RateLimiter
from doc_retrieval.utils.robots import RobotsChecker
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
        self.deduplicated_count: int = 0
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

        # Debug HTML saving
        self._debug_html: DebugHtmlWriter | None = None
        if config.save_html:
            self._debug_html = DebugHtmlWriter(config.output.path.parent)

        # State management for resume
        self._state_manager: StateManager | None = None
        if config.resume or config.state_file:
            state_path = config.state_file or Path(".doc-retrieval-state.json")
            self._state_manager = StateManager(state_path)

        # HTTP response cache
        self._cache: ResponseCache | None = None
        if not config.no_cache:
            cache_dir = config.cache_dir or Path.home() / ".cache" / "doc-retrieval"
            self._cache = ResponseCache(cache_dir)

        # Content-hash deduplication
        self._content_hashes: dict[str, str] = {}  # hash -> canonical URL
        self._content_hash_lock = asyncio.Lock()

        # Pipeline hooks
        self._pipeline = Pipeline.from_config(config.hooks) if config.hooks else Pipeline()

    async def run(self) -> ExtractionResult:
        """Execute the full extraction pipeline."""
        result = ExtractionResult()
        result.pipeline_start = time.monotonic()

        # Register user-defined custom patterns from config
        for name, custom in self.config.custom_patterns.items():
            data = custom.model_dump()
            data["name"] = name
            PatternRegistry.register(SitePattern(**data))
            if self.config.verbose:
                self.console.print(f"[blue]Registered custom pattern: {name}[/blue]")

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
            markdown_cleanup_patterns=self.config.extractor.markdown_cleanup_patterns or None,
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

        # Robots.txt filtering
        robots: RobotsChecker | None = None
        if not self.config.ignore_robots:
            robots = RobotsChecker(
                user_agent=self.config.fetcher.user_agent,
            )
            loaded = await robots.load(self.config.base_url)
            if loaded:
                before_robots = len(urls)
                urls = [u for u in urls if robots.is_allowed(u.url)]
                blocked = before_robots - len(urls)
                if blocked:
                    self.console.print(
                        f"[dim]Blocked {blocked} URLs by robots.txt[/dim]"
                    )

        # Resume: load state and skip already-completed URLs
        if self._state_manager and self.config.resume:
            run_state = self._state_manager.load(self.config.base_url)
            completed = run_state.completed_urls
            if completed:
                before_resume = len(urls)
                urls = [u for u in urls if u.url not in completed]
                resumed_count = before_resume - len(urls)
                if resumed_count:
                    self.console.print(
                        f"[blue]Resuming: skipped {resumed_count}"
                        f" already-completed pages[/blue]"
                    )
        elif self._state_manager:
            # Not resuming but state file configured — start fresh state
            self._state_manager.load(self.config.base_url)

        result.discovery_duration = time.monotonic() - discovery_start
        disc_rate = len(urls) / result.discovery_duration if result.discovery_duration > 0 else 0
        self.console.print(
            f"[green]Found {len(urls)} pages to extract[/green]"
            f" [dim]({disc_rate:.1f} pages/sec)[/dim]"
        )

        # Dry-run: extract a few sample pages and display results
        if self.config.dry_run:
            proceed = await self._run_dry_run(urls, extractor, formatter, pattern)
            if not proceed:
                self.console.print("[yellow]Dry run complete — extraction cancelled.[/yellow]")
                result.pipeline_end = time.monotonic()
                return result

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
                        detection = PatternRegistry.detect_with_confidence(
                            first_url, probe_result.html
                        )
                        if detection:
                            pattern = detection.pattern
                            self._apply_pattern(pattern)
                            if self.config.verbose:
                                self.console.print(
                                    f"[blue]Auto-detected pattern:"
                                    f" {pattern.name}"
                                    f" (score={detection.score},"
                                    f" confidence={detection.confidence:.0%})[/blue]"
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

            if self.config.output.mode == OutputMode.MULTI:
                md_files = list(output_path.glob("*.md"))
                total_size = sum(f.stat().st_size for f in md_files)
                self.console.print(
                    f"[green]Written to {output_path}/"
                    f" ({len(md_files)} files, {_format_size(total_size)} total)[/green]"
                )
            else:
                size = output_path.stat().st_size
                self.console.print(
                    f"[green]Written to {output_path}"
                    f" ({_format_size(size)}, {len(result.pages)} pages)[/green]"
                )

        result.pipeline_end = time.monotonic()

        # Write metrics JSON
        if result.pages:
            metrics_path = write_metrics(
                output_path=self.config.output.path,
                pages=result.pages,
                errors=result.errors,
                skipped=result.skipped,
                skipped_categories=result.skipped_categories,
                timings=result.page_timings,
                pipeline_start=result.pipeline_start,
                pipeline_end=result.pipeline_end,
                discovery_duration=result.discovery_duration,
                output_duration=result.output_duration,
                base_url=self.config.base_url,
                cache_hits=self._cache.hits if self._cache else 0,
                cache_misses=self._cache.misses if self._cache else 0,
            )
            if self.config.verbose:
                self.console.print(f"[dim]Metrics written to {metrics_path}[/dim]")

        # Finalize state file for resume
        if self._state_manager:
            self._state_manager.finalize()
            self.console.print(
                f"[dim]State saved to {self._state_manager.state_path}[/dim]"
            )

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
        if result.deduplicated_count:
            self.console.print(
                f"  Deduplicated:    [yellow]{result.deduplicated_count}[/yellow]"
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

            # Quality score distribution
            scores = [p.quality_score for p in result.pages]
            avg_score = sum(scores) // len(scores) if scores else 0
            low_quality = sum(1 for s in scores if s < 30)
            medium_quality = sum(1 for s in scores if 30 <= s < 60)
            high_quality = sum(1 for s in scores if s >= 60)
            self.console.print(
                f"  Quality scores:  avg {avg_score}/100"
                f" ({low_quality} low, {medium_quality} medium, {high_quality} high)"
            )
            if low_quality > 0:
                low_pages = [
                    p for p in result.pages if p.quality_score < 30
                ][:5]
                self.console.print(
                    "  [yellow]Low-quality pages:[/yellow]"
                )
                for p in low_pages:
                    self.console.print(
                        f"    {_truncate_url(p.url, 50)}"
                        f"  score={p.quality_score}"
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

        # Cache stats
        if self._cache and (self._cache.hits or self._cache.misses):
            self.console.print()
            self.console.print("[bold]Cache[/bold]")
            self.console.print(f"  Hits:   {self._cache.hits}")
            self.console.print(f"  Misses: {self._cache.misses}")

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

    async def _run_dry_run(
        self,
        urls: list,
        extractor: ContentExtractor,
        formatter: LLMFormatter,
        pattern: SitePattern | None,
    ) -> bool:
        """Extract a few sample pages and display a preview.

        Returns True if the user wants to proceed with full extraction.
        Uses a separate fetcher instance so the main fetcher is unaffected.
        """
        from rich.prompt import Confirm

        # Pick up to 3 representative pages: first, middle, last
        indices = [0]
        if len(urls) > 2:
            indices.append(len(urls) // 2)
        if len(urls) > 1:
            indices.append(len(urls) - 1)
        samples = [urls[i] for i in indices]

        self.console.print()
        self.console.print(
            f"[bold blue]Dry run:[/bold blue] extracting {len(samples)}"
            f" sample page(s) from {len(urls)} discovered..."
        )

        preview_fetcher = self._create_fetcher()
        async with preview_fetcher:
            # Auto-detect pattern from first page if not set
            if not pattern:
                try:
                    probe = await preview_fetcher.fetch(samples[0].url)
                    if probe.html:
                        detection = PatternRegistry.detect_with_confidence(
                            samples[0].url, probe.html
                        )
                        if detection:
                            pattern = detection.pattern
                            self._apply_pattern(pattern)
                            self.console.print(
                                f"[blue]Auto-detected pattern:"
                                f" {pattern.name}"
                                f" (confidence={detection.confidence:.0%})[/blue]"
                            )
                except Exception:
                    pass

            for discovered in samples:
                url = discovered.url
                try:
                    fetch_result = await preview_fetcher.fetch(url)
                    if not fetch_result.success:
                        self.console.print(
                            f"\n[red]Failed:[/red] {url}"
                            f" — {fetch_result.error or f'HTTP {fetch_result.status_code}'}"
                        )
                        continue

                    effective_url = fetch_result.final_url or url
                    content = await asyncio.to_thread(
                        extractor.extract, fetch_result.html, effective_url,
                    )
                    if not content or not content.html:
                        self.console.print(f"\n[yellow]No content extracted:[/yellow] {url}")
                        continue

                    page = await asyncio.to_thread(
                        formatter.format_page,
                        content, effective_url, raw_html=fetch_result.html,
                    )

                    # Display preview
                    preview_len = 500
                    preview = page.markdown[:preview_len]
                    if len(page.markdown) > preview_len:
                        preview += "\n..."

                    info_lines = [
                        f"[bold]URL:[/bold] {url}",
                        f"[bold]Title:[/bold] {page.title or '(none)'}",
                        f"[bold]Extraction method:[/bold] {content.extraction_method or 'unknown'}",
                        f"[bold]Content length:[/bold] {len(page.markdown):,} chars",
                        "",
                        preview,
                    ]
                    self.console.print()
                    self.console.print(Panel(
                        "\n".join(info_lines),
                        title=f"Preview: {_truncate_url(url, 60)}",
                        border_style="cyan",
                    ))

                except Exception as e:
                    self.console.print(f"\n[red]Error extracting {url}:[/red] {e}")

        self.console.print()
        return Confirm.ask(
            f"Proceed with full extraction of {len(urls)} pages?",
            default=True,
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

        # Run pre_fetch hooks (may modify URL or skip by returning None)
        if self._pipeline.has_hooks(HookPoint.PRE_FETCH):
            hook_url = await self._pipeline.run_pre_fetch(url)
            if hook_url is None:
                result.skipped.append(url)
                timing.status = PageStatus.SKIPPED
                progress.update(task_id, advance=1)
                return
            url = hook_url

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

                # Check HTTP cache first
                cache_hit = False
                entry = None
                if self._cache:
                    entry, cached_html = self._cache.get(url)
                    if entry is not None and cached_html is not None:
                        fetch_result = self._cache.make_cached_result(
                            url, entry, cached_html
                        )
                        cache_hit = True

                if not cache_hit:
                    # Reuse the probe result if this is the same URL
                    if cached_probe and url == cached_probe.url:
                        fetch_result = cached_probe
                    else:
                        cond_headers: dict[str, str] | None = None
                        if self._cache and entry is not None:
                            cond_headers = self._cache.conditional_headers(entry) or None

                        fetch_result = await fetcher.fetch_with_retry(
                            url,
                            self.config.rate_limit.max_retries,
                            self.config.rate_limit.retry_base_delay,
                            extra_headers=cond_headers,
                        )

                        # Reuse cached HTML on 304 Not Modified
                        if (
                            fetch_result.status_code == 304
                            and self._cache
                            and entry is not None
                        ):
                            reuse_html = self._cache.read_cached_html(url)
                            if reuse_html is not None:
                                fetch_result = self._cache.make_cached_result(
                                    url, entry, reuse_html
                                )
                                self._cache.put(url, fetch_result)
                                cache_hit = True

                    # Store successful responses in cache
                    if self._cache and fetch_result.success and not cache_hit:
                        self._cache.put(url, fetch_result)

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

                html = fetch_result.html

                # post_fetch hook
                if self._pipeline.has_hooks(HookPoint.POST_FETCH):
                    html = await self._pipeline.run_post_fetch(effective_url, html)

                # pre_extract hook
                if self._pipeline.has_hooks(HookPoint.PRE_EXTRACT):
                    html = await self._pipeline.run_pre_extract(effective_url, html)

                timing.status = PageStatus.EXTRACTING
                timing.extract_start = time.monotonic()

                content = await asyncio.to_thread(extractor.extract, html, effective_url)

                timing.extract_end = time.monotonic()
                timing.extraction_method = (content.extraction_method or "") if content else ""

                if self._debug_html:
                    await self._debug_html.save(
                        url=effective_url,
                        base_url=self.config.base_url,
                        html=fetch_result.html,
                        extraction_method=timing.extraction_method or None,
                        content_length=len(content.html) if content and content.html else 0,
                    )

                if not content or not content.html:
                    result.skipped.append(url)
                    timing.status = PageStatus.SKIPPED
                    return

                if self._is_login_gated(content):
                    result.skipped.append(url)
                    timing.status = PageStatus.SKIPPED
                    return

                # post_extract hook
                if self._pipeline.has_hooks(HookPoint.POST_EXTRACT):
                    content = await self._pipeline.run_post_extract(effective_url, content)

                # pre_convert hook
                if self._pipeline.has_hooks(HookPoint.PRE_CONVERT):
                    content = await self._pipeline.run_pre_convert(effective_url, content)

                timing.status = PageStatus.CONVERTING
                timing.convert_start = time.monotonic()

                # Format — pass raw HTML so API schema detection
                # operates on the full, uncleaned page DOM
                page = await asyncio.to_thread(
                    formatter.format_page,
                    content, effective_url, raw_html=fetch_result.html,
                )

                timing.convert_end = time.monotonic()

                # post_convert hook
                if self._pipeline.has_hooks(HookPoint.POST_CONVERT):
                    page = await self._pipeline.run_post_convert(effective_url, page)

                # Content-hash deduplication
                content_hash = hashlib.sha256(page.markdown.encode()).hexdigest()[:16]
                async with self._content_hash_lock:
                    canonical_url = self._content_hashes.get(content_hash)
                    if canonical_url is not None:
                        result.skipped.append(url)
                        result.deduplicated_count += 1
                        timing.status = PageStatus.SKIPPED
                        self._save_page_state(url, "skipped")
                        return
                    self._content_hashes[content_hash] = url

                if self._is_category_page(page):
                    result.skipped_categories.append(url)
                    timing.status = PageStatus.SKIPPED
                    return

                result.pages.append(page)
                timing.status = PageStatus.DONE
                self.rate_limiter.ease_off()
                self._save_page_state(url, "completed")

            finally:
                self.rate_limiter.release()
        except Exception as e:
            error_msg = str(e)
            category = self._categorize_error(0, error_msg, "pipeline")
            result.errors.append((url, error_msg, category))
            timing.status = PageStatus.ERROR
            timing.error = error_msg
            self._save_page_state(url, "failed", error_msg)
        finally:
            progress.update(task_id, advance=1)

    def _save_page_state(
        self, url: str, status: str, error: str | None = None
    ) -> None:
        """Record page status in the state file for resume support."""
        if not self._state_manager or not self._state_manager._state:
            return
        state = self._state_manager._state
        if status == "completed":
            state.mark_completed(url)
        elif status == "failed":
            state.mark_failed(url, error or "unknown")
        else:
            state.mark_skipped(url)
        self._state_manager.save()

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
        """Apply pattern settings to config via PatternRegistry.apply_to_config()."""
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

        self.config = PatternRegistry.apply_to_config(pattern.name, self.config)

    def _create_discoverer(self) -> BaseDiscoverer:
        """Create the appropriate discoverer."""
        mode = self.config.discovery.mode

        if mode == DiscoveryMode.SITEMAP:
            return SitemapDiscoverer(self.config.base_url, self.config.discovery)
        elif mode == DiscoveryMode.CRAWL:
            return CrawlerDiscoverer(self.config.base_url, self.config.discovery)
        elif mode == DiscoveryMode.CRAWL_JS:
            return JsCrawlerDiscoverer(self.config.base_url, self.config.discovery)
        elif mode == DiscoveryMode.MANUAL:
            return ManualDiscoverer(self.config.base_url, self.config.discovery)
        else:
            raise ValueError(f"Unknown discovery mode: {mode}")

    def _create_fetcher(self) -> BaseFetcher:
        """Create the appropriate fetcher."""
        auth = self.config.auth
        if self.config.fetcher.use_js:
            return PlaywrightFetcher(self.config.fetcher, auth=auth)
        else:
            return HttpFetcher(self.config.fetcher, auth=auth)

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
        mode = self.config.output.mode
        path = self.config.output.path

        writer: SingleFileOutput | MultiFileOutput | JsonOutput | JsonlOutput | ChunkedOutput
        if mode == OutputMode.SINGLE:
            writer = SingleFileOutput(
                path,
                include_metadata=self.config.output.include_metadata,
                include_toc=self.config.output.include_toc,
            )
        elif mode == OutputMode.JSON:
            writer = JsonOutput(path)
        elif mode == OutputMode.JSONL:
            writer = JsonlOutput(path)
        elif mode == OutputMode.CHUNKED:
            chunk_cfg = self.config.output.chunk
            writer = ChunkedOutput(
                path,
                max_tokens=chunk_cfg.max_tokens,
                overlap_tokens=chunk_cfg.overlap_tokens,
            )
        elif mode == OutputMode.MULTI:
            writer = MultiFileOutput(
                path,
                include_metadata=self.config.output.include_metadata,
            )
        else:
            raise ValueError(f"Unknown output mode: {mode}")

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
