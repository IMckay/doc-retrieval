"""API schema extraction for OpenAPI/Docusaurus documentation."""

import json
import re

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


def extract_api_schema(html: str) -> str | None:
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

    # Track extracted field sets to avoid duplicates
    seen_field_sets: list[set[str]] = []
    details_sections = soup.select("details.openapi-markdown__details")
    for section in details_sections:
        section_md = _extract_schema_details(section)
        if section_md:
            schema_items = section.select(".openapi-schema__list-item, .openapi-params__list-item")
            prop_elem = None
            field_names: set[str] = set()
            for item in schema_items:
                prop_elem = item.select_one(".openapi-schema__property")
                if prop_elem:
                    field_names.add(prop_elem.get_text(strip=True))
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
            flat_fields, nested_sections = _extract_fields(schema_items)
            if flat_fields:
                # Check if this is a duplicate of an already-extracted schema
                field_names = {f["name"] for f in flat_fields}
                if any(field_names == seen for seen in seen_field_sets):
                    continue
                seen_field_sets.append(field_names)
                parts.append("## Response Schema")
                parts.append("")
                parts.append(_format_fields_table(flat_fields))
                parts.append("")
                for obj_name, child_fields in nested_sections:
                    parts.append(f"### {obj_name} object")
                    parts.append("")
                    parts.append(_format_fields_table(child_fields))
                    parts.append("")

    auth_md = _extract_auth_info(soup)
    if auth_md:
        parts.append(auth_md)
        parts.append("")

    code_md = _extract_code_sample(soup)
    if code_md:
        parts.append(code_md)
        parts.append("")

    if len(parts) <= 2:
        return None

    return "\n".join(parts)


def _extract_schema_details(details: Tag) -> str | None:
    """Extract a schema <details> section into markdown."""
    parts = []

    # Determine section type from details class
    raw_classes: str | list[str] = details.get("class") or []
    classes: list[str] = (
        raw_classes.split() if isinstance(raw_classes, str) else list(raw_classes)
    )
    is_response = "response" in classes

    # Get section header
    summary = details.find("summary")
    if summary:
        header_text = summary.get_text(" ", strip=True)
        # Clean up "Body required" -> "Body (required)"
        header_text = re.sub(
            r"(Body|Query|Path|Header)\s+(required)", r"\1 (required)", header_text
        )
        # Prefix response schemas clearly
        if is_response and header_text == "Schema":
            header_text = "Response Schema"
        parts.append(f"## {header_text}")
        parts.append("")

    # Extract fields (schema uses __list-item, params use params__list-item)
    schema_items = details.select(".openapi-schema__list-item, .openapi-params__list-item")
    flat_fields, nested_sections = _extract_fields(schema_items)

    if flat_fields:
        parts.append(_format_fields_table(flat_fields))

    for obj_name, child_fields in nested_sections:
        parts.append("")
        parts.append(f"### {obj_name} object")
        parts.append("")
        parts.append(_format_fields_table(child_fields))

    return "\n".join(parts) if parts else None


def _extract_single_field(item: Tag) -> dict | None:
    """Extract a single field definition from an openapi-schema__list-item element."""
    field: dict = {}

    # Field name: <strong class="openapi-schema__property">
    name_elem = item.select_one(".openapi-schema__property")
    if not name_elem:
        name_elem = item.find("strong")
    if name_elem:
        name = name_elem.get_text(strip=True)
        # Skip non-field entries
        if name in ["Example:", "Schema", "Body", ""]:
            return None
        field["name"] = name
    else:
        return None

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
    example_strong = item.find("strong", string=re.compile(r"Example:?"))  # type: ignore[call-overload]
    if example_strong:
        # Try a <code> sibling first
        example_elem = item.select_one("code")
        if example_elem:
            field["example"] = example_elem.get_text(strip=True)
        else:
            # Fall back to text content following the "Example:" label
            example_text_parts = []
            for sibling in example_strong.next_siblings:
                if hasattr(sibling, "get_text"):
                    example_text_parts.append(sibling.get_text(strip=True))
                elif isinstance(sibling, str) and sibling.strip():
                    example_text_parts.append(sibling.strip())
            example_text = " ".join(example_text_parts).strip()
            if example_text:
                field["example"] = example_text

    return field


def _extract_fields(
    schema_items: list[Tag],
) -> tuple[list[dict], list[tuple[str, list[dict]]]]:
    """Extract field definitions from openapi-schema__list-item elements.

    Returns:
        A tuple of (flat_fields, nested_sections) where nested_sections is a
        list of (parent_name, child_fields) for fields that are objects with
        nested sub-fields.
    """
    # First pass: identify parent objects whose direct child <ul> contains
    # nested .openapi-schema__list-item children
    nested_parents: dict[int, list[Tag]] = {}  # index in schema_items -> child items
    child_ids: set[int] = set()  # ids of items that are children of a parent

    for idx, item in enumerate(schema_items):
        # Look for a direct child <ul> containing schema list items
        child_ul = item.find("ul", recursive=False)
        if not child_ul:
            # Also check inside divs (collapsible wrappers)
            for div in item.find_all("div", recursive=False):
                child_ul = div.find("ul", recursive=False)
                if child_ul:
                    break
        if child_ul:
            child_items = child_ul.select(
                ":scope > li.openapi-schema__list-item, "
                ":scope > li > .openapi-schema__list-item"
            )
            if not child_items:
                # Broader fallback: any nested schema items
                child_items = child_ul.select(".openapi-schema__list-item")
            if child_items:
                nested_parents[idx] = child_items
                for ci in child_items:
                    child_ids.add(id(ci))

    # Second pass: build flat field list, skipping child items
    flat_fields = []
    nested_sections: list[tuple[str, list[dict]]] = []

    for idx, item in enumerate(schema_items):
        if id(item) in child_ids:
            continue

        field = _extract_single_field(item)
        if not field:
            continue

        if idx in nested_parents:
            # Mark as object type if type is empty
            if not field["type"]:
                field["type"] = "object"
            flat_fields.append(field)

            # Extract child fields
            child_fields = []
            for ci in nested_parents[idx]:
                cf = _extract_single_field(ci)
                if cf:
                    child_fields.append(cf)
            if child_fields:
                nested_sections.append((field["name"], child_fields))
        else:
            flat_fields.append(field)

    return flat_fields, nested_sections


def _format_fields_table(fields: list[dict]) -> str:
    """Format extracted fields as a markdown table."""
    if not fields:
        return ""

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

        if has_examples:
            example = field.get("example", "").replace("|", "\\|")
            ex_col = f"`{example}`" if example else ""
            lines.append(f"| `{name}` | {ftype} | {desc}{required} | {ex_col} |")
        else:
            lines.append(f"| `{name}` | {ftype} | {desc}{required} |")

    return "\n".join(lines)


def _extract_auth_info(soup: Tag) -> str | None:
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
        # Filter out JSON objects that leak through (OAuth flow definitions)
        if scope and not scope.lstrip().startswith("{") and "flows" not in scope:
            if f"**scopes:** {scope}" not in "\n".join(parts):
                parts.append(f"- **Scopes:** `{scope}`")
        elif scope and scope.lstrip().startswith("{"):
            # Parse OAuth flow URLs from the JSON-like content
            try:
                flow_data = json.loads(scope)
                for flow_name, flow_info in flow_data.items():
                    if isinstance(flow_info, dict):
                        if "authorizationUrl" in flow_info:
                            parts.append(
                                f"- **Authorization URL:** {flow_info['authorizationUrl']}"
                            )
                        if "tokenUrl" in flow_info:
                            parts.append(f"- **Token URL:** {flow_info['tokenUrl']}")
            except (json.JSONDecodeError, TypeError):
                pass

    return "\n".join(parts) if len(parts) > 2 else None


def _extract_code_sample(soup: Tag) -> str | None:
    """Extract code samples from the right panel.

    Only the active language tab's panel is rendered in the DOM (other
    language panels are lazy-loaded by JavaScript on click), so we
    extract the active tab and deduplicate to avoid repeating the same
    code under different language labels.
    """
    code_container = soup.select_one(".openapi-tabs__code-container")
    if not code_container:
        return None

    parts = ["## Example"]
    parts.append("")

    extracted_any = False
    seen_code: set[str] = set()

    lang_aliases = {
        "http.client": "python",
        "requests": "python",
    }
    allowed_langs = {"python", "http.client", "requests", "curl", "bash"}

    # First, check for captured tab snapshots injected by Playwright
    # (the plugin only renders one panel at a time, so we capture each
    # desired tab's panel during fetch and inject as hidden divs).
    for captured in code_container.select(".doc-retrieval-captured-tab"):
        tab_label = captured.get("data-tab-label", "")
        if isinstance(tab_label, list):
            tab_label = tab_label[0] if tab_label else ""
        raw_lang = str(tab_label).lower()
        if raw_lang not in allowed_langs:
            continue
        lang = lang_aliases.get(raw_lang, raw_lang)
        code_text = _extract_code_from_panel(captured)
        if code_text and code_text not in seen_code:
            seen_code.add(code_text)
            parts.append(f"```{lang}")
            parts.append(code_text)
            parts.append("```")
            parts.append("")
            extracted_any = True

    # Also check live tab panels (for tabs whose panel is in the DOM)
    for tab in code_container.select('[role="tab"]'):
        raw_lang = tab.get_text(strip=True).lower()
        if raw_lang not in allowed_langs:
            continue
        lang = lang_aliases.get(raw_lang, raw_lang)
        # Locate the panel this tab controls
        panel = None
        aria_controls = tab.get("aria-controls")
        if aria_controls:
            panel = code_container.find(id=aria_controls)
        if not panel:
            continue

        code_text = _extract_code_from_panel(panel)
        if code_text and code_text not in seen_code:
            seen_code.add(code_text)
            parts.append(f"```{lang}")
            parts.append(code_text)
            parts.append("```")
            parts.append("")
            extracted_any = True

    # Fallback: grab whatever visible panel exists
    if not extracted_any:
        active_tab = code_container.select_one(
            '[role="tab"][aria-selected="true"]'
        )
        raw_lang = active_tab.get_text(strip=True).lower() if active_tab else ""
        lang = lang_aliases.get(raw_lang, raw_lang)
        panel = code_container.select_one('[role="tabpanel"]')
        if panel:
            code_text = _extract_code_from_panel(panel)
            if code_text:
                parts.append(f"```{lang}")
                parts.append(code_text)
                parts.append("```")
                extracted_any = True

    return "\n".join(parts) if extracted_any else None


def _extract_code_from_panel(panel: Tag) -> str | None:
    """Extract code text from a tab panel element."""
    code_elem = panel.select_one("code")
    if not code_elem:
        return None

    # Each line is a <span class="token-line"> with sub-tokens and a trailing <br>.
    line_spans = code_elem.select(".token-line")
    if line_spans:
        code_text = "\n".join(span.get_text() for span in line_spans)
    else:
        code_text = code_elem.get_text()

    return code_text.strip() if code_text.strip() else None
