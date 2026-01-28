# doc-retrieval

Extract documentation from websites as LLM-ready Markdown. Point it at any documentation site and get clean, structured Markdown output suitable for use with LLMs.

## Installation

```bash
# Create virtual environment and install
uv venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
uv pip install -e .

# Install Playwright browsers (required for JS-rendered sites)
playwright install chromium
```

## Quick Start

```bash
# Run extraction (interactive mode by default)
doc-retrieval extract https://click.palletsprojects.com/en/stable/

# Non-interactive mode for scripting
doc-retrieval extract https://click.palletsprojects.com/en/stable/ -N -o click-docs.md
```

## Commands

### `extract` - Extract documentation from a website

```bash
doc-retrieval extract <URL> [OPTIONS]
```

**Arguments:**
- `URL` - Base URL of the documentation site (required)

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output` | `-o` | `output.md` | Output file path (single mode) or directory (multi mode) |
| `--mode` | `-m` | `single` | Output mode: `single` (one combined file) or `multi` (one file per page) |
| `--discovery` | `-d` | `sitemap` | URL discovery method: `sitemap`, `crawl`, or `manual` |
| `--urls-file` | `-f` | - | File containing URLs, one per line (required for `manual` mode) |
| `--include` | `-i` | - | Regex pattern - only include matching URLs |
| `--exclude` | `-e` | - | Regex pattern - exclude matching URLs |
| `--max-pages` | - | `0` | Maximum pages to extract (0 = unlimited) |
| `--max-depth` | - | `3` | Maximum link depth for `crawl` discovery |
| `--delay` | - | `1.0` | Delay between requests in seconds |
| `--js/--no-js` | - | `--js` | Enable/disable JavaScript rendering |
| `--pattern` | `-p` | - | Site pattern preset (see below) |
| `--interactive/--no-interactive` | `-I/-N` | `--interactive` | Interactive mode (default) or direct mode for scripting |
| `--verbose` | `-v` | - | Show detailed progress |

### `list-patterns` - Show available site presets

```bash
doc-retrieval list-patterns
```

## Interactive Mode (Default)

By default, `doc-retrieval` runs in interactive mode, guiding you through:

1. **Site analysis** - Fetches the URL and detects the documentation framework
2. **Pattern selection** - Suggests the detected pattern (Docusaurus, Sphinx, etc.) or lets you choose
3. **JS rendering** - Recommends whether JavaScript rendering is needed
4. **Page discovery** - Tries sitemap first, offers crawling as fallback
5. **URL filtering** - Shows discovered pages and lets you add include/exclude filters
6. **Output config** - Asks about single vs multi-file mode and output path
7. **Confirmation** - Shows summary before starting extraction

```bash
# Interactive mode (default)
doc-retrieval extract https://docs.example.com

# Skip interactive mode for scripting/automation
doc-retrieval extract https://docs.example.com -N -o docs.md
```

## Usage Examples (Non-Interactive)

Use `-N` to skip interactive mode for scripting and automation.

### Basic Extraction

```bash
# Extract using sitemap (default discovery method)
doc-retrieval extract https://docs.example.com -N -o docs.md

# Extract by crawling links from the starting page
doc-retrieval extract https://docs.example.com -N --discovery crawl -o docs.md

# Limit to 20 pages
doc-retrieval extract https://docs.example.com -N --max-pages 20 -o docs.md
```

### Output Modes

```bash
# Single file (default) - all pages combined with table of contents
doc-retrieval extract https://docs.example.com -N -o documentation.md

# Multi-file - one Markdown file per page, preserving URL structure
doc-retrieval extract https://docs.example.com -N --mode multi -o ./docs/
```

### URL Filtering

```bash
# Only include API reference pages
doc-retrieval extract https://docs.example.com -N --include "/api/.*" -o api-docs.md

# Exclude changelog and release notes
doc-retrieval extract https://docs.example.com -N --exclude ".*(changelog|releases).*" -o docs.md

# Combine filters
doc-retrieval extract https://docs.example.com -N \
  --include "/guide/.*" \
  --exclude ".*/deprecated/.*" \
  -o guide.md
```

### JavaScript Rendering

```bash
# With JS rendering (default) - for React, Vue, modern doc sites
doc-retrieval extract https://docs.example.com -N -o docs.md

# Without JS - faster, for static HTML sites like Sphinx/ReadTheDocs
doc-retrieval extract https://docs.example.com -N --no-js -o docs.md
```

### Site Patterns

Use presets for common documentation frameworks to improve extraction quality:

```bash
# Docusaurus sites
doc-retrieval extract https://docusaurus.io/docs -N --pattern docusaurus -o docs.md

# ReadTheDocs sites
doc-retrieval extract https://requests.readthedocs.io -N --pattern readthedocs --no-js -o docs.md

# GitBook sites
doc-retrieval extract https://docs.gitbook.com -N --pattern gitbook -o docs.md
```

Available patterns:
- `docusaurus` - Docusaurus documentation sites
- `gitbook` - GitBook documentation sites
- `readthedocs` - Read the Docs sites
- `mkdocs` - MkDocs documentation sites
- `sphinx` - Sphinx documentation sites
- `vitepress` - VitePress documentation sites

### Manual URL List

```bash
# Create a file with URLs to extract
cat > urls.txt << EOF
https://docs.example.com/getting-started
https://docs.example.com/api/overview
https://docs.example.com/api/reference
EOF

# Extract only those specific pages
doc-retrieval extract https://docs.example.com -N --discovery manual --urls-file urls.txt -o docs.md
```

## Output Format

### Single File Mode

```markdown
# Site Title

> Documentation extracted from https://docs.example.com
> Extracted on: 2024-01-07T12:00:00
> Total pages: 42

## Table of Contents

- [Getting Started](#getting-started)
- [API Reference](#api-reference)
...

---

<!-- Page: https://docs.example.com/getting-started -->
# Getting Started

Page content here...

---

<!-- Page: https://docs.example.com/api -->
# API Reference

Page content here...
```

### Multi-File Mode

```
output/
├── index.md           # Index with links to all pages
├── getting-started.md
├── api/
│   ├── overview.md
│   └── reference.md
└── guides/
    └── tutorial.md
```

## Development

```bash
# Clone and install with dev dependencies
git clone <repo>
cd doc-retrieval
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Install Playwright
playwright install chromium

# Run tests
pytest

# Lint
ruff check src/
```

## License

MIT
