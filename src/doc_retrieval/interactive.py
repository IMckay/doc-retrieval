"""Interactive mode for guided documentation extraction."""

import re
import string
import time as _time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
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
from doc_retrieval.discovery import (
    CrawlerDiscoverer,
    DiscoveredURL,
    SitemapDiscoverer,
)
from doc_retrieval.discovery.base import BaseDiscoverer
from doc_retrieval.patterns import PatternRegistry
from doc_retrieval.patterns.registry import DetectionResult
from doc_retrieval.scanner import NavScanner, NavSection, NavSubSection, SiteStructure
from doc_retrieval.scanner.nav_scanner import auto_expand_sections, derive_sub_sections


@dataclass
class _PathGroup:
    """A group of URLs sharing the same path prefix."""

    pattern: str
    urls: list[DiscoveredURL]
    included: bool = True


@dataclass
class _FilterSuggestion:
    """A smart suggestion for filtering URL groups."""

    label: str
    action: str  # "exclude" or "include_only"
    target_indices: list[int]
    page_count: int


@dataclass
class _DisplayRow:
    """A row in the group table — single group or collapsed version cluster."""

    label: str
    group_indices: list[int]
    total_pages: int
    detail: str = ""
    is_cluster: bool = False


_VERSION_RE = re.compile(
    r"^(v?\d+(\.\d+)*|unstable|beta|alpha|rc\d*|latest|stable|nightly|canary|current|next)$",
    re.IGNORECASE,
)


class InteractiveExtractor:
    """Guide user through documentation extraction interactively."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    async def run(self, url: str) -> AppConfig | None:
        """Run interactive extraction flow. Returns config if user confirms."""
        self.console.print()
        self.console.print(Panel.fit(
            "[bold blue]Documentation Extractor[/bold blue]\n"
            "Interactive mode - I'll guide you through the extraction process.",
            border_style="blue"
        ))
        self.console.print()

        # Step 1: Analyze — fetch, detect pattern, JS decision, nav scan
        self.console.print("[bold]Step 1:[/bold] Analyzing site...")
        site_info = await self._analyze_site(url)

        if not site_info:
            self.console.print("[red]Failed to access the site. Please check the URL.[/red]")
            return None

        pattern = await self._detect_or_ask_pattern(site_info)
        use_js = await self._ask_js_rendering(site_info, pattern)
        section_include, section_exclude = await self._scan_site_structure(
            site_info, pattern, use_js
        )

        # Step 2: Discover URLs (scoped by selected sections)
        discovery_mode, urls = await self._discover_urls(
            url, pattern, use_js,
            include_pattern=section_include,
            exclude_pattern=section_exclude,
        )

        if not urls:
            self.console.print("[yellow]No pages found to extract.[/yellow]")
            return None

        # Step 3: Refine URL list
        urls, include_pattern, exclude_pattern = await self._refine_urls(urls)

        # Merge section-scoping patterns with URL refinement patterns
        include_pattern = self._merge_patterns(section_include, include_pattern)
        exclude_pattern = self._merge_patterns(section_exclude, exclude_pattern)

        if not urls:
            self.console.print("[yellow]No pages selected for extraction.[/yellow]")
            return None

        # Step 4: Output options
        output_mode, output_path = await self._ask_output_options(url)

        # Step 5: Rate-limit / performance settings
        max_concurrent, delay_seconds = await self._ask_rate_limit(len(urls))

        # Step 6: Confirm and extract
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
            max_concurrent=max_concurrent,
            delay_seconds=delay_seconds,
        )

        # Show summary and confirm
        if await self._confirm_extraction(config, len(urls)):
            return config

        return None

    @staticmethod
    def _needs_js_probe(html: str) -> bool:
        """Check if the page likely needs JS rendering for detection.

        Returns True only when JS framework markers are present AND the
        visible body text is thin (< 500 chars), suggesting the content
        hasn't been server-rendered.
        """
        js_markers = [
            "__NEXT_DATA__",
            "__NUXT__",
            "__docusaurus",
            'id="root"',
            'id="app"',
            'id="__next"',
            "window.__INITIAL_STATE__",
        ]
        has_js_marker = any(m in html for m in js_markers)
        if not has_js_marker:
            return False

        # Rough visible-text length: strip tags, collapse whitespace
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return len(text) < 500

    async def _playwright_probe(self, url: str) -> str | None:
        """Fetch the page with a headless browser and return rendered HTML.

        Returns None if Playwright is not installed or the probe fails.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        try:
            self.console.print(
                "[dim]JS framework detected, probing with browser...[/dim]"
            )
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=15000)
                    html = await page.content()
                    return html
                finally:
                    await browser.close()
        except Exception:
            return None

    async def _analyze_site(self, url: str) -> dict | None:
        """Fetch the site and gather basic info, with optional JS probe."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()

                static_html = response.text
                html = static_html
                js_rendered = False

                if self._needs_js_probe(static_html):
                    js_html = await self._playwright_probe(str(response.url))
                    if js_html and len(js_html) > len(static_html) * 1.5:
                        html = js_html
                        js_rendered = True

                return {
                    "url": url,
                    "final_url": str(response.url),
                    "status": response.status_code,
                    "html": html,
                    "static_html": static_html,
                    "js_rendered": js_rendered,
                    "content_length": len(html),
                    "has_trailing_slash": str(response.url).endswith("/"),
                    "headers": dict(response.headers),
                }
        except Exception as e:
            self.console.print(f"[red]Error accessing site: {e}[/red]")
            return None

    @staticmethod
    def _confidence_label(result: DetectionResult) -> str:
        """Return a human-readable confidence label."""
        if result.confidence >= 0.6:
            return "high confidence"
        if result.confidence >= 0.3:
            return "medium confidence"
        return "low confidence"

    async def _detect_or_ask_pattern(self, site_info: dict) -> str | None:
        """Detect site pattern or ask user."""
        html = site_info["html"]
        url = site_info["final_url"]

        # Try auto-detection with two-phase scoring
        headers = site_info.get("headers", {})
        result = PatternRegistry.detect_two_phase(url, html, headers=headers)

        self.console.print()
        if result:
            label = self._confidence_label(result)
            via_js = " (detected via JS-rendered content)" if site_info.get("js_rendered") else ""
            self.console.print(
                f"[green]Detected site type:[/green] {result.pattern.name}"
                f" - {result.pattern.description}"
                f" [{label}]{via_js}"
            )
            use_detected = Confirm.ask("Use this pattern?", default=True)
            if use_detected:
                return result.pattern.name
            # User declined — fall through to manual selection
        else:
            self.console.print(
                "[dim]No known site pattern detected — using generic extraction.[/dim]"
            )
            pick = Confirm.ask("Choose a pattern manually instead?", default=False)
            if not pick:
                return None

        # Show available patterns (only when user wants to pick manually)
        self.console.print("\n[bold]Available site patterns:[/bold]")
        patterns = PatternRegistry.list_patterns()

        table = Table(show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("JS", justify="center")

        table.add_row("0", "none", "No preset - use generic extraction", "-")
        for i, p in enumerate(patterns, 1):
            table.add_row(
                str(i), p.name, p.description,
                "Yes" if p.requires_js else "No",
            )

        self.console.print(table)

        choice = IntPrompt.ask(
            "Select a pattern (0 for none)",
            default=0,
            choices=[str(i) for i in range(len(patterns) + 1)]
        )

        if choice == 0:
            return None
        return patterns[choice - 1].name

    async def _ask_js_rendering(self, site_info: dict, pattern: str | None) -> bool:
        """Determine if JavaScript rendering is needed."""
        self.console.print()

        # If we already rendered with JS during the probe, default to enabled
        if site_info.get("js_rendered"):
            self.console.print(
                "[yellow]This site required JavaScript rendering for detection.[/yellow]"
            )
            return Confirm.ask("Enable JavaScript rendering?", default=True)

        # Check if pattern explicitly requires JS
        if pattern:
            p = PatternRegistry.get(pattern)
            if p and p.requires_js:
                self.console.print(
                    f"[dim]Pattern '{pattern}' requires JavaScript rendering.[/dim]"
                )
                return Confirm.ask("Enable JavaScript rendering?", default=True)
            if p and not p.requires_js:
                self.console.print(
                    f"[dim]Pattern '{pattern}' doesn't require JavaScript rendering.[/dim]"
                )
                return Confirm.ask("Enable JavaScript rendering anyway?", default=False)

        # Check for signs of JS-rendered content in the static HTML
        html = site_info.get("static_html") or site_info["html"]
        js_indicators = [
            "__NEXT_DATA__",
            "__NUXT__",
            "window.__INITIAL_STATE__",
            "react-root",
            'id="app"',
            'id="root"',
            "<noscript>",
        ]

        seems_js = any(indicator in html for indicator in js_indicators)

        if seems_js:
            self.console.print("[yellow]This site appears to use JavaScript rendering.[/yellow]")
            return Confirm.ask("Enable JavaScript rendering?", default=True)
        else:
            self.console.print("[dim]Site appears to be statically rendered.[/dim]")
            return Confirm.ask("Enable JavaScript rendering?", default=False)

    def _analyze_url_groups(self, urls: list[DiscoveredURL]) -> list[_PathGroup]:
        """Group URLs by first 3 path segments, returning PathGroup objects."""
        groups_map: dict[str, list[DiscoveredURL]] = defaultdict(list)

        for discovered in urls:
            parsed = urlparse(discovered.url)
            path = parsed.path.strip("/")
            if path:
                segments = path.split("/")
                depth = min(len(segments), 3)
                prefix = "/" + "/".join(segments[:depth]) + "/"
                groups_map[prefix].append(discovered)
            else:
                groups_map["/"].append(discovered)

        # Sort by count descending (same as most_common)
        sorted_patterns = sorted(groups_map.keys(), key=lambda k: len(groups_map[k]), reverse=True)
        return [_PathGroup(pattern=p, urls=groups_map[p]) for p in sorted_patterns]

    @staticmethod
    def _version_sort_key(segment: str) -> tuple[int, ...]:
        """Return a sort key for a version segment. Higher = newer."""
        lower = segment.lower()

        special: dict[str, tuple[int, ...]] = {
            "latest": (100,), "stable": (100,), "current": (100,),
            "unstable": (99,), "nightly": (99,), "next": (99,), "canary": (99,),
            "beta": (98,), "alpha": (97,),
        }
        if lower in special:
            return special[lower]

        # rc<N>
        rc_match = re.match(r"^rc(\d+)$", lower)
        if rc_match:
            return (96, int(rc_match.group(1)))

        # Numeric version: strip leading 'v', parse dotted parts
        ver = lower.lstrip("v")
        try:
            parts = tuple(int(x) for x in ver.split("."))
            return parts
        except ValueError:
            return (-1,)

    @staticmethod
    def _is_stable_version(segment: str) -> bool:
        """Return True if the version segment represents a stable release.

        Stable = numeric versions (e.g. '2.13', 'v1') or 'latest'/'stable'/'current'.
        Pre-release = 'unstable', 'nightly', 'canary', 'next', 'beta', 'alpha', 'rc*'.
        """
        lower = segment.lower()
        if lower in ("latest", "stable", "current"):
            return True
        if lower in ("unstable", "nightly", "next", "canary", "beta", "alpha"):
            return False
        if re.match(r"^rc\d*$", lower):
            return False
        # Numeric version → stable
        ver = lower.lstrip("v")
        try:
            tuple(int(x) for x in ver.split("."))
            return True
        except ValueError:
            return False

    def _detect_version_clusters(
        self, groups: list[_PathGroup]
    ) -> list[tuple[str, list[int]]]:
        """Find groups that are version variants of the same base path.

        Returns list of (base_pattern, [group_indices]) for clusters with ≥3
        version-like members. Sorted by total page count descending.
        """
        # Map parent_pattern → [(group_index, last_segment)]
        parent_children: dict[str, list[tuple[int, str]]] = defaultdict(list)

        for i, group in enumerate(groups):
            trimmed = group.pattern.strip("/")
            if "/" not in trimmed:
                continue
            parts = trimmed.rsplit("/", 1)
            parent = "/" + parts[0] + "/"
            last_seg = parts[1]
            parent_children[parent].append((i, last_seg))

        clusters: list[tuple[str, list[int]]] = []
        for parent, children in parent_children.items():
            if len(children) < 3:
                continue
            version_members = [
                (idx, seg) for idx, seg in children if _VERSION_RE.match(seg)
            ]
            if len(version_members) < 3:
                continue
            # ≥50% must be version-like
            if len(version_members) < len(children) * 0.5:
                continue
            indices = [idx for idx, _ in version_members]
            clusters.append((parent, indices))

        # Sort clusters by total page count descending
        clusters.sort(
            key=lambda c: sum(len(groups[i].urls) for i in c[1]),
            reverse=True,
        )
        return clusters

    def _build_display_rows(
        self,
        groups: list[_PathGroup],
        clusters: list[tuple[str, list[int]]],
    ) -> list[_DisplayRow]:
        """Build display rows, collapsing version clusters and sibling groups."""
        clustered_indices: set[int] = set()
        rows: list[_DisplayRow] = []

        # Phase 1: Version clusters
        for base_pattern, indices in clusters:
            clustered_indices.update(indices)
            total = sum(len(groups[i].urls) for i in indices)

            # Build sorted version label list
            version_labels: list[tuple[tuple[int, ...], str]] = []
            for i in indices:
                seg = groups[i].pattern.strip("/").rsplit("/", 1)[-1]
                version_labels.append((self._version_sort_key(seg), seg))
            version_labels.sort(reverse=True)
            labels = [seg for _, seg in version_labels]

            if len(labels) > 8:
                detail = ", ".join(labels[:8]) + ", ..."
            else:
                detail = ", ".join(labels)

            rows.append(_DisplayRow(
                label=f"{base_pattern}* ({len(indices)} versions)",
                group_indices=indices,
                total_pages=total,
                detail=detail,
                is_cluster=True,
            ))

        # Phase 2: Collapse remaining sibling groups sharing a parent (≥5 siblings)
        remaining: dict[str, list[int]] = defaultdict(list)
        for i, group in enumerate(groups):
            if i in clustered_indices:
                continue
            trimmed = group.pattern.strip("/")
            if "/" in trimmed:
                parent = "/" + trimmed.rsplit("/", 1)[0] + "/"
            else:
                parent = "/"
            remaining[parent].append(i)

        sibling_collapsed: set[int] = set()
        for parent, indices in remaining.items():
            if len(indices) >= 5:
                sibling_collapsed.update(indices)
                total = sum(len(groups[i].urls) for i in indices)
                rows.append(_DisplayRow(
                    label=f"{parent}* ({len(indices)} subgroups)",
                    group_indices=indices,
                    total_pages=total,
                    is_cluster=True,
                ))

        # Phase 3: Remaining uncollapsed singletons
        for i, group in enumerate(groups):
            if i not in clustered_indices and i not in sibling_collapsed:
                rows.append(_DisplayRow(
                    label=group.pattern,
                    group_indices=[i],
                    total_pages=len(group.urls),
                ))

        # Sort by page count descending
        rows.sort(key=lambda r: r.total_pages, reverse=True)
        return rows

    def _display_groups_table(
        self,
        rows: list[_DisplayRow],
        groups: list[_PathGroup],
        display_limit: int = 25,
    ) -> None:
        """Render the numbered group table with inclusion status."""
        total_urls = sum(len(g.urls) for g in groups)
        included_count = sum(len(g.urls) for g in groups if g.included)
        excluded_count = total_urls - included_count

        self.console.print("\n[bold]URL path groups:[/bold]")
        table = Table(show_header=True, header_style="dim")
        table.add_column("#", style="dim", width=4)
        table.add_column("Path Pattern", style="cyan")
        table.add_column("Pages", justify="right")
        table.add_column("Status", justify="center")

        visible_rows = rows[:display_limit]
        for i, row in enumerate(visible_rows):
            # Determine status from member groups
            member_included = [groups[gi].included for gi in row.group_indices]
            if all(member_included):
                status = "[green]included[/green]"
            elif not any(member_included):
                status = "[red]EXCLUDED[/red]"
            else:
                status = "[yellow]partial[/yellow]"

            label = row.label
            if row.detail:
                label += f"\n[dim]  {row.detail}[/dim]"

            table.add_row(str(i + 1), label, str(row.total_pages), status)

        self.console.print(table)

        if len(rows) > display_limit:
            overflow_rows = rows[display_limit:]
            overflow_count = len(overflow_rows)
            overflow_pages = sum(r.total_pages for r in overflow_rows)
            self.console.print(
                f"[dim]  ... and {overflow_count} more groups"
                f" ({overflow_pages} pages, all included)[/dim]"
            )

        self.console.print(
            f"\n  [green]{included_count} pages included[/green]"
            f"  [dim]|[/dim]  [red]{excluded_count} pages excluded[/red]"
            f"  [dim]|[/dim]  {total_urls} total"
        )

    def _generate_smart_suggestions(
        self,
        groups: list[_PathGroup],
        clusters: list[tuple[str, list[int]]],
    ) -> list[_FilterSuggestion]:
        """Generate smart filter suggestions based on version clusters and keywords."""
        suggestions: list[_FilterSuggestion] = []

        # --- Version cluster suggestions ---
        for base_pattern, indices in clusters:
            if len(indices) < 3:
                continue

            # Sort indices by version (newest first)
            sorted_indices = sorted(
                indices,
                key=lambda i: self._version_sort_key(
                    groups[i].pattern.strip("/").rsplit("/", 1)[-1]
                ),
                reverse=True,
            )

            def _label(idx: int) -> str:
                return groups[idx].pattern.strip("/").rsplit("/", 1)[-1]

            # Partition into stable and pre-release, each sorted newest-first
            stable_indices = [
                i for i in sorted_indices if self._is_stable_version(_label(i))
            ]
            prerelease_indices = [
                i for i in sorted_indices if not self._is_stable_version(_label(i))
            ]

            # Detect the primary unversioned sibling — a non-version direct child
            # of the same parent with significant page count (e.g. "rest-api" next
            # to versioned siblings "2.13", "2.12", …). This is likely the "current"
            # unversioned API docs.
            cluster_set = set(indices)
            avg_pages = sum(len(groups[i].urls) for i in indices) / len(indices)
            current_name: str | None = None
            best_sibling_pages = 0
            for i, g in enumerate(groups):
                if i in cluster_set:
                    continue
                if not g.pattern.startswith(base_pattern):
                    continue
                suffix = g.pattern[len(base_pattern):].strip("/")
                if not suffix or "/" in suffix or _VERSION_RE.match(suffix):
                    continue
                pg = len(g.urls)
                if pg >= 10 and pg >= avg_pages * 0.25 and pg > best_sibling_pages:
                    current_name = suffix
                    best_sibling_pages = pg

            best_idx = stable_indices[0] if stable_indices else sorted_indices[0]
            best_label = _label(best_idx)

            if current_name:
                # --- Suggestions when an unversioned "current" sibling exists ---

                # 1. "Only <current> — exclude all versioned"
                all_pages = sum(len(groups[i].urls) for i in indices)
                suggestions.append(_FilterSuggestion(
                    label=(
                        f"Only {current_name} (current) in {base_pattern}"
                        f" — exclude all {len(indices)} versioned"
                    ),
                    action="exclude",
                    target_indices=list(indices),
                    page_count=all_pages,
                ))

                # 2. "Keep <current> + latest stable"
                exclude_all_but_one = [i for i in sorted_indices if i != best_idx]
                suggestions.append(_FilterSuggestion(
                    label=(
                        f"Keep {current_name} + latest stable"
                        f" ({best_label}) in {base_pattern}"
                    ),
                    action="exclude",
                    target_indices=exclude_all_but_one,
                    page_count=sum(
                        len(groups[i].urls) for i in exclude_all_but_one
                    ),
                ))

                # 3. "Keep <current> + latest 2 stable" (if ≥5 versions)
                if len(indices) >= 5:
                    if len(stable_indices) >= 2:
                        keep = stable_indices[:2]
                    else:
                        keep = sorted_indices[:2]
                    keep_set = set(keep)
                    exclude_indices = [
                        i for i in sorted_indices if i not in keep_set
                    ]
                    keep_labels = [_label(i) for i in keep]
                    suggestions.append(_FilterSuggestion(
                        label=(
                            f"Keep {current_name} + {' + '.join(keep_labels)}"
                            f" in {base_pattern}"
                        ),
                        action="exclude",
                        target_indices=exclude_indices,
                        page_count=sum(
                            len(groups[i].urls) for i in exclude_indices
                        ),
                    ))
            else:
                # --- Suggestions without an unversioned sibling ---
                qualifier = (
                    "stable " if stable_indices and prerelease_indices else ""
                )

                # 1. "Only latest [stable] version"
                exclude_all_but_one = [i for i in sorted_indices if i != best_idx]
                suggestions.append(_FilterSuggestion(
                    label=(
                        f"Only latest {qualifier}API version"
                        f" ({best_label}) in {base_pattern}"
                    ),
                    action="exclude",
                    target_indices=exclude_all_but_one,
                    page_count=sum(
                        len(groups[i].urls) for i in exclude_all_but_one
                    ),
                ))

                # 2. "Keep latest 2 [stable]" (if ≥5 versions)
                if len(indices) >= 5:
                    if len(stable_indices) >= 2:
                        keep = stable_indices[:2]
                        keep_qualifier = "stable "
                    else:
                        keep = sorted_indices[:2]
                        keep_qualifier = ""
                    keep_set = set(keep)
                    exclude_indices = [
                        i for i in sorted_indices if i not in keep_set
                    ]
                    keep_labels = [_label(i) for i in keep]
                    suggestions.append(_FilterSuggestion(
                        label=(
                            f"Exclude old versions in {base_pattern}"
                            f" (keep {keep_qualifier}"
                            f"{' + '.join(keep_labels)})"
                        ),
                        action="exclude",
                        target_indices=exclude_indices,
                        page_count=sum(
                            len(groups[i].urls) for i in exclude_indices
                        ),
                    ))

                # 3. "Exclude all versions"
                all_pages = sum(len(groups[i].urls) for i in indices)
                suggestions.append(_FilterSuggestion(
                    label=f"Exclude all versions in {base_pattern}",
                    action="exclude",
                    target_indices=list(indices),
                    page_count=all_pages,
                ))

        # --- Keyword-based suggestions ---
        exclude_keywords = {
            "blog", "posts", "news", "changelog", "releases", "community",
            "forum", "examples", "demos", "search", "tags", "category",
        }
        include_keywords = {
            "api", "reference", "guide", "guides", "tutorial", "tutorials",
            "getting-started", "quickstart", "sdk",
        }

        total_pages = sum(len(g.urls) for g in groups)

        # Aggregate exclude suggestions by keyword
        exclude_by_keyword: dict[str, list[int]] = defaultdict(list)
        for i, group in enumerate(groups):
            segments = {s.lower() for s in group.pattern.strip("/").split("/")}
            matched = segments & exclude_keywords
            if matched:
                keyword = sorted(matched)[0]
                exclude_by_keyword[keyword].append(i)

        for keyword in sorted(exclude_by_keyword):
            indices = exclude_by_keyword[keyword]
            page_count = sum(len(groups[i].urls) for i in indices)
            if page_count < total_pages * 0.5:
                if len(indices) == 1:
                    label = f"Exclude {keyword} ({groups[indices[0]].pattern})"
                else:
                    label = f"Exclude {keyword} ({len(indices)} groups)"
                suggestions.append(_FilterSuggestion(
                    label=label,
                    action="exclude",
                    target_indices=indices,
                    page_count=page_count,
                ))

        for keyword in sorted(include_keywords):
            matching_indices = []
            matching_count = 0
            for i, group in enumerate(groups):
                segments = {s.lower() for s in group.pattern.strip("/").split("/")}
                if keyword in segments:
                    matching_indices.append(i)
                    matching_count += len(group.urls)
            if matching_indices and matching_count >= total_pages * 0.1:
                suggestions.append(_FilterSuggestion(
                    label=f"Only {keyword} docs",
                    action="include_only",
                    target_indices=matching_indices,
                    page_count=matching_count,
                ))

        return suggestions[:6]

    def _show_suggestions(self, suggestions: list[_FilterSuggestion]) -> None:
        """Display the suggestion menu."""
        self.console.print("\n[bold]Smart suggestions:[/bold]")
        letters = string.ascii_uppercase
        for idx, s in enumerate(suggestions):
            letter = letters[idx]
            action_label = "exclude" if s.action == "exclude" else "include only"
            self.console.print(
                f"  [cyan][{letter}][/cyan] {s.label} — {s.page_count} pages ({action_label})"
            )

    def _prompt_and_apply_suggestion(
        self, groups: list[_PathGroup], suggestions: list[_FilterSuggestion]
    ) -> bool:
        """Prompt user to pick a suggestion and apply it. Returns True if applied."""
        choice = Prompt.ask(
            "Apply a suggestion (letter) or press Enter to skip",
            default="",
        )
        return self._apply_suggestion_choice(groups, suggestions, choice)

    def _apply_suggestion_choice(
        self,
        groups: list[_PathGroup],
        suggestions: list[_FilterSuggestion],
        choice: str,
    ) -> bool:
        """Apply a letter-keyed suggestion. Returns True if applied."""
        choice = choice.strip().upper()
        if not choice:
            return False

        letters = string.ascii_uppercase
        idx = letters.find(choice)
        if idx < 0 or idx >= len(suggestions):
            self.console.print("[yellow]Invalid choice.[/yellow]")
            return False

        suggestion = suggestions[idx]
        if suggestion.action == "exclude":
            for i in suggestion.target_indices:
                groups[i].included = False
            excluded = sum(len(groups[i].urls) for i in suggestion.target_indices)
            self.console.print(f"[green]Excluded {excluded} pages[/green]")
        elif suggestion.action == "include_only":
            target_set = set(suggestion.target_indices)
            for i, group in enumerate(groups):
                group.included = i in target_set
            kept = sum(len(groups[i].urls) for i in suggestion.target_indices)
            self.console.print(f"[green]Kept {kept} pages, excluded the rest[/green]")
        return True

    def _parse_group_selection(self, input_str: str, max_groups: int) -> list[int]:
        """Parse '1,3,5' or '1-3,5' into 0-based indices."""
        indices: list[int] = []
        for part in input_str.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                bounds = part.split("-", 1)
                try:
                    start = int(bounds[0])
                    end = int(bounds[1])
                    for n in range(start, end + 1):
                        if 1 <= n <= max_groups:
                            indices.append(n - 1)
                except ValueError:
                    self.console.print(f"[yellow]Invalid range: '{part}'[/yellow]")
            else:
                try:
                    n = int(part)
                    if 1 <= n <= max_groups:
                        indices.append(n - 1)
                    else:
                        self.console.print(
                            f"[yellow]Group {n} out of range (1-{max_groups})[/yellow]"
                        )
                except ValueError:
                    self.console.print(f"[yellow]Invalid number: '{part}'[/yellow]")
        return indices

    def _groups_to_regex(
        self, groups: list[_PathGroup]
    ) -> tuple[str | None, str | None]:
        """Convert group toggle states to include/exclude regex patterns.

        Picks whichever direction (include vs exclude) produces the shorter pattern.
        """
        included = [g for g in groups if g.included]
        excluded = [g for g in groups if not g.included]

        if not excluded:
            return None, None
        if not included:
            # All excluded — express as exclude pattern
            parts = [re.escape(g.pattern.rstrip("/")) for g in excluded]
            return None, "(" + "|".join(parts) + ")"

        # Pick the shorter direction
        include_parts = [re.escape(g.pattern.rstrip("/")) for g in included]
        exclude_parts = [re.escape(g.pattern.rstrip("/")) for g in excluded]

        include_regex = "(" + "|".join(include_parts) + ")"
        exclude_regex = "(" + "|".join(exclude_parts) + ")"

        if len(exclude_parts) <= len(include_parts):
            return None, exclude_regex
        else:
            return include_regex, None

    @staticmethod
    def _merge_patterns(
        group_pat: str | None, user_pat: str | None
    ) -> str | None:
        """Combine a group-derived pattern with a user-typed pattern using OR."""
        if group_pat and user_pat:
            return f"({group_pat}|{user_pat})"
        return group_pat or user_pat

    def _ask_regex_filters(self) -> tuple[str | None, str | None]:
        """Prompt user for include/exclude regex patterns."""
        self.console.print(
            "\n[dim]Enter regex patterns (or leave blank to skip)[/dim]"
        )
        self.console.print(
            "[dim]Tip: Use patterns like '/docs/api'"
            " to match URLs containing that path[/dim]"
        )

        include_pattern: str | None = None
        exclude_pattern: str | None = None

        include_input = Prompt.ask("Include pattern (only URLs matching this)", default="")
        if include_input.strip():
            try:
                re.compile(include_input.strip())
                include_pattern = include_input.strip()
            except re.error as e:
                self.console.print(f"[red]Invalid include pattern: {e}[/red]")

        exclude_input = Prompt.ask("Exclude pattern (remove URLs matching this)", default="")
        if exclude_input.strip():
            try:
                re.compile(exclude_input.strip())
                exclude_pattern = exclude_input.strip()
            except re.error as e:
                self.console.print(f"[red]Invalid exclude pattern: {e}[/red]")

        return include_pattern, exclude_pattern

    @staticmethod
    def _apply_filters(
        urls: list[DiscoveredURL],
        include_pattern: str | None,
        exclude_pattern: str | None,
    ) -> list[DiscoveredURL]:
        """Apply include/exclude regex patterns to a URL list."""
        filtered = urls
        if include_pattern:
            include_re = re.compile(include_pattern)
            filtered = [u for u in filtered if include_re.search(u.url)]
        if exclude_pattern:
            exclude_re = re.compile(exclude_pattern)
            filtered = [u for u in filtered if not exclude_re.search(u.url)]
        return filtered

    def _show_sample_urls(self, urls: list[DiscoveredURL], limit: int = 10) -> None:
        """Show a sample of URLs."""
        self.console.print("\n[dim]Sample URLs:[/dim]")
        for u in urls[:limit]:
            self.console.print(f"  • {u.url}")
        if len(urls) > limit:
            self.console.print(f"  [dim]... and {len(urls) - limit} more[/dim]")

    def _extract_url_category(self, url: str, max_len: int = 30) -> str:
        """Extract a category/section name from URL path for display.

        Examples:
            https://example.com/docs/api/auth → docs/api/auth
            https://example.com/help/en/articles/123-title → articles
            https://example.com/ → /
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path.strip("/")

        if not path:
            return "/"

        # Split path and take meaningful segments
        segments = path.split("/")

        # Skip common prefixes like language codes
        skip_prefixes = {"en", "es", "de", "fr", "ja", "zh", "pt", "docs", "help"}
        filtered = [s for s in segments if s.lower() not in skip_prefixes]

        if not filtered:
            filtered = segments  # Fall back to original if all filtered out

        # Take first 1-2 meaningful segments
        category = "/".join(filtered[:2])

        # Truncate if too long
        if len(category) > max_len:
            category = category[: max_len - 1] + "…"

        return category

    # ------------------------------------------------------------------
    # Section scanning & selection
    # ------------------------------------------------------------------

    async def _scan_site_structure(
        self,
        site_info: dict,
        pattern: str | None,
        use_js: bool,
    ) -> tuple[str | None, str | None]:
        """Scan nav structure, present section choices, return (include, exclude) patterns."""
        self.console.print("  Scanning site structure...")

        pattern_obj = PatternRegistry.get(pattern) if pattern else None
        scanner = NavScanner(site_info["final_url"], pattern_obj)
        structure = scanner.scan(site_info["html"])

        # Heuristic: if nav elements exist but have no links, try JS probe
        if not structure.sections and use_js and not site_info.get("js_rendered"):
            js_html = await self._playwright_probe(site_info["final_url"])
            if js_html:
                structure = scanner.scan(js_html)

        if not structure.sections:
            self.console.print(
                "[dim]No distinct sections detected in navigation. "
                "Skipping section selection.[/dim]"
            )
            return None, None

        # Quick sitemap probe for page count estimates
        structure = await self._enrich_section_counts(
            scanner, structure, site_info["final_url"]
        )

        # Auto-expand large or few sections into sub-sections
        structure = auto_expand_sections(structure)

        if len(structure.sections) == 1:
            s = structure.sections[0]
            # If the single section has sub-sections, still show the UI
            if s.sub_sections:
                self.console.print(
                    f"[dim]Single section detected: {s.label} ({s.path_prefix})"
                    f" with {len(s.sub_sections)} sub-sections.[/dim]"
                )
            else:
                self.console.print(
                    f"[dim]Single section detected: {s.label} ({s.path_prefix}). "
                    f"Proceeding with full site.[/dim]"
                )
                return None, None

        # Show section selection UI
        return await self._section_selection_ui(structure)

    async def _enrich_section_counts(
        self,
        scanner: NavScanner,
        structure: SiteStructure,
        url: str,
    ) -> SiteStructure:
        """Do a quick sitemap fetch to estimate page counts per section."""
        try:
            config = DiscoveryConfig(mode=DiscoveryMode.SITEMAP, max_pages=0)
            discoverer: BaseDiscoverer = SitemapDiscoverer(url, config)
            sitemap_urls: list[str] = []
            async for discovered in discoverer.discover():
                sitemap_urls.append(discovered.url)
                if len(sitemap_urls) >= 5000:
                    break
            if sitemap_urls:
                structure = scanner.enrich_with_sitemap(structure, sitemap_urls)
        except Exception:
            pass
        return structure

    _SUB_DISPLAY_LIMIT = 10

    def _display_sections_table(
        self, sections: list[NavSection], *, expand_section: int | None = None,
    ) -> None:
        """Render the section selection table with indented sub-sections.

        Args:
            expand_section: If set, show all sub-sections for this 0-based
                section index instead of truncating at ``_SUB_DISPLAY_LIMIT``.
        """
        table = Table(show_header=True, header_style="dim")
        table.add_column("#", style="dim", width=6)
        table.add_column("Section", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Est. Pages", justify="right")
        table.add_column("Status", justify="center")

        total_est = 0
        for i, s in enumerate(sections):
            pages_str = str(s.estimated_pages) if s.estimated_pages else "?"
            if s.estimated_pages:
                total_est += s.estimated_pages
            status = "[green]included[/green]" if s.selected else "[red]EXCLUDED[/red]"
            table.add_row(str(i + 1), s.label, s.path_prefix, pages_str, status)

            # Show sub-sections as indented rows.
            # Always show all selected subs; only truncate excluded ones.
            if i == expand_section:
                visible_indices: set[int] = set(range(len(s.sub_sections)))
            else:
                # Budget: show all selected, fill remaining slots with excluded
                excluded_shown = 0
                excluded_budget = max(
                    0,
                    self._SUB_DISPLAY_LIMIT
                    - sum(1 for sub in s.sub_sections if sub.selected),
                )
                visible_indices = set()
                for j, sub in enumerate(s.sub_sections):
                    if sub.selected:
                        visible_indices.add(j)
                    elif excluded_shown < excluded_budget:
                        visible_indices.add(j)
                        excluded_shown += 1

            for j, sub in enumerate(s.sub_sections):
                if j not in visible_indices:
                    continue
                letter = chr(ord("a") + j)
                sub_num = f"{i + 1}{letter}"
                sub_label = f"  {sub.label}"
                sub_path = f"  {sub.path_prefix}"
                sub_pages = str(sub.estimated_pages) if sub.estimated_pages else "?"
                sub_status = (
                    "[green]included[/green]" if sub.selected
                    else "[red]EXCLUDED[/red]"
                )
                table.add_row(sub_num, sub_label, sub_path, sub_pages, sub_status)

            hidden_subs = [
                sub for j, sub in enumerate(s.sub_sections)
                if j not in visible_indices
            ]
            if hidden_subs:
                overflow_pages = sum(sub.estimated_pages for sub in hidden_subs)
                all_sel = all(sub.selected for sub in hidden_subs)
                none_sel = not any(sub.selected for sub in hidden_subs)
                if all_sel:
                    overflow_status = "[green]included[/green]"
                elif none_sel:
                    overflow_status = "[red]EXCLUDED[/red]"
                else:
                    overflow_status = "[yellow]partial[/yellow]"
                table.add_row(
                    "", f"  [dim]... {len(hidden_subs)} more sub-sections[/dim]",
                    "", str(overflow_pages), overflow_status,
                )

        self.console.print(table)

        # Compute effective selected pages (respecting sub-section selections)
        total_selected = 0
        for s in sections:
            if s.sub_sections:
                total_selected += sum(
                    sub.estimated_pages for sub in s.sub_sections if sub.selected
                )
            elif s.selected and s.estimated_pages:
                total_selected += s.estimated_pages

        included = sum(1 for s in sections if s.selected)
        total_pages_str = f"~{total_selected}" if total_selected else "unknown"
        self.console.print(
            f"\n  [green]{included} sections selected[/green]"
            f"  [dim]|[/dim]  Total: {total_pages_str} pages"
        )

    _SUB_RE = re.compile(r"^(\d+)([a-z])$")

    def _show_section_recommendations(self, sections: list[NavSection]) -> None:
        """Show hints for large sections, dominant sub-sections, and high totals."""
        hints: list[str] = []

        # Compute effective selected pages (respecting sub-section selections)
        total_pages = 0
        for s in sections:
            if s.sub_sections:
                total_pages += sum(
                    sub.estimated_pages for sub in s.sub_sections if sub.selected
                )
            elif s.selected:
                total_pages += s.estimated_pages or 0

        for i, s in enumerate(sections):
            # Effective pages for this section
            if s.sub_sections:
                pages = sum(
                    sub.estimated_pages for sub in s.sub_sections if sub.selected
                )
            else:
                pages = s.estimated_pages or 0

            if pages > 1000 and s.sub_sections:
                hints.append(
                    f"Section '{s.label}' has ~{pages} selected pages"
                    " — sub-sections shown for granular selection."
                )
                # Check for dominant sub-section (skip excluded)
                for j, sub in enumerate(s.sub_sections):
                    if not sub.selected:
                        continue
                    if pages > 0 and sub.estimated_pages / pages > 0.6:
                        pct = int(sub.estimated_pages / pages * 100)
                        letter = chr(ord("a") + j)
                        addr = f"{i + 1}{letter}"
                        hints.append(
                            f"  Sub-section '{sub.label}' contains"
                            f" ~{sub.estimated_pages} pages"
                            f" ({pct}% of '{s.label}')."
                            f" Use 'drill {addr}' to explore further."
                        )

        if total_pages > 2000:
            hints.append(
                f"Selected ~{total_pages} pages total."
                " Consider narrowing to reduce extraction time."
            )

        if hints:
            self.console.print("\n[bold]Recommendations:[/bold]")
            for hint in hints:
                self.console.print(f"  [dim]*[/dim] {hint}")

    def _parse_sub_section_address(
        self, token: str
    ) -> tuple[int, int] | None:
        """Parse '2a' into (section_index, sub_section_index) or None."""
        m = self._SUB_RE.match(token)
        if not m:
            return None
        sec_idx = int(m.group(1)) - 1
        sub_idx = ord(m.group(2)) - ord("a")
        return sec_idx, sub_idx

    def _toggle_parent_cascade(
        self, section: NavSection, new_state: bool
    ) -> None:
        """Set section and all its sub-sections to *new_state*."""
        section.selected = new_state
        for sub in section.sub_sections:
            sub.selected = new_state

    async def _section_selection_ui(
        self,
        structure: SiteStructure,
    ) -> tuple[str | None, str | None]:
        """Interactive section toggle/drill UI. Returns (include_pattern, exclude_pattern)."""
        sections = structure.sections
        sitemap_urls = structure.sitemap_urls
        self._display_sections_table(sections)

        # Version bloat detection and filtering
        if sitemap_urls:
            bloat = self._detect_version_bloat(sections, sitemap_urls)
            if bloat:
                if self._offer_version_filtering(sections, bloat):
                    self._sort_sub_sections(sections)
                    self._display_sections_table(sections)

        has_subs = any(s.sub_sections for s in sections)
        if has_subs:
            self._show_section_recommendations(sections)

        sub_hint = " or sub-section (2a,2c)" if has_subs else ""
        show_hint = ", 'show 2'" if has_subs else ""
        self.console.print(
            f"\n[dim]Commands: toggle by number (1,3){sub_hint}, "
            f"'all', 'none', 'drill N' or 'drill 2a'{show_hint}, 'done'[/dim]"
        )

        while True:
            choice = Prompt.ask("Section select", default="done").strip().lower()

            if choice == "done":
                break
            elif choice == "all":
                for s in sections:
                    self._toggle_parent_cascade(s, True)
                self._display_sections_table(sections)
            elif choice == "none":
                for s in sections:
                    self._toggle_parent_cascade(s, False)
                self._display_sections_table(sections)
            elif choice.startswith("drill"):
                self._drill_into_section(sections, choice, sitemap_urls)
            elif choice.startswith("show"):
                parts = choice.split()
                if len(parts) == 2:
                    try:
                        idx = int(parts[1]) - 1
                        if 0 <= idx < len(sections) and sections[idx].sub_sections:
                            self._display_sections_table(sections, expand_section=idx)
                        elif 0 <= idx < len(sections):
                            self.console.print(
                                "[dim]That section has no sub-sections.[/dim]"
                            )
                        else:
                            self.console.print("[yellow]Section number out of range.[/yellow]")
                    except ValueError:
                        self.console.print("[yellow]Usage: show N (e.g. 'show 2')[/yellow]")
                else:
                    self.console.print("[yellow]Usage: show N (e.g. 'show 2')[/yellow]")
            else:
                changed = False
                for token in choice.replace(",", " ").split():
                    token = token.strip()
                    if not token:
                        continue
                    sub_addr = self._parse_sub_section_address(token)
                    if sub_addr is not None:
                        sec_idx, sub_idx = sub_addr
                        if 0 <= sec_idx < len(sections):
                            subs = sections[sec_idx].sub_sections
                            if 0 <= sub_idx < len(subs):
                                subs[sub_idx].selected = not subs[sub_idx].selected
                                changed = True
                            else:
                                self.console.print(
                                    f"[yellow]No sub-section '{token}'[/yellow]"
                                )
                        else:
                            self.console.print(
                                f"[yellow]Section {sec_idx + 1} out of range[/yellow]"
                            )
                    else:
                        indices = self._parse_group_selection(token, len(sections))
                        if indices:
                            for idx in indices:
                                new_state = not sections[idx].selected
                                self._toggle_parent_cascade(sections[idx], new_state)
                            changed = True
                if changed:
                    self._display_sections_table(sections)

        return self._sections_to_patterns(sections)

    def _drill_into_section(
        self,
        sections: list[NavSection],
        choice: str,
        sitemap_urls: list[str],
    ) -> None:
        """Handle 'drill N' or 'drill Na' to expand sub-sections from sitemap data."""
        parts = choice.split()
        if len(parts) != 2:
            self.console.print(
                "[yellow]Usage: drill N or drill 2a (e.g. 'drill 1', 'drill 2a')[/yellow]"
            )
            return

        target = parts[1]

        if not sitemap_urls:
            self.console.print("[yellow]No sitemap data available for drilling.[/yellow]")
            return

        # Try parsing as sub-section address (e.g. "2a")
        sub_addr = self._parse_sub_section_address(target)
        if sub_addr is not None:
            self._drill_sub_section(sections, sub_addr, sitemap_urls)
            return

        # Otherwise parse as plain section number
        try:
            idx = int(target) - 1
        except ValueError:
            self.console.print("[yellow]Invalid section number.[/yellow]")
            return
        if idx < 0 or idx >= len(sections):
            self.console.print("[yellow]Section number out of range.[/yellow]")
            return

        section = sections[idx]

        # If section already has sub-sections, hint to drill those instead
        if section.sub_sections:
            self.console.print(
                f"[dim]Sub-sections already shown for '{section.label}'."
                f" Use 'drill {idx + 1}a' to explore a specific sub-section.[/dim]"
            )
            return

        # Derive sub-sections from sitemap
        subs = derive_sub_sections(section, sitemap_urls)
        if len(subs) < 2:
            self.console.print(
                f"[dim]No further sub-sections found within '{section.label}'.[/dim]"
            )
            return

        # Attach sub-sections and re-display
        section.sub_sections = subs
        self.console.print(
            f"[green]Found {len(subs)} sub-sections in '{section.label}'.[/green]"
        )
        self._display_sections_table(sections)

    def _drill_sub_section(
        self,
        sections: list[NavSection],
        addr: tuple[int, int],
        sitemap_urls: list[str],
    ) -> None:
        """Expand a sub-section (e.g. 2a) into its children."""
        sec_idx, sub_idx = addr
        if sec_idx < 0 or sec_idx >= len(sections):
            self.console.print("[yellow]Section number out of range.[/yellow]")
            return
        section = sections[sec_idx]
        if sub_idx < 0 or sub_idx >= len(section.sub_sections):
            self.console.print("[yellow]Sub-section not found.[/yellow]")
            return

        sub = section.sub_sections[sub_idx]

        # Create a temporary NavSection to derive deeper sub-sections
        tmp = NavSection(label=sub.label, url="", path_prefix=sub.path_prefix)
        children = derive_sub_sections(tmp, sitemap_urls)
        if len(children) < 2:
            self.console.print(
                f"[dim]No further sub-sections found within '{sub.label}'.[/dim]"
            )
            return

        # Inherit selected state from the replaced sub-section
        for child in children:
            child.selected = sub.selected

        # Replace the single sub-section with its children
        section.sub_sections[sub_idx:sub_idx + 1] = children
        self.console.print(
            f"[green]Expanded '{sub.label}' into {len(children)} sub-sections.[/green]"
        )
        self._display_sections_table(sections)

    def _detect_version_bloat(
        self,
        sections: list[NavSection],
        sitemap_urls: list[str],
    ) -> list[tuple[int, int, list[NavSubSection]]]:
        """Detect sub-sections with heavy version bloat.

        Returns a list of ``(sec_idx, sub_idx, children)`` tuples for each
        sub-section that has ≥3 version-like children making up ≥50% of all
        children, and ≥200 estimated pages.
        """
        results: list[tuple[int, int, list[NavSubSection]]] = []

        for sec_idx, section in enumerate(sections):
            for sub_idx, sub in enumerate(section.sub_sections):
                if (sub.estimated_pages or 0) < 200:
                    continue

                # Derive children with relaxed filters to see everything
                tmp = NavSection(label=sub.label, url="", path_prefix=sub.path_prefix)
                children = derive_sub_sections(
                    tmp, sitemap_urls, max_results=50, min_pages=1,
                )
                if len(children) < 3:
                    continue

                version_count = sum(
                    1 for c in children
                    if _VERSION_RE.match(c.path_prefix.rstrip("/").rsplit("/", 1)[-1])
                )
                if version_count >= 3 and version_count >= len(children) * 0.5:
                    results.append((sec_idx, sub_idx, children))

        return results

    def _offer_version_filtering(
        self,
        sections: list[NavSection],
        bloat: list[tuple[int, int, list[NavSubSection]]],
    ) -> bool:
        """Prompt user to filter version bloat in sub-sections.

        Processes entries in **reverse index order** to avoid index shift issues
        when replacing sub-sections with their children.

        Returns True if any changes were made.
        """
        changed = False

        # Sort by (sec_idx, sub_idx) descending so replacements don't shift indices
        for sec_idx, sub_idx, children in sorted(bloat, key=lambda t: (t[0], t[1]), reverse=True):
            section = sections[sec_idx]
            sub = section.sub_sections[sub_idx]

            # Partition children into version vs non-version
            version_children: list[tuple[tuple[int, ...], NavSubSection]] = []
            non_version_children: list[NavSubSection] = []
            for child in children:
                seg = child.path_prefix.rstrip("/").rsplit("/", 1)[-1]
                if _VERSION_RE.match(seg):
                    version_children.append((self._version_sort_key(seg), child))
                else:
                    non_version_children.append(child)

            # Sort versions newest-first
            version_children.sort(key=lambda t: t[0], reverse=True)

            # Find latest stable version
            latest_stable: NavSubSection | None = None
            for _key, vc in version_children:
                seg = vc.path_prefix.rstrip("/").rsplit("/", 1)[-1]
                if self._is_stable_version(seg):
                    latest_stable = vc
                    break

            # Build the prompt
            version_pages = sum(vc.estimated_pages for _, vc in version_children)
            non_version_label = (
                " + ".join(c.label for c in non_version_children[:3])
                if non_version_children else None
            )
            latest_label = (
                latest_stable.path_prefix.rstrip("/").rsplit("/", 1)[-1]
                if latest_stable else None
            )

            # Description line
            self.console.print()
            self.console.print(
                f"[yellow]'{sub.label}' has {len(version_children)} API versions"
                f" ({version_pages} pages).[/yellow]"
            )

            # Build keep description
            keep_parts: list[str] = []
            if non_version_label:
                keep_parts.append(non_version_label)
            if latest_label:
                keep_parts.append(latest_label)
            keep_desc = " + ".join(keep_parts) if keep_parts else "non-version sections"

            accepted = Confirm.ask(
                f"Keep only {keep_desc}, exclude old versions?",
                default=True,
            )
            if not accepted:
                continue

            # Apply: mark non-version + latest stable as selected, old versions as excluded
            for child in non_version_children:
                child.selected = sub.selected  # inherit parent's state
            for _key, vc in version_children:
                if latest_stable and vc is latest_stable:
                    vc.selected = sub.selected
                else:
                    vc.selected = False

            # Build replacement list: non-version first, then all versions (selected order later)
            replacement = non_version_children + [vc for _, vc in version_children]

            # Replace the sub-section with its expanded children
            section.sub_sections[sub_idx:sub_idx + 1] = replacement
            changed = True

        return changed

    @staticmethod
    def _sort_sub_sections(sections: list[NavSection]) -> None:
        """Sort each section's sub-sections: selected first (by pages desc), then excluded."""
        for section in sections:
            if section.sub_sections:
                section.sub_sections.sort(
                    key=lambda s: (not s.selected, -(s.estimated_pages or 0))
                )

    @staticmethod
    def _sections_to_patterns(
        sections: list[NavSection],
    ) -> tuple[str | None, str | None]:
        """Convert selected sections into an include_pattern regex.

        When a parent has sub-sections and not all are selected, emit include
        patterns from the selected sub-section prefixes instead of the parent's.
        When all sub-sections (or no sub-sections exist) are selected, use the
        parent prefix as before.
        """
        all_selected = all(s.selected for s in sections)
        all_subs_default = all(
            all(sub.selected for sub in s.sub_sections)
            for s in sections
            if s.sub_sections
        )
        if all_selected and all_subs_default:
            return None, None  # Nothing filtered

        none_selected = not any(s.selected for s in sections)
        if none_selected:
            # All excluded — check if any sub-section is still selected
            any_sub = any(
                sub.selected
                for s in sections
                for sub in s.sub_sections
            )
            if not any_sub:
                return None, None

        prefixes: list[str] = []
        for s in sections:
            if not s.selected and not s.sub_sections:
                continue
            if not s.path_prefix or s.path_prefix == "/":
                continue

            if s.sub_sections:
                selected_subs = [sub for sub in s.sub_sections if sub.selected]
                all_subs_on = len(selected_subs) == len(s.sub_sections)
                if s.selected and all_subs_on:
                    # Parent selected, all subs on → use parent prefix
                    prefixes.append(re.escape(s.path_prefix.rstrip("/")))
                elif selected_subs:
                    # Partial sub-selection → emit each selected sub-section
                    for sub in selected_subs:
                        prefixes.append(re.escape(sub.path_prefix.rstrip("/")))
                # else: nothing selected for this section
            elif s.selected:
                prefixes.append(re.escape(s.path_prefix.rstrip("/")))

        if not prefixes:
            return None, None

        include = "(" + "|".join(p + "(/|$)" for p in prefixes) + ")"
        return include, None

    async def _discover_urls(
        self,
        url: str,
        pattern: str | None,
        use_js: bool,
        include_pattern: str | None = None,
        exclude_pattern: str | None = None,
    ) -> tuple[DiscoveryMode, list[DiscoveredURL]]:
        """Discover URLs using sitemap or crawling."""
        self.console.print()
        self.console.print("[bold]Step 2:[/bold] Discovering pages...")

        self.console.print("  Checking for sitemap...")
        config = DiscoveryConfig(
            mode=DiscoveryMode.SITEMAP,
            max_pages=0,
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
        )
        discoverer: BaseDiscoverer = SitemapDiscoverer(url, config)

        urls = []
        try:
            sitemap_start = _time.monotonic()
            with self.console.status("Reading sitemap...") as status:
                async for discovered in discoverer.discover():
                    urls.append(discovered)
                    if len(urls) % 50 == 0:
                        elapsed = _time.monotonic() - sitemap_start
                        rate = len(urls) / elapsed if elapsed > 0 else 0
                        status.update(
                            f"Reading sitemap... found {len(urls)} pages ({rate:.1f}/sec)"
                        )
        except Exception:
            pass

        if urls:
            self.console.print(f"  [green]Found {len(urls)} pages via sitemap[/green]")
            use_sitemap = Confirm.ask("Use sitemap discovery?", default=True)
            if use_sitemap:
                return DiscoveryMode.SITEMAP, urls

        self.console.print("\n  Sitemap not available or not selected. Using crawl discovery...")

        max_depth = IntPrompt.ask("Maximum crawl depth", default=3)
        max_pages = IntPrompt.ask("Maximum pages to discover (0 = unlimited)", default=100)

        config = DiscoveryConfig(
            mode=DiscoveryMode.CRAWL,
            max_depth=max_depth,
            max_pages=max_pages if max_pages > 0 else 0,
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
        )
        discoverer = CrawlerDiscoverer(url, config)

        urls: list[DiscoveredURL] = []
        crawl_start = _time.monotonic()
        current_depth = 0
        depth_categories: set[str] = set()
        depth_start_count = 0

        with self.console.status("Crawling...") as status:
            async for discovered in discoverer.discover():
                urls.append(discovered)

                # Track when we move to a new depth level
                if discovered.depth > current_depth:
                    # Print summary of completed depth
                    if depth_categories:
                        cats = ", ".join(sorted(depth_categories)[:5])
                        if len(depth_categories) > 5:
                            cats += f" (+{len(depth_categories) - 5} more)"
                        depth_count = len(urls) - 1 - depth_start_count
                        self.console.print(
                            f"  [dim]Depth {current_depth}:[/dim] "
                            f"{depth_count} pages — {cats}"
                        )
                    current_depth = discovered.depth
                    depth_categories = set()
                    depth_start_count = len(urls) - 1

                # Collect categories at this depth
                category = self._extract_url_category(discovered.url)
                depth_categories.add(category)

                elapsed = _time.monotonic() - crawl_start
                rate = len(urls) / elapsed if elapsed > 0 else 0
                status.update(
                    f"Crawling depth {current_depth}... "
                    f"found {len(urls)} pages ({rate:.1f}/sec)"
                )

        # Print final depth summary
        if depth_categories:
            cats = ", ".join(sorted(depth_categories)[:5])
            if len(depth_categories) > 5:
                cats += f" (+{len(depth_categories) - 5} more)"
            depth_count = len(urls) - depth_start_count
            self.console.print(
                f"  [dim]Depth {current_depth}:[/dim] "
                f"{depth_count} pages — {cats}"
            )

        self.console.print(f"  [green]Found {len(urls)} pages via crawling[/green]")
        return DiscoveryMode.CRAWL, urls

    async def _refine_urls(
        self, urls: list[DiscoveredURL]
    ) -> tuple[list[DiscoveredURL], str | None, str | None]:
        """Let user review and filter URLs via group toggling, suggestions, or regex."""
        self.console.print()
        self.console.print(f"[bold]Step 3:[/bold] Review discovered URLs ({len(urls)} found)")

        # Show sample URLs
        self._show_sample_urls(urls)

        # Analyze URL groups and detect version clusters
        groups = self._analyze_url_groups(urls)
        clusters = self._detect_version_clusters(groups)
        rows = self._build_display_rows(groups, clusters)

        # Only 1 display row — skip group selection, offer regex only
        if len(rows) <= 1:
            self._display_groups_table(rows, groups)
            include_pattern = None
            exclude_pattern = None
            if Confirm.ask("\nFilter by regex?", default=False):
                include_pattern, exclude_pattern = self._ask_regex_filters()
                if include_pattern or exclude_pattern:
                    urls = self._apply_filters(urls, include_pattern, exclude_pattern)
                    self.console.print(f"[green]After filtering: {len(urls)} pages[/green]")
            return self._apply_page_limit(urls, include_pattern, exclude_pattern)

        # Display groups table
        self._display_groups_table(rows, groups)

        # Generate suggestions (available throughout the toggle loop)
        suggestions: list[_FilterSuggestion] = []
        if len(rows) >= 3:
            suggestions = self._generate_smart_suggestions(groups, clusters)

        # Show suggestions and prompt for initial pick
        if suggestions:
            self._show_suggestions(suggestions)
            if self._prompt_and_apply_suggestion(groups, suggestions):
                self._display_groups_table(rows, groups)

        # Interactive toggle loop
        user_include: str | None = None
        user_exclude: str | None = None
        displayable = min(len(rows), 25)

        has_suggestions = bool(suggestions)
        suggest_hint = ", 'suggest'" if has_suggestions else ""
        self.console.print(
            f"\n[dim]Toggle groups by number (e.g. '4,5,7' or '1-3'), "
            f"'all', 'none'{suggest_hint}, 'regex', or 'done'[/dim]"
        )

        while True:
            choice = Prompt.ask("Toggle", default="done")
            choice = choice.strip().lower()

            if choice == "done":
                # Warn if 0 pages selected
                selected = sum(len(g.urls) for g in groups if g.included)
                if selected == 0:
                    self.console.print(
                        "[red bold]Warning: 0 pages are currently selected![/red bold]"
                    )
                    if not Confirm.ask("Continue with 0 pages?", default=False):
                        continue
                break
            elif choice == "all":
                for g in groups:
                    g.included = True
                self._display_groups_table(rows, groups)
            elif choice == "none":
                for g in groups:
                    g.included = False
                self._display_groups_table(rows, groups)
            elif choice == "suggest" and has_suggestions:
                self._show_suggestions(suggestions)
                if self._prompt_and_apply_suggestion(groups, suggestions):
                    self._display_groups_table(rows, groups)
            elif has_suggestions and len(choice) == 1 and choice.upper() in string.ascii_uppercase:
                # Direct letter input — apply suggestion without showing menu
                if self._apply_suggestion_choice(groups, suggestions, choice):
                    self._display_groups_table(rows, groups)
            elif choice == "regex":
                user_include, user_exclude = self._ask_regex_filters()
                if user_include or user_exclude:
                    preview = self._apply_filters(urls, user_include, user_exclude)
                    self.console.print(
                        f"[dim]Regex would match {len(preview)}/{len(urls)} URLs[/dim]"
                    )
                break
            else:
                row_indices = self._parse_group_selection(choice, displayable)
                if row_indices:
                    for ri in row_indices:
                        row = rows[ri]
                        # Toggle all member groups in this display row
                        member_states = [groups[gi].included for gi in row.group_indices]
                        new_state = not all(member_states)
                        for gi in row.group_indices:
                            groups[gi].included = new_state
                    self._display_groups_table(rows, groups)

        # Convert group toggles to regex patterns
        group_include, group_exclude = self._groups_to_regex(groups)

        # Merge with user-typed regex
        include_pattern = self._merge_patterns(group_include, user_include)
        exclude_pattern = self._merge_patterns(group_exclude, user_exclude)

        # Apply all filters to get the final URL list
        filtered = self._apply_filters(urls, include_pattern, exclude_pattern)
        self.console.print(f"\n[green]After filtering: {len(filtered)} pages[/green]")

        if filtered and len(filtered) != len(urls):
            self._show_sample_urls(filtered)

        return self._apply_page_limit(filtered, include_pattern, exclude_pattern)

    def _apply_page_limit(
        self,
        urls: list[DiscoveredURL],
        include_pattern: str | None,
        exclude_pattern: str | None,
    ) -> tuple[list[DiscoveredURL], str | None, str | None]:
        """Prompt for page limit and return the trimmed list with patterns."""
        self.console.print(f"\n[bold]Pages to extract:[/bold] {len(urls)}")
        max_pages = IntPrompt.ask(
            "How many pages to extract? (0 = all)",
            default=min(len(urls), 100),
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
        self.console.print("  3. JSON - structured JSON with metadata (for RAG pipelines)")
        self.console.print("  4. JSONL - one JSON object per line (for streaming/embeddings)")
        self.console.print("  5. Chunked - token-limited JSONL chunks (for LLM context windows)")

        mode_choice = Prompt.ask(
            "Choose output mode", choices=["1", "2", "3", "4", "5"], default="1"
        )
        mode_map = {
            "1": OutputMode.SINGLE,
            "2": OutputMode.MULTI,
            "3": OutputMode.JSON,
            "4": OutputMode.JSONL,
            "5": OutputMode.CHUNKED,
        }
        output_mode = mode_map[mode_choice]

        # Output path
        parsed = urlparse(url)
        default_name = parsed.netloc.replace(".", "-")

        ext_map = {
            OutputMode.SINGLE: ".md",
            OutputMode.JSON: ".json",
            OutputMode.JSONL: ".jsonl",
            OutputMode.CHUNKED: ".jsonl",
        }
        if output_mode == OutputMode.MULTI:
            default_path = f"output/{default_name}/"
            output_path = Prompt.ask("Output directory", default=default_path)
        else:
            ext = ext_map.get(output_mode, ".md")
            default_path = f"output/{default_name}{ext}"
            output_path = Prompt.ask("Output file", default=default_path)

        return output_mode, Path(output_path)

    async def _ask_rate_limit(self, num_pages: int) -> tuple[int, float]:
        """Ask user about concurrency and request pacing."""
        self.console.print()
        self.console.print("[bold]Step 5:[/bold] Request pacing")

        self.console.print("\n[bold]Speed preset:[/bold]")
        self.console.print("  1. Polite   - 3 concurrent, 0.5s delay  (gentle on the server)")
        self.console.print("  2. Moderate - 5 concurrent, 0.1s delay  (default)")
        self.console.print("  3. Fast     - 10 concurrent, 0.05s delay (for robust servers)")
        self.console.print("  4. Custom")

        choice = Prompt.ask("Choose preset", choices=["1", "2", "3", "4"], default="2")

        if choice == "1":
            return 3, 0.5
        elif choice == "2":
            return 5, 0.1
        elif choice == "3":
            return 10, 0.05
        else:
            max_concurrent = IntPrompt.ask("Max concurrent requests (1-20)", default=5)
            max_concurrent = max(1, min(20, max_concurrent))
            delay_input = Prompt.ask("Delay between requests in seconds (0-60)", default="0.1")
            try:
                delay_seconds = max(0.0, min(60.0, float(delay_input)))
            except ValueError:
                self.console.print("[yellow]Invalid value, using 0.1s[/yellow]")
                delay_seconds = 0.1
            return max_concurrent, delay_seconds

    def _build_config(
        self,
        url: str,
        discovery_mode: DiscoveryMode,
        use_js: bool,
        pattern: str | None,
        include_pattern: str | None,
        exclude_pattern: str | None,
        max_pages: int,
        output_mode: OutputMode,
        output_path: Path,
        max_concurrent: int,
        delay_seconds: float,
    ) -> AppConfig:
        """Build the final configuration."""
        config = AppConfig(
            base_url=url,
            discovery=DiscoveryConfig(
                mode=discovery_mode,
                max_pages=max_pages,
                include_pattern=include_pattern,
                exclude_pattern=exclude_pattern,
            ),
            fetcher=FetcherConfig(use_js=use_js, page_pool_size=min(max_concurrent, 20)),
            extractor=ExtractorConfig(),
            output=OutputConfig(mode=output_mode, path=output_path),
            rate_limit=RateLimitConfig(
                max_concurrent=max_concurrent,
                delay_seconds=delay_seconds,
            ),
            pattern=pattern,
            verbose=False,
        )
        if pattern:
            config = PatternRegistry.apply_to_config(pattern, config)
        return config

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
            f"Concurrency: {config.rate_limit.max_concurrent} requests,"
            f" {config.rate_limit.delay_seconds}s delay\n"
            f"Output: {config.output.path} ({config.output.mode.value} mode)",
            title="Ready to Extract",
            border_style="green"
        ))

        return Confirm.ask("\nProceed with extraction?", default=True)
