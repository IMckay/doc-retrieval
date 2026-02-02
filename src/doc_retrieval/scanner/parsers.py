"""Navigation parsing strategies for extracting site structure from HTML."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from doc_retrieval.scanner.models import NavLink, NavSection
from doc_retrieval.utils.url_utils import is_doc_url, is_same_domain

# Paths that are unlikely to be documentation sections.
_SKIP_PATH_KEYWORDS = frozenset({
    "login", "signin", "sign-in", "signup", "sign-up", "register",
    "pricing", "status", "careers", "about", "contact",
    "legal", "privacy", "terms", "tos",
    "blog", "community", "forum", "support",
})


def _is_nav_worthy(url: str, base_url: str) -> bool:
    """Return True if the URL is worth including as a nav section candidate."""
    if not is_same_domain(url, base_url):
        return False
    if not is_doc_url(url):
        return False
    parsed = urlparse(url)
    path = parsed.path.strip("/").lower()
    if not path:
        return False
    segments = path.split("/")
    # Skip if any segment matches a non-doc keyword
    if any(seg in _SKIP_PATH_KEYWORDS for seg in segments):
        return False
    return True


def _extract_links(elements: list[Tag], base_url: str) -> list[NavLink]:
    """Extract NavLink objects from a list of <a> elements."""
    seen: set[str] = set()
    links: list[NavLink] = []
    for el in elements:
        href = el.get("href")
        if not href or not isinstance(href, str):
            continue
        # Skip fragment-only and javascript: links
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        if not _is_nav_worthy(absolute, base_url):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        label = el.get_text(strip=True)
        if not label:
            continue
        path = urlparse(absolute).path
        links.append(NavLink(label=label, url=absolute, path=path))
    return links


def parse_with_selectors(
    html: str, base_url: str, selectors: list[str]
) -> list[NavLink]:
    """Parse navigation links using pattern-specific CSS selectors."""
    soup = BeautifulSoup(html, "html.parser")
    anchors: list[Tag] = []
    seen_elements: set[int] = set()
    for selector in selectors:
        for el in soup.select(selector):
            # selector may target <a> directly or a container
            if el.name == "a":
                if id(el) not in seen_elements:
                    seen_elements.add(id(el))
                    anchors.append(el)
            else:
                for a in el.find_all("a", href=True):
                    if id(a) not in seen_elements:
                        seen_elements.add(id(a))
                        anchors.append(a)
    return _extract_links(anchors, base_url)


def parse_header_nav(html: str, base_url: str) -> list[NavLink]:
    """Parse navigation links from header/navbar elements."""
    soup = BeautifulSoup(html, "html.parser")
    anchors: list[Tag] = []
    seen: set[int] = set()

    # Priority order: header nav a, nav[aria-label] a, [role="navigation"] a
    selectors = [
        "header nav a[href]",
        "header a[href]",
        'nav[aria-label] a[href]',
        '[role="navigation"] a[href]',
    ]
    for selector in selectors:
        for a in soup.select(selector):
            if id(a) not in seen:
                seen.add(id(a))
                anchors.append(a)

    return _extract_links(anchors, base_url)


def parse_sidebar_nav(html: str, base_url: str) -> list[NavLink]:
    """Parse navigation links from sidebar elements."""
    soup = BeautifulSoup(html, "html.parser")
    anchors: list[Tag] = []
    seen: set[int] = set()

    selectors = [
        "aside nav a[href]",
        ".sidebar a[href]",
        '[class*="sidebar"] a[href]',
        '[class*="Sidebar"] a[href]',
    ]
    for selector in selectors:
        for a in soup.select(selector):
            if id(a) not in seen:
                seen.add(id(a))
                anchors.append(a)

    return _extract_links(anchors, base_url)


def _path_prefix(path: str) -> str:
    """Extract the first meaningful path segment as a prefix.

    /docs/api/v1/users -> /docs/
    /api-reference/    -> /api-reference/
    /                  -> /
    """
    path = path.strip("/")
    if not path:
        return "/"
    first_segment = path.split("/")[0]
    return f"/{first_segment}/"


def group_links_into_sections(links: list[NavLink]) -> list[NavSection]:
    """Group flat nav links into sections by their first path segment."""
    if not links:
        return []

    # Group by path prefix
    prefix_groups: dict[str, list[NavLink]] = {}
    for link in links:
        prefix = _path_prefix(link.path)
        prefix_groups.setdefault(prefix, []).append(link)

    sections: list[NavSection] = []
    for prefix, group_links in prefix_groups.items():
        # Use the first link with this prefix as the section representative
        # Prefer the link whose path is exactly the prefix (the "root" of the section)
        root_link = None
        for link in group_links:
            normalized = link.path.rstrip("/") + "/"
            if normalized == prefix:
                root_link = link
                break
        if root_link is None:
            root_link = group_links[0]

        children = [lnk for lnk in group_links if lnk.url != root_link.url]

        sections.append(NavSection(
            label=root_link.label,
            url=root_link.url,
            path_prefix=prefix,
            children=children,
        ))

    return sections


def _deduplicate_sections(sections: list[NavSection]) -> list[NavSection]:
    """Remove duplicate sections by path_prefix, keeping the one with more children."""
    by_prefix: dict[str, NavSection] = {}
    for section in sections:
        key = section.path_prefix
        existing = by_prefix.get(key)
        if existing is None or len(section.children) > len(existing.children):
            by_prefix[key] = section
    return list(by_prefix.values())


def parse_generic_nav(html: str, base_url: str) -> list[NavLink]:
    """Combine header and sidebar parsing as a generic fallback."""
    header_links = parse_header_nav(html, base_url)
    sidebar_links = parse_sidebar_nav(html, base_url)

    # Merge, deduplicating by URL
    seen: set[str] = set()
    merged: list[NavLink] = []
    for link in header_links + sidebar_links:
        if link.url not in seen:
            seen.add(link.url)
            merged.append(link)
    return merged


def parse_subsection_links(html: str, base_url: str, parent_prefix: str) -> list[NavLink]:
    """Parse sub-navigation links from a section's root page.

    Only returns links that are within the parent section's path prefix.
    """
    all_links = parse_generic_nav(html, base_url)
    return [
        link for link in all_links
        if link.path.startswith(parent_prefix.rstrip("/"))
    ]
