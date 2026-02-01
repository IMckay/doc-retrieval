# Pattern Detection Redesign

## Problem

The current pattern identification system has several weaknesses:

1. **Coarse signal matching** — `html_substring` does raw `in` checks on entire HTML. A comment mentioning "docusaurus" on a MkDocs site scores points for the wrong pattern.
2. **No disambiguation between overlapping patterns** — Docusaurus and docusaurus-openapi share signals with no way to prefer the more specific match.
3. **Misleading confidence** — `score / max_possible` means fewer signals = easier high confidence. A 2-signal pattern reaching 1.0 looks more confident than an 8-signal pattern at 0.75.
4. **Single-page detection** — Only the root page is analyzed. Some engines are only visible from inner documentation pages.
5. **No negative signals** — Cannot express "has X but NOT Y" for disambiguation.
6. **No HTTP header analysis** — Many platforms set identifiable response headers.
7. **Pattern config doesn't flow downstream** — Detected pattern's `wait_selector`, `click_tabs_selector`, and selectors aren't applied to the pipeline config.

## Design

### Pattern Hierarchy Model

`SitePattern` gains a `parent` field and auto-derived `specificity`:

```python
class SitePattern(BaseModel):
    name: str
    description: str
    parent: str | None = None
    specificity: int = 0  # auto-derived: parent.specificity + 1

    content_selectors: list[str] = []
    remove_selectors: list[str] = []
    requires_js: bool = True
    wait_selector: str | None = None
    wait_time_ms: int = 0
    click_tabs_selector: str | None = None

    phase1_signals: list[DetectionSignal] = []
    phase2_checks: list[Phase2Check] = []
```

Rules:
- `docusaurus-openapi` sets `parent="docusaurus"`, gets `specificity=1`.
- When both parent and child pass detection, the child wins automatically.
- Child selectors override entirely (no merging with parent).
- Registration validates the parent exists.

### Two-Phase Detection

#### Phase 1 — Cheap signals (no DOM parsing)

Runs against all patterns. Signal kinds:

| Kind | What it checks | Example |
|------|---------------|---------|
| `meta_generator` | `<meta name="generator">` content | `"docusaurus"` |
| `url_substring` | URL string containment | `"readthedocs"` |
| `html_substring` | Raw HTML containment (high-confidence markers only) | `"__docusaurus"` |
| `http_header` | HTTP response header presence/value | `"x-mintlify"` |

Phase 1 produces a list of candidate families. Any pattern scoring >= 15 becomes a candidate. All children of a matching parent are auto-included as candidates.

The `DetectionSignal` model stays the same:

```python
class DetectionSignal(BaseModel):
    kind: str  # "url_substring" | "html_substring" | "meta_generator" | "http_header"
    value: str
    weight: int = 10
    case_sensitive: bool = True
```

`http_header` signals use `value` as `"header-name:expected-substring"` (e.g., `"x-powered-by:mintlify"`). If no colon, checks header presence only.

#### Phase 2 — Targeted confirmation (DOM-aware, candidates only)

Runs only against Phase 1 candidates. Check kinds:

| Kind | What it checks | Example |
|------|---------------|---------|
| `css_present` | CSS selector matches >= 1 element | `".openapi-left-panel__container"` |
| `css_absent` | CSS selector matches 0 elements (negative signal) | `".sphinxsidebar"` |
| `script_src_regex` | Regex match against `<script src="...">` values | `"redoc\\.standalone"` |
| `content_min_length` | Main content area has >= N chars of text | `"500"` |

```python
class Phase2Check(BaseModel):
    kind: str  # "css_present" | "css_absent" | "script_src_regex" | "content_min_length"
    value: str
    weight: int = 20
    required: bool = False  # If True, failing this check disqualifies the pattern
```

Phase 2 checks against the (possibly JS-rendered) HTML use BeautifulSoup for CSS selectors, not Playwright — so this works on already-fetched HTML without additional browser calls.

### Inner-Page Probing

Triggered when root-page detection is inconclusive:
- `best.confidence < 0.5`, OR
- `second_best.score >= best.score * 0.8` (ambiguous)

Steps:
1. Extract up to 3 internal links from root HTML, preferring doc-like paths (`/docs/`, `/guide/`, `/api/`, `/reference/`, `/tutorial/`, `/getting-started`).
2. Fetch with httpx (or Playwright if root needed JS).
3. Run Phase 1 + Phase 2 on each inner page.
4. Aggregate scores across all probed pages (root + inner) by summing.
5. Highest aggregate score wins.

Constraints:
- Maximum 3 inner pages
- Reuses the existing httpx client / Playwright instance
- Skipped when root detection is confident
- Interactive mode shows: `"Detection inconclusive, checking inner pages..."`

Link extraction regex for probe candidates:
```python
_DOC_PATH_RE = re.compile(
    r'href="(/(?:docs?|guide|api|reference|tutorial|getting-started)[^"]*)"',
    re.IGNORECASE,
)
```

### Confidence Scoring

Phase 1 scoring: sum matched signal weights. Used only for candidate selection (threshold >= 15).

Final confidence uses a fixed normalizer:

```python
confidence = min(1.0, (phase1_score + phase2_score) / CONFIDENCE_NORMALIZER)
```

`CONFIDENCE_NORMALIZER = 100`. All patterns compete on the same absolute scale.

Confidence bands:
- `>= 0.7` — high confidence (green)
- `>= 0.4` — medium confidence (yellow)
- `< 0.4` — low confidence (dim)

Winner selection (in order):
1. Disqualify patterns with a failed `required` Phase 2 check.
2. Group remaining candidates by family (parent chain).
3. Within each family, the most-specific passing descendant wins.
4. Across families, highest combined score wins.
5. Ties broken by specificity (more specific preferred).

### Auto Config Flow

`PatternRegistry.apply_to_config()` applies pattern settings to the pipeline config, filling defaults without overriding explicit user settings:

```python
@classmethod
def apply_to_config(cls, pattern_name: str, config: AppConfig) -> AppConfig:
    pattern = cls.get(pattern_name)
    if not pattern:
        return config

    fetcher = config.fetcher.model_copy()
    if fetcher.wait_selector is None and pattern.wait_selector:
        fetcher.wait_selector = pattern.wait_selector
    if fetcher.wait_time_ms == 0 and pattern.wait_time_ms > 0:
        fetcher.wait_time_ms = pattern.wait_time_ms
    if fetcher.click_tabs_selector is None and pattern.click_tabs_selector:
        fetcher.click_tabs_selector = pattern.click_tabs_selector
    if not fetcher.use_js and pattern.requires_js:
        fetcher.use_js = True

    extractor = config.extractor.model_copy()
    if pattern.content_selectors:
        extractor.content_selectors = pattern.content_selectors
    if pattern.remove_selectors:
        extractor.remove_selectors = pattern.remove_selectors

    return config.model_copy(update={"fetcher": fetcher, "extractor": extractor})
```

Called in:
- `InteractiveExtractor._build_config()` — after building the config
- `Orchestrator.__init__()` — so CLI/batch mode also benefits

### Example: Docusaurus Family

**Docusaurus (base, specificity=0):**

Phase 1:
- `meta_generator:"docusaurus"` (weight 50)
- `html_substring:"__docusaurus"` (weight 30)
- `html_substring:"docMainContainer"` (weight 25)

Phase 2:
- `css_present:"article.markdown"` (weight 20)
- `css_present:'[class*="docMainContainer"]'` (weight 20)

**Docusaurus-OpenAPI (parent="docusaurus", specificity=1):**

Phase 1: inherits candidacy from parent match.

Phase 2:
- `css_present:".openapi-left-panel__container"` (weight 30, **required**)
- `css_present:".openapi-schema__property"` (weight 20)
- `script_src_regex:"docusaurus-openapi|plugin-content-docs-api"` (weight 20)
- `css_present:".openapi-explorer"` (weight 15)

If the openapi panel selector is absent, the child is disqualified and plain docusaurus wins. When present, the child's higher specificity wins automatically.

### Example: Readthedocs vs. Sphinx

**Sphinx (specificity=0):**

Phase 1: `meta_generator:"sphinx"` (50), `html_substring:"sphinxsidebar"` (30)
Phase 2: `css_present:'[role="main"]'` (15), `css_present:".document"` (15)

**Readthedocs (specificity=0, separate family):**

Phase 1: `url_substring:"readthedocs"` (25), `html_substring:"rst-content"` (30), `html_substring:"wy-nav-side"` (30)
Phase 2: `css_present:".wy-nav-side"` (required), `css_absent:".sphinxsidebar"` (15)

Readthedocs is a separate family (not a child of sphinx) because it uses a completely different theme with different selectors. The `css_absent:".sphinxsidebar"` negative signal prevents confusion.

## Files Changed

| File | Change |
|------|--------|
| `patterns/registry.py` | Add `Phase2Check` model, `parent`/`specificity` to `SitePattern`, split `detection_signals` into `phase1_signals` + `phase2_checks`, new `detect_two_phase()` method, `apply_to_config()`, inner-page probe logic. Restructure all 13 pattern definitions. |
| `patterns/__init__.py` | Export new types (`Phase2Check`) |
| `interactive.py` | Update `_analyze_site()` to pass HTTP headers to detection. Update `_detect_or_ask_pattern()` to use `detect_two_phase()`. Call `apply_to_config()` in `_build_config()`. |
| `orchestrator.py` | Call `PatternRegistry.apply_to_config()` during init. |
| `config.py` | No changes needed — `FetcherConfig` and `ExtractorConfig` already have the right fields. |

## Migration

The old `detect_with_confidence()` and `detect()` methods remain as deprecated wrappers around `detect_two_phase()` for backward compatibility. They will be removed in a future version.

The `detection_signals` field on `SitePattern` is replaced by `phase1_signals` + `phase2_checks`. Since there are no external consumers of these pattern definitions (all built-in), this is a clean swap.
