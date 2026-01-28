"""API schema extraction for OpenAPI/Docusaurus documentation."""

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag


def is_api_doc_page(url: str, html: str) -> bool:
    """Detect if this is an API documentation page with schema content."""
    # URL patterns for API docs
    api_url_patterns = [
        r"/docs/api/",
        r"/api-reference/",
        r"/api/v\d+/",
        r"/reference/",
    ]

    for pattern in api_url_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            # Confirm it has OpenAPI schema content (not just an index page)
            if html and "openapi-schema__property" in html:
                return True

    return False


def extract_api_schema(html: str) -> Optional[str]:
    """Extract API schema content and format as structured markdown.

    Targets docusaurus-openapi-docs plugin HTML structure:
    - .openapi-schema__list-item: field container
    - .openapi-schema__property: field name (<strong>)
    - .openapi-schema__name: field type (<span>)
    - .openapi-schema__required: required badge
    - .openapi__heading: page title
    - .openapi__method-endpoint: HTTP method + URL
    """
    soup = BeautifulSoup(html, "lxml")
    parts = []

    # Extract title
    title_elem = soup.select_one(".openapi__heading") or soup.find("h1")
    if title_elem:
        parts.append(f"# {title_elem.get_text(strip=True)}")
        parts.append("")

    # Extract HTTP method and endpoint
    method_block = soup.select_one(".openapi__method-endpoint")
    if method_block:
        method_badge = method_block.select_one(".badge")
        endpoint = method_block.select_one(".openapi__method-endpoint-path, h2")
        if method_badge and endpoint:
            method = method_badge.get_text(strip=True).upper()
            path = endpoint.get_text(strip=True)
            parts.append(f"**{method}** `{path}`")
            parts.append("")

    # Extract description paragraphs (before schema sections)
    content_area = soup.select_one(".openapi-left-panel__container") or soup
    for p in content_area.find_all("p", recursive=False):
        text = p.get_text(strip=True)
        if text and len(text) > 5:
            parts.append(text)
            parts.append("")

    # Also try direct child paragraphs of the markdown div
    markdown_div = soup.select_one(".theme-api-markdown .openapi-left-panel__container")
    if markdown_div:
        for child in markdown_div.children:
            if hasattr(child, "name") and child.name == "p":
                text = child.get_text(strip=True)
                if text and len(text) > 5 and text not in "\n".join(parts):
                    parts.append(text)
                    parts.append("")

    # Extract all schema sections (Request Body, Response Schema, etc.)
    # Track extracted field sets to avoid duplicates
    seen_field_sets: list[set[str]] = []
    details_sections = soup.select("details.openapi-markdown__details")
    for section in details_sections:
        section_md = _extract_schema_details(section)
        if section_md:
            # Track field names to detect duplicates
            schema_items = section.select(".openapi-schema__list-item, .openapi-params__list-item")
            field_names = {
                item.select_one(".openapi-schema__property").get_text(strip=True)
                for item in schema_items
                if item.select_one(".openapi-schema__property")
            }
            seen_field_sets.append(field_names)
            parts.append(section_md)
            parts.append("")

    # Also look for non-details schema sections (response schemas in tabpanels)
    for tabpanel in soup.select('[role="tabpanel"]'):
        # Skip if inside a details section (already handled above)
        if tabpanel.find_parent("details"):
            continue
        schema_items = tabpanel.select(".openapi-schema__list-item")
        if schema_items:
            fields = _extract_fields(schema_items)
            if fields:
                # Check if this is a duplicate of an already-extracted schema
                field_names = {f["name"] for f in fields}
                if any(field_names == seen for seen in seen_field_sets):
                    continue
                seen_field_sets.append(field_names)
                parts.append("## Response Schema")
                parts.append("")
                parts.append(_format_fields_table(fields))
                parts.append("")

    # Extract authorization info from right panel
    auth_md = _extract_auth_info(soup)
    if auth_md:
        parts.append(auth_md)
        parts.append("")

    # Extract code sample from right panel
    code_md = _extract_code_sample(soup)
    if code_md:
        parts.append(code_md)
        parts.append("")

    if len(parts) <= 2:
        return None

    return "\n".join(parts)


def _extract_schema_details(details: Tag) -> Optional[str]:
    """Extract a schema <details> section into markdown."""
    parts = []

    # Determine section type from details class
    is_response = "response" in details.get("class", [])

    # Get section header
    summary = details.find("summary")
    if summary:
        header_text = summary.get_text(" ", strip=True)
        # Clean up "Body required" -> "Body (required)"
        header_text = re.sub(r"(Body|Query|Path|Header)\s+(required)", r"\1 (required)", header_text)
        # Prefix response schemas clearly
        if is_response and header_text == "Schema":
            header_text = "Response Schema"
        parts.append(f"## {header_text}")
        parts.append("")

    # Extract fields (schema uses __list-item, params use params__list-item)
    schema_items = details.select(".openapi-schema__list-item, .openapi-params__list-item")
    fields = _extract_fields(schema_items)

    if fields:
        parts.append(_format_fields_table(fields))

    return "\n".join(parts) if parts else None


def _extract_fields(schema_items: list[Tag]) -> list[dict]:
    """Extract field definitions from openapi-schema__list-item elements."""
    fields = []

    for item in schema_items:
        field = {}

        # Field name: <strong class="openapi-schema__property">
        name_elem = item.select_one(".openapi-schema__property")
        if not name_elem:
            name_elem = item.find("strong")
        if name_elem:
            name = name_elem.get_text(strip=True)
            # Skip non-field entries
            if name in ["Example:", "Schema", "Body", ""]:
                continue
            field["name"] = name
        else:
            continue

        # Type: <span class="openapi-schema__name"> or <span class="openapi-schema__type">
        type_elem = item.select_one(".openapi-schema__name, .openapi-schema__type")
        if type_elem:
            field["type"] = type_elem.get_text(strip=True)
        else:
            field["type"] = ""

        # Required: check for .openapi-schema__required
        required_elem = item.select_one(".openapi-schema__required")
        field["required"] = bool(required_elem)

        # Description: first <p> in the item
        desc_elem = item.find("p")
        if desc_elem:
            field["description"] = desc_elem.get_text(strip=True)
        else:
            field["description"] = ""

        # Example: look for "Example:" pattern
        example_elem = item.select_one("code")
        example_strong = item.find("strong", string=re.compile(r"Example:?"))
        if example_strong and example_elem:
            field["example"] = example_elem.get_text(strip=True)

        fields.append(field)

    return fields


def _format_fields_table(fields: list[dict]) -> str:
    """Format extracted fields as a markdown table."""
    if not fields:
        return ""

    # Check if any fields have examples
    has_examples = any(f.get("example") for f in fields)

    lines = []
    if has_examples:
        lines.append("| Field | Type | Description | Example |")
        lines.append("|-------|------|-------------|---------|")
    else:
        lines.append("| Field | Type | Description |")
        lines.append("|-------|------|-------------|")

    for field in fields:
        name = field.get("name", "")
        ftype = field.get("type", "")
        desc = field.get("description", "").replace("|", "\\|")
        required = " **(required)**" if field.get("required") else ""

        # Truncate very long descriptions for table readability
        if len(desc) > 120:
            desc = desc[:117] + "..."

        if has_examples:
            example = field.get("example", "").replace("|", "\\|")
            if len(example) > 50:
                example = example[:47] + "..."
            lines.append(f"| `{name}` | {ftype} | {desc}{required} | {f'`{example}`' if example else ''} |")
        else:
            lines.append(f"| `{name}` | {ftype} | {desc}{required} |")

    return "\n".join(lines)


def _extract_auth_info(soup: Tag) -> Optional[str]:
    """Extract authorization details from the right panel."""
    auth_section = soup.select_one(".openapi-security__details")
    if not auth_section:
        return None

    parts = ["## Authorization"]
    parts.append("")

    # Get auth type from header
    header = auth_section.select_one(".openapi-security__summary-header")
    if header:
        parts.append(f"**{header.get_text(strip=True)}**")
        parts.append("")

    # Extract key-value pairs (name, type, scopes)
    for span in auth_section.select("pre > span"):
        strong = span.find("strong")
        if strong:
            key = strong.get_text(strip=True).rstrip(":")
            # Get the value text (everything after the strong)
            value_parts = []
            for sibling in strong.next_siblings:
                if hasattr(sibling, "get_text"):
                    value_parts.append(sibling.get_text(strip=True))
                elif isinstance(sibling, str) and sibling.strip():
                    value_parts.append(sibling.strip())
            value = " ".join(value_parts).strip()
            if key and value and key != "flows":
                parts.append(f"- **{key}:** {value}")

    # Extract required scopes
    scope_code = auth_section.select_one("span code")
    if scope_code:
        scope = scope_code.get_text(strip=True)
        if scope and f"**scopes:** {scope}" not in "\n".join(parts):
            parts.append(f"- **Scopes:** `{scope}`")

    return "\n".join(parts) if len(parts) > 2 else None


def _extract_code_sample(soup: Tag) -> Optional[str]:
    """Extract the first visible code sample from the right panel."""
    code_container = soup.select_one(".openapi-tabs__code-container")
    if not code_container:
        return None

    parts = ["## Example"]
    parts.append("")

    # Get the active language tab
    active_tab = code_container.select_one('[role="tab"][aria-selected="true"]')
    lang = ""
    if active_tab:
        lang = active_tab.get_text(strip=True).lower()

    # Get the visible code block
    tabpanel = code_container.select_one('[role="tabpanel"]')
    if not tabpanel:
        return None

    code_elem = tabpanel.select_one("code")
    if not code_elem:
        return None

    # Each line is a <span class="token-line"> with sub-tokens and a trailing <br>.
    # Extract text per line span to preserve line structure.
    line_spans = code_elem.select(".token-line")
    if line_spans:
        code_text = "\n".join(span.get_text() for span in line_spans)
    else:
        code_text = code_elem.get_text()
    if not code_text.strip():
        return None

    parts.append(f"```{lang}")
    parts.append(code_text.strip())
    parts.append("```")

    return "\n".join(parts)
