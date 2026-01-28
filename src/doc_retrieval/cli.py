"""Command-line interface for doc-retrieval."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from doc_retrieval import __version__
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
        help="Output mode: 'single' (one file) or 'multi' (multiple files)",
    ),
    discovery: str = typer.Option(
        "sitemap",
        "--discovery",
        "-d",
        help="Discovery method: 'sitemap', 'crawl', or 'manual'",
    ),
    urls_file: Optional[Path] = typer.Option(
        None,
        "--urls-file",
        "-f",
        help="File containing URLs (one per line) for manual discovery mode",
    ),
    include_pattern: Optional[str] = typer.Option(
        None,
        "--include",
        "-i",
        help="Regex pattern for URLs to include",
    ),
    exclude_pattern: Optional[str] = typer.Option(
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
    pattern: Optional[str] = typer.Option(
        None,
        "--pattern",
        "-p",
        help="Site pattern preset (docusaurus, gitbook, readthedocs, mkdocs, sphinx, vitepress)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
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
    # Interactive mode
    if interactive:
        try:
            extractor = InteractiveExtractor(console)
            config = asyncio.run(extractor.run(url))
            if config:
                orchestrator = Orchestrator(config, console)
                asyncio.run(orchestrator.run())
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
    # Validate mode
    try:
        output_mode = OutputMode(mode)
    except ValueError:
        console.print(f"[red]Invalid mode: {mode}. Use 'single' or 'multi'.[/red]")
        raise typer.Exit(1)

    # Validate discovery
    try:
        discovery_mode = DiscoveryMode(discovery)
    except ValueError:
        console.print(f"[red]Invalid discovery: {discovery}. Use 'sitemap', 'crawl', or 'manual'.[/red]")
        raise typer.Exit(1)

    # Check manual mode requirements
    if discovery_mode == DiscoveryMode.MANUAL and not urls_file:
        console.print("[red]--urls-file is required for manual discovery mode.[/red]")
        raise typer.Exit(1)

    # Build config
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
        ),
        rate_limit=RateLimitConfig(
            delay_seconds=delay,
        ),
        pattern=pattern,
        verbose=verbose,
    )

    # Run extraction
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
