"""Data models for site navigation structure."""

from __future__ import annotations

from pydantic import BaseModel


class NavLink(BaseModel):
    """A single navigation link."""

    label: str
    url: str
    path: str = ""


class NavSubSection(BaseModel):
    """A sub-section within a documentation section, derived from sitemap URLs."""

    label: str
    path_prefix: str
    estimated_pages: int = 0
    selected: bool = True


class NavSection(BaseModel):
    """A documentation section discovered from site navigation."""

    label: str
    url: str
    path_prefix: str = ""
    children: list[NavLink] = []
    estimated_pages: int | None = None
    selected: bool = True
    sub_sections: list[NavSubSection] = []


class SiteStructure(BaseModel):
    """Navigation structure of a documentation site."""

    sections: list[NavSection] = []
    source: str = "generic"  # "pattern", "generic", "fallback"
    raw_nav_links: int = 0
    sitemap_urls: list[str] = []
