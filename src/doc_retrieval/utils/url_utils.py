"""URL manipulation utilities."""

import re
from urllib.parse import urljoin, urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Normalize a URL by removing fragments and trailing slashes."""
    parsed = urlparse(url)
    # Remove fragment
    normalized = parsed._replace(fragment="")
    # Remove trailing slash from path (except for root)
    path = normalized.path.rstrip("/") if normalized.path != "/" else "/"
    normalized = normalized._replace(path=path)
    return urlunparse(normalized)


def is_same_domain(url1: str, url2: str) -> bool:
    """Check if two URLs are on the same domain."""
    parsed1 = urlparse(url1)
    parsed2 = urlparse(url2)
    return parsed1.netloc.lower() == parsed2.netloc.lower()


def get_base_domain(url: str) -> str:
    """Extract the domain from a URL."""
    return urlparse(url).netloc.lower()


def make_absolute(base_url: str, href: str) -> str:
    """Convert a potentially relative URL to absolute."""
    return urljoin(base_url, href)


def url_to_filename(url: str, base_url: str) -> str:
    """Convert a URL to a safe filename preserving path structure."""
    parsed = urlparse(url)
    base_parsed = urlparse(base_url)

    # Get path relative to base
    path = parsed.path.strip("/")

    if not path:
        path = "index"

    # Clean up path for filesystem
    # Replace problematic characters
    path = re.sub(r"[<>:\"|?*]", "_", path)

    # Ensure .md extension
    if not path.endswith(".md"):
        path = path + ".md"

    return path


def is_doc_url(url: str) -> bool:
    """Check if a URL looks like a documentation page (not an asset)."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Skip common non-doc paths
    skip_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
        ".pdf", ".zip", ".tar", ".gz",
        ".xml", ".json", ".yaml", ".yml",
    }

    for ext in skip_extensions:
        if path.endswith(ext):
            return False

    # Skip common non-doc paths
    skip_paths = {
        "/assets/", "/static/", "/images/", "/img/",
        "/css/", "/js/", "/fonts/",
        "/_next/", "/_nuxt/", "/.well-known/",
    }

    for skip in skip_paths:
        if skip in path:
            return False

    return True
