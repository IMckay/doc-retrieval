"""NavScanner — discover documentation structure from site navigation."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from doc_retrieval.scanner.models import NavLink, NavSection, NavSubSection, SiteStructure
from doc_retrieval.scanner.parsers import (
    _deduplicate_sections,
    group_links_into_sections,
    parse_generic_nav,
    parse_subsection_links,
    parse_with_selectors,
)

if TYPE_CHECKING:
    from doc_retrieval.patterns.registry import SitePattern


class NavScanner:
    """Scans a page's navigation to discover documentation sections."""

    def __init__(self, base_url: str, pattern: SitePattern | None = None) -> None:
        self.base_url = base_url
        self.pattern = pattern

    def scan(self, html: str) -> SiteStructure:
        """Parse navigation structure from HTML.

        Strategy order:
        1. Pattern-specific selectors (if pattern has nav_selectors)
        2. Generic header/sidebar extraction
        """
        links: list[NavLink] = []
        source = "generic"

        # 1. Try pattern-specific nav selectors
        if self.pattern and self.pattern.nav_selectors:
            links = parse_with_selectors(
                html, self.base_url, self.pattern.nav_selectors
            )
            if links:
                source = "pattern"

        # 2. Fall back to generic extraction
        if not links:
            links = parse_generic_nav(html, self.base_url)
            source = "generic"

        if not links:
            return SiteStructure(source="fallback", raw_nav_links=0)

        raw_count = len(links)
        sections = group_links_into_sections(links)
        sections = _deduplicate_sections(sections)

        return SiteStructure(
            sections=sections,
            source=source,
            raw_nav_links=raw_count,
        )

    def scan_subsections(self, html: str, parent: NavSection) -> list[NavLink]:
        """Parse sub-navigation from a section's root page."""
        return parse_subsection_links(html, self.base_url, parent.path_prefix)

    def enrich_with_sitemap(
        self, structure: SiteStructure, urls: list[str]
    ) -> SiteStructure:
        """Cross-reference sections with sitemap/discovered URLs to estimate page counts."""
        if not structure.sections or not urls:
            return structure

        updated_sections: list[NavSection] = []
        for section in structure.sections:
            prefix = section.path_prefix.rstrip("/")
            count = sum(
                1 for u in urls
                if urlparse(u).path.startswith(prefix)
            )
            updated_sections.append(section.model_copy(
                update={"estimated_pages": count if count > 0 else None}
            ))

        return structure.model_copy(
            update={"sections": updated_sections, "sitemap_urls": urls}
        )


def _humanize_label(segment: str) -> str:
    """Convert a URL path segment to a human-readable label.

    ``api-reference`` → ``Api Reference``, ``getting_started`` → ``Getting Started``.
    """
    return segment.replace("-", " ").replace("_", " ").title()


def derive_sub_sections(
    section: NavSection, sitemap_urls: list[str],
    *, max_results: int = 15, min_pages: int = 3,
) -> list[NavSubSection]:
    """Derive sub-sections for *section* by grouping sitemap URLs by their next path segment.

    Only URLs whose path starts with ``section.path_prefix`` are considered.
    Groups with fewer than *min_pages* pages are dropped as noise. Results are
    capped at *max_results* sub-sections and sorted by page count descending.
    """
    prefix = section.path_prefix.rstrip("/") + "/"
    groups: dict[str, int] = defaultdict(int)

    for url in sitemap_urls:
        path = urlparse(url).path
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix):]
        if not remainder:
            continue
        next_segment = remainder.split("/", 1)[0]
        if next_segment:
            groups[next_segment] += 1

    # Filter out noise (< min_pages pages) and sort by count descending
    filtered = sorted(
        ((seg, count) for seg, count in groups.items() if count >= min_pages),
        key=lambda x: x[1],
        reverse=True,
    )

    # Cap at max_results sub-sections
    filtered = filtered[:max_results]

    return [
        NavSubSection(
            label=_humanize_label(seg),
            path_prefix=prefix + seg + "/",
            estimated_pages=count,
        )
        for seg, count in filtered
    ]


def auto_expand_sections(
    structure: SiteStructure, sitemap_urls: list[str] | None = None
) -> SiteStructure:
    """Attach sub-sections to sections that benefit from finer-grained selection.

    Sub-sections are derived when:
    - There are ≤4 top-level sections, OR
    - Any individual section has >500 estimated pages.

    Sub-sections are only attached if ≥2 are found (a single sub-section adds no value).
    """
    urls = sitemap_urls or structure.sitemap_urls
    if not urls or not structure.sections:
        return structure

    few_sections = len(structure.sections) <= 4
    updated: list[NavSection] = []

    for section in structure.sections:
        pages = section.estimated_pages or 0
        should_expand = few_sections or pages > 500

        if should_expand:
            subs = derive_sub_sections(section, urls)
            if len(subs) >= 2:
                updated.append(section.model_copy(update={"sub_sections": subs}))
                continue

        updated.append(section)

    return structure.model_copy(update={"sections": updated})
