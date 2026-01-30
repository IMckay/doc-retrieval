"""Command-line interface for doc-retrieval."""

import asyncio
from pathlib import Path
from urllib.parse import urlparse as _urlparse

import typer
from rich.console import Console
from rich.prompt import Confirm as _Confirm
from rich.table import Table

from doc_retrieval import __version__
from doc_retrieval.config import (
    AppConfig,
    AuthConfig,
    BatchConfig,
    ChunkConfig,
    DiscoveryConfig,
    DiscoveryMode,
    ExtractorConfig,
    FetcherConfig,
    OutputConfig,
    OutputMode,
    RateLimitConfig,
)
from doc_retrieval.interactive import InteractiveExtractor
from doc_retrieval.orchestrator import Orchestrator
from doc_retrieval.patterns import PatternRegistry

app = typer.Typer(
    name="doc-retrieval",
    help="Extract documentation from websites as LLM-ready Markdown.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"doc-retrieval version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
):
    """Documentation extraction tool for LLM consumption."""
    pass


@app.command()
def extract(
    url: str = typer.Argument(..., help="Base URL of the documentation site"),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        "-I/-N",
        help="Interactive mode (default) or direct mode for scripting",
    ),
    output: Path = typer.Option(
        Path("./output.md"),
        "--output",
        "-o",
        help="Output file or directory path",
    ),
    mode: str = typer.Option(
        "single",
        "--mode",
        "-m",
        help="Output mode: 'single', 'multi', 'json', 'jsonl', or 'chunked'",
    ),
    chunk_size: int = typer.Option(
        4000,
        "--chunk-size",
        help="Max tokens per chunk (for chunked mode)",
    ),
    chunk_overlap: int = typer.Option(
        200,
        "--chunk-overlap",
        help="Overlap tokens between chunks (for chunked mode)",
    ),
    discovery: str = typer.Option(
        "sitemap",
        "--discovery",
        "-d",
        help="Discovery method: 'sitemap', 'crawl', 'crawl-js', or 'manual'",
    ),
    urls_file: Path | None = typer.Option(
        None,
        "--urls-file",
        "-f",
        help="File containing URLs (one per line) for manual discovery mode",
    ),
    include_pattern: str | None = typer.Option(
        None,
        "--include",
        "-i",
        help="Regex pattern for URLs to include",
    ),
    exclude_pattern: str | None = typer.Option(
        None,
        "--exclude",
        "-e",
        help="Regex pattern for URLs to exclude",
    ),
    max_pages: int = typer.Option(
        0,
        "--max-pages",
        help="Maximum pages to extract (0 = unlimited)",
    ),
    max_depth: int = typer.Option(
        3,
        "--max-depth",
        help="Maximum crawl depth for crawl discovery mode",
    ),
    delay: float = typer.Option(
        1.0,
        "--delay",
        help="Delay between requests in seconds",
    ),
    js: bool = typer.Option(
        True,
        "--js/--no-js",
        help="Enable/disable JavaScript rendering",
    ),
    pattern: str | None = typer.Option(
        None,
        "--pattern",
        "-p",
        help="Site pattern preset (use 'list-patterns' to see all available)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="TOML config file",
    ),
    skip_urls: Path | None = typer.Option(
        None,
        "--skip-urls",
        help="File with URLs to skip (one per line)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "--preview",
        help="Extract 1-3 sample pages and display results before full run",
    ),
    header: list[str] | None = typer.Option(
        None,
        "--header",
        "-H",
        help="Custom HTTP header (format: 'Name: Value'), repeatable",
    ),
    cookie: list[str] | None = typer.Option(
        None,
        "--cookie",
        help="Cookie (format: 'name=value'), repeatable",
    ),
    cookie_file: Path | None = typer.Option(
        None,
        "--cookie-file",
        help="Netscape-format cookie jar file",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume a previous run, skipping already-completed pages",
    ),
    state_file: Path | None = typer.Option(
        None,
        "--state-file",
        help="Path to state file for resume (default: .doc-retrieval-state.json)",
    ),
    save_html: bool = typer.Option(
        False,
        "--save-html",
        help="Save raw fetched HTML alongside output for debugging",
    ),
    ignore_robots: bool = typer.Option(
        False,
        "--ignore-robots",
        help="Ignore robots.txt crawl directives",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Disable HTTP response caching",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="Cache directory (default: ~/.cache/doc-retrieval)",
    ),
):
    """
    Extract documentation from a website and convert to Markdown.

    By default, runs in interactive mode which guides you through the process.
    Use -N/--no-interactive for scripting or automation.

    Examples:

        doc-retrieval extract https://docs.example.com

        doc-retrieval extract https://docs.example.com -N -o docs.md

        doc-retrieval extract https://docs.example.com -N --mode multi -o ./docs/

        doc-retrieval extract https://docs.example.com -N --discovery crawl

        doc-retrieval extract https://docs.example.com -N --pattern docusaurus
    """
    if interactive:
        try:
            extractor = InteractiveExtractor(console)
            config = asyncio.run(extractor.run(url))
            if config:
                orchestrator = Orchestrator(config, console)
                asyncio.run(orchestrator.run())
                if _Confirm.ask("Save config for reuse?", default=False):
                    domain = _urlparse(url).netloc.replace(".", "-")
                    toml_path = Path(f"{domain}.toml")
                    toml_path.write_text(config.to_toml())
                    console.print(f"[green]Config saved to {toml_path}[/green]")
            else:
                console.print("[yellow]Extraction cancelled.[/yellow]")
                raise typer.Exit(0)
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")
            raise typer.Exit(130)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            if verbose:
                console.print_exception()
            raise typer.Exit(1)
        return

    if config_file:
        try:
            config = AppConfig.from_toml(config_file)
            config.base_url = url
            if skip_urls:
                config.skip_urls = skip_urls
            if verbose:
                config.verbose = True
        except Exception as e:
            console.print(f"[red]Error loading config: {e}[/red]")
            raise typer.Exit(1)
    else:
        try:
            output_mode = OutputMode(mode)
        except ValueError:
            valid = ", ".join(f"'{m.value}'" for m in OutputMode)
            console.print(f"[red]Invalid mode: {mode}. Use {valid}.[/red]")
            raise typer.Exit(1)

        try:
            discovery_mode = DiscoveryMode(discovery)
        except ValueError:
            console.print(
                f"[red]Invalid discovery: {discovery}."
                f" Use 'sitemap', 'crawl', 'crawl-js', or 'manual'.[/red]"
            )
            raise typer.Exit(1)

        if discovery_mode == DiscoveryMode.MANUAL and not urls_file:
            console.print("[red]--urls-file is required for manual discovery mode.[/red]")
            raise typer.Exit(1)

        # Parse auth options
        auth_headers: dict[str, str] = {}
        if header:
            for h in header:
                if ":" not in h:
                    console.print(f"[red]Invalid header format: {h}. Use 'Name: Value'.[/red]")
                    raise typer.Exit(1)
                name, _, value = h.partition(":")
                auth_headers[name.strip()] = value.strip()

        auth_cookies: dict[str, str] = {}
        if cookie:
            for c in cookie:
                if "=" not in c:
                    console.print(f"[red]Invalid cookie format: {c}. Use 'name=value'.[/red]")
                    raise typer.Exit(1)
                name, _, value = c.partition("=")
                auth_cookies[name.strip()] = value.strip()

        config = AppConfig(
            base_url=url,
            discovery=DiscoveryConfig(
                mode=discovery_mode,
                max_depth=max_depth,
                max_pages=max_pages,
                include_pattern=include_pattern,
                exclude_pattern=exclude_pattern,
                urls_file=urls_file,
            ),
            fetcher=FetcherConfig(
                use_js=js,
            ),
            extractor=ExtractorConfig(),
            output=OutputConfig(
                mode=output_mode,
                path=output,
                chunk=ChunkConfig(
                    max_tokens=chunk_size,
                    overlap_tokens=chunk_overlap,
                ),
            ),
            rate_limit=RateLimitConfig(
                delay_seconds=delay,
            ),
            auth=AuthConfig(
                headers=auth_headers,
                cookies=auth_cookies,
                cookie_file=cookie_file,
            ),
            pattern=pattern,
            verbose=verbose,
            skip_urls=skip_urls,
            dry_run=dry_run,
            resume=resume,
            state_file=state_file,
            save_html=save_html,
            ignore_robots=ignore_robots,
            no_cache=no_cache,
            cache_dir=cache_dir,
        )

    orchestrator = Orchestrator(config, console)

    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Extraction cancelled.[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            console.print_exception()
        raise typer.Exit(1)


@app.command("batch-extract")
def batch_extract(
    config_file: Path = typer.Argument(..., help="TOML config file with [[site]] entries"),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
):
    """
    Extract documentation from multiple sites defined in a TOML config.

    The config file should contain [[site]] entries:

        [[site]]
        url = "https://docs.example.com"
        output = "./output/example/"
        pattern = "docusaurus"

        [[site]]
        url = "https://api.example.com/docs"
        output = "./output/api/"
        mode = "json"

    Global options (verbose, delay, js, save_html, resume) can be set
    at the top level and apply to all sites.
    """
    try:
        batch = BatchConfig.from_toml(config_file)
    except Exception as e:
        console.print(f"[red]Error loading batch config: {e}[/red]")
        raise typer.Exit(1)

    if verbose:
        batch.verbose = True

    configs = batch.to_app_configs()
    console.print(f"[blue]Batch extraction: {len(configs)} sites[/blue]")

    total_pages = 0
    total_errors = 0
    failed_sites: list[str] = []

    for i, config in enumerate(configs, 1):
        console.print()
        console.print(f"[bold]═══ Site {i}/{len(configs)}: {config.base_url} ═══[/bold]")

        orchestrator = Orchestrator(config, console)
        try:
            result = asyncio.run(orchestrator.run())
            total_pages += result.success_count
            total_errors += result.error_count
        except KeyboardInterrupt:
            console.print("\n[yellow]Batch cancelled.[/yellow]")
            raise typer.Exit(130)
        except Exception as e:
            console.print(f"[red]Site failed: {config.base_url} — {e}[/red]")
            failed_sites.append(config.base_url)
            if verbose:
                console.print_exception()

    # Combined summary
    console.print()
    console.print("[bold]═══ Batch Summary ═══[/bold]")
    console.print(f"  Sites processed: {len(configs)}")
    console.print(f"  Total pages:     [green]{total_pages}[/green]")
    if total_errors:
        console.print(f"  Total errors:    [red]{total_errors}[/red]")
    if failed_sites:
        console.print(f"  Failed sites:    [red]{len(failed_sites)}[/red]")
        for site_url in failed_sites:
            console.print(f"    - {site_url}")


@app.command("list-patterns")
def list_patterns():
    """List available site pattern presets."""
    patterns = PatternRegistry.list_patterns()

    table = Table(title="Available Site Patterns")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("JS Required", justify="center")

    for pattern in patterns:
        table.add_row(
            pattern.name,
            pattern.description,
            "Yes" if pattern.requires_js else "No",
        )

    console.print(table)


if __name__ == "__main__":
    app()
