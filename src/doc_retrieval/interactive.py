"""Interactive mode for guided documentation extraction."""

import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt, IntPrompt
from rich.table import Table

from doc_retrieval.config import (
    AppConfig,
    DiscoveryConfig,
    DiscoveryMode,
    ExtractorConfig,
    FetcherConfig,
    OutputConfig,
    OutputMode,
    RateLimitConfig,
)
from doc_retrieval.discovery import CrawlerDiscoverer, DiscoveredURL, SitemapDiscoverer
from doc_retrieval.fetcher import HttpFetcher, PlaywrightFetcher
from doc_retrieval.patterns import PatternRegistry, SitePattern


class InteractiveExtractor:
    """Guide user through documentation extraction interactively."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    async def run(self, url: str) -> Optional[AppConfig]:
        """Run interactive extraction flow. Returns config if user confirms."""
        self.console.print()
        self.console.print(Panel.fit(
            "[bold blue]Documentation Extractor[/bold blue]\n"
            "Interactive mode - I'll guide you through the extraction process.",
            border_style="blue"
        ))
        self.console.print()

        # Step 1: Analyze the site
        self.console.print("[bold]Step 1:[/bold] Analyzing site...")
        site_info = await self._analyze_site(url)

        if not site_info:
            self.console.print("[red]Failed to access the site. Please check the URL.[/red]")
            return None

        # Step 2: Detect or ask for site pattern
        pattern = await self._detect_or_ask_pattern(site_info)

        # Step 3: Determine if JS rendering is needed
        use_js = await self._ask_js_rendering(site_info, pattern)

        # Step 4: Choose discovery method and discover URLs
        discovery_mode, urls = await self._discover_urls(url, pattern, use_js)

        if not urls:
            self.console.print("[yellow]No pages found to extract.[/yellow]")
            return None

        # Step 5: Let user filter/refine URL list
        urls, include_pattern, exclude_pattern = await self._refine_urls(urls)

        if not urls:
            self.console.print("[yellow]No pages selected for extraction.[/yellow]")
            return None

        # Step 6: Choose output options
        output_mode, output_path = await self._ask_output_options(url)

        # Step 7: Confirm and build config
        config = self._build_config(
            url=url,
            discovery_mode=discovery_mode,
            use_js=use_js,
            pattern=pattern,
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
            max_pages=len(urls),
            output_mode=output_mode,
            output_path=output_path,
        )

        # Show summary and confirm
        if await self._confirm_extraction(config, len(urls)):
            return config

        return None

    async def _analyze_site(self, url: str) -> Optional[dict]:
        """Fetch the site and gather basic info."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()

                return {
                    "url": url,
                    "final_url": str(response.url),
                    "status": response.status_code,
                    "html": response.text,
                    "content_length": len(response.text),
                    "has_trailing_slash": str(response.url).endswith("/"),
                }
        except Exception as e:
            self.console.print(f"[red]Error accessing site: {e}[/red]")
            return None

    async def _detect_or_ask_pattern(self, site_info: dict) -> Optional[str]:
        """Detect site pattern or ask user."""
        html = site_info["html"]
        url = site_info["final_url"]

        # Try auto-detection
        detected = PatternRegistry.detect(url, html)

        self.console.print()
        if detected:
            self.console.print(f"[green]Detected site type:[/green] {detected.name} - {detected.description}")
            use_detected = Confirm.ask("Use this pattern?", default=True)
            if use_detected:
                return detected.name

        # Show available patterns
        self.console.print("\n[bold]Available site patterns:[/bold]")
        patterns = PatternRegistry.list_patterns()

        table = Table(show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("JS", justify="center")

        table.add_row("0", "none", "No preset - use generic extraction", "-")
        for i, p in enumerate(patterns, 1):
            table.add_row(str(i), p.name, p.description, "Yes" if p.requires_js else "No")

        self.console.print(table)

        choice = IntPrompt.ask(
            "Select a pattern (0 for none)",
            default=0,
            choices=[str(i) for i in range(len(patterns) + 1)]
        )

        if choice == 0:
            return None
        return patterns[choice - 1].name

    async def _ask_js_rendering(self, site_info: dict, pattern: Optional[str]) -> bool:
        """Determine if JavaScript rendering is needed."""
        self.console.print()

        # Check if pattern requires JS
        if pattern:
            p = PatternRegistry.get(pattern)
            if p and not p.requires_js:
                self.console.print(f"[dim]Pattern '{pattern}' doesn't require JavaScript rendering.[/dim]")
                return Confirm.ask("Enable JavaScript rendering anyway?", default=False)

        # Check for signs of JS-rendered content
        html = site_info["html"]
        js_indicators = [
            "__NEXT_DATA__",
            "__NUXT__",
            "window.__INITIAL_STATE__",
            "react-root",
            "id=\"app\"",
            "id=\"root\"",
            "<noscript>",
        ]

        seems_js = any(indicator in html for indicator in js_indicators)

        if seems_js:
            self.console.print("[yellow]This site appears to use JavaScript rendering.[/yellow]")
            return Confirm.ask("Enable JavaScript rendering?", default=True)
        else:
            self.console.print("[dim]Site appears to be statically rendered.[/dim]")
            return Confirm.ask("Enable JavaScript rendering?", default=False)

    def _show_url_structure(self, urls: list[DiscoveredURL]) -> None:
        """Analyze and display URL path structure to help with filtering."""
        from collections import Counter
        from urllib.parse import urlparse

        # Count pages by top-level path segments
        path_counts: Counter = Counter()

        for discovered in urls:
            parsed = urlparse(discovered.url)
            path = parsed.path.strip("/")
            if path:
                # Get first 2-3 path segments for grouping
                segments = path.split("/")
                if len(segments) >= 2:
                    prefix = "/" + "/".join(segments[:2]) + "/"
                elif len(segments) == 1:
                    prefix = "/" + segments[0] + "/"
                else:
                    prefix = "/"
                path_counts[prefix] += 1
            else:
                path_counts["/"] += 1

        # Show top path patterns
        self.console.print("\n[bold]URL patterns found:[/bold]")
        table = Table(show_header=True, header_style="dim")
        table.add_column("Path Pattern", style="cyan")
        table.add_column("Pages", justify="right")
        table.add_column("Example Filter", style="dim")

        for pattern, count in path_counts.most_common(10):
            # Suggest a filter pattern
            filter_pattern = pattern.rstrip("/")
            table.add_row(pattern, str(count), f'--include "{filter_pattern}"')

        self.console.print(table)

        if len(path_counts) > 10:
            self.console.print(f"[dim]  ... and {len(path_counts) - 10} more patterns[/dim]")

    async def _discover_urls(
        self, url: str, pattern: Optional[str], use_js: bool
    ) -> tuple[DiscoveryMode, list[DiscoveredURL]]:
        """Discover URLs using sitemap or crawling."""
        self.console.print()
        self.console.print("[bold]Step 2:[/bold] Discovering pages...")

        # Try sitemap first
        self.console.print("  Checking for sitemap...")
        config = DiscoveryConfig(mode=DiscoveryMode.SITEMAP, max_pages=0)  # No limit initially
        discoverer = SitemapDiscoverer(url, config)

        urls = []
        try:
            with self.console.status("Reading sitemap...") as status:
                async for discovered in discoverer.discover():
                    urls.append(discovered)
                    if len(urls) % 50 == 0:
                        status.update(f"Reading sitemap... found {len(urls)} pages")
        except Exception:
            pass

        if urls:
            self.console.print(f"  [green]Found {len(urls)} pages via sitemap[/green]")
            use_sitemap = Confirm.ask("Use sitemap discovery?", default=True)
            if use_sitemap:
                return DiscoveryMode.SITEMAP, urls

        # Fall back to crawling
        self.console.print("\n  Sitemap not available or not selected. Using crawl discovery...")

        max_depth = IntPrompt.ask("Maximum crawl depth", default=3)
        max_pages = IntPrompt.ask("Maximum pages to discover (0 = unlimited)", default=100)

        config = DiscoveryConfig(
            mode=DiscoveryMode.CRAWL,
            max_depth=max_depth,
            max_pages=max_pages if max_pages > 0 else 0,
        )
        discoverer = CrawlerDiscoverer(url, config)

        urls = []
        with self.console.status("Crawling...") as status:
            async for discovered in discoverer.discover():
                urls.append(discovered)
                status.update(f"Crawling... found {len(urls)} pages")

        self.console.print(f"  [green]Found {len(urls)} pages via crawling[/green]")
        return DiscoveryMode.CRAWL, urls

    async def _refine_urls(
        self, urls: list[DiscoveredURL]
    ) -> tuple[list[DiscoveredURL], Optional[str], Optional[str]]:
        """Let user review and filter URLs."""
        self.console.print()
        self.console.print(f"[bold]Step 3:[/bold] Review discovered URLs ({len(urls)} found)")

        # Analyze URL structure to help user filter
        self._show_url_structure(urls)

        # Show sample of URLs
        self.console.print("\n[dim]Sample URLs:[/dim]")
        for url in urls[:10]:
            self.console.print(f"  • {url.url}")
        if len(urls) > 10:
            self.console.print(f"  [dim]... and {len(urls) - 10} more[/dim]")

        include_pattern = None
        exclude_pattern = None

        # Ask about filtering
        if Confirm.ask("\nWould you like to filter URLs by pattern?", default=len(urls) > 100):
            self.console.print("\n[dim]Enter regex patterns based on the paths above (or leave blank to skip)[/dim]")
            self.console.print("[dim]Tip: Use patterns like '/docs/api' to match URLs containing that path[/dim]")

            include_input = Prompt.ask("Include pattern (only URLs matching this)", default="")
            if include_input.strip():
                include_pattern = include_input.strip()

            exclude_input = Prompt.ask("Exclude pattern (remove URLs matching this)", default="")
            if exclude_input.strip():
                exclude_pattern = exclude_input.strip()

            # Apply filters and show result
            import re
            filtered = urls
            if include_pattern:
                try:
                    include_re = re.compile(include_pattern)
                    filtered = [u for u in filtered if include_re.search(u.url)]
                except re.error as e:
                    self.console.print(f"[red]Invalid include pattern: {e}[/red]")
                    include_pattern = None

            if exclude_pattern:
                try:
                    exclude_re = re.compile(exclude_pattern)
                    filtered = [u for u in filtered if not exclude_re.search(u.url)]
                except re.error as e:
                    self.console.print(f"[red]Invalid exclude pattern: {e}[/red]")
                    exclude_pattern = None

            self.console.print(f"\n[green]After filtering: {len(filtered)} pages[/green]")

            if filtered and len(filtered) != len(urls):
                self.console.print("[dim]Filtered URLs:[/dim]")
                for url in filtered[:10]:
                    self.console.print(f"  • {url.url}")
                if len(filtered) > 10:
                    self.console.print(f"  [dim]... and {len(filtered) - 10} more[/dim]")

            urls = filtered

        # Always ask about page limit
        self.console.print(f"\n[bold]Pages to extract:[/bold] {len(urls)}")
        max_pages = IntPrompt.ask(
            "How many pages to extract? (0 = all)",
            default=min(len(urls), 100)
        )

        if max_pages > 0 and max_pages < len(urls):
            urls = urls[:max_pages]
            self.console.print(f"[green]Will extract {len(urls)} pages[/green]")
        else:
            self.console.print(f"[green]Will extract all {len(urls)} pages[/green]")

        return urls, include_pattern, exclude_pattern

    async def _ask_output_options(self, url: str) -> tuple[OutputMode, Path]:
        """Ask user about output preferences."""
        self.console.print()
        self.console.print("[bold]Step 4:[/bold] Output options")

        # Output mode
        self.console.print("\n[bold]Output mode:[/bold]")
        self.console.print("  1. Single file - all pages combined into one Markdown file")
        self.console.print("  2. Multiple files - one Markdown file per page")

        mode_choice = Prompt.ask("Choose output mode", choices=["1", "2"], default="1")
        output_mode = OutputMode.SINGLE if mode_choice == "1" else OutputMode.MULTI

        # Output path
        parsed = urlparse(url)
        default_name = parsed.netloc.replace(".", "-")

        if output_mode == OutputMode.SINGLE:
            default_path = f"output/{default_name}.md"
            output_path = Prompt.ask("Output file", default=default_path)
        else:
            default_path = f"output/{default_name}/"
            output_path = Prompt.ask("Output directory", default=default_path)

        return output_mode, Path(output_path)

    def _build_config(
        self,
        url: str,
        discovery_mode: DiscoveryMode,
        use_js: bool,
        pattern: Optional[str],
        include_pattern: Optional[str],
        exclude_pattern: Optional[str],
        max_pages: int,
        output_mode: OutputMode,
        output_path: Path,
    ) -> AppConfig:
        """Build the final configuration."""
        return AppConfig(
            base_url=url,
            discovery=DiscoveryConfig(
                mode=discovery_mode,
                max_pages=max_pages,
                include_pattern=include_pattern,
                exclude_pattern=exclude_pattern,
            ),
            fetcher=FetcherConfig(use_js=use_js),
            extractor=ExtractorConfig(),
            output=OutputConfig(mode=output_mode, path=output_path),
            rate_limit=RateLimitConfig(delay_seconds=1.0),
            pattern=pattern,
            verbose=False,
        )

    async def _confirm_extraction(self, config: AppConfig, num_pages: int) -> bool:
        """Show summary and ask for confirmation."""
        self.console.print()
        self.console.print(Panel.fit(
            f"[bold]Extraction Summary[/bold]\n\n"
            f"URL: {config.base_url}\n"
            f"Pages: {num_pages}\n"
            f"Discovery: {config.discovery.mode.value}\n"
            f"JS Rendering: {'Yes' if config.fetcher.use_js else 'No'}\n"
            f"Pattern: {config.pattern or 'none'}\n"
            f"Output: {config.output.path} ({config.output.mode.value} mode)",
            title="Ready to Extract",
            border_style="green"
        ))

        return Confirm.ask("\nProceed with extraction?", default=True)
