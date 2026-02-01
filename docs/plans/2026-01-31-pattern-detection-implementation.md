# Pattern Detection Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single-pass weighted-signal pattern detection with a two-phase detection system featuring pattern hierarchy, DOM-aware checks, inner-page probing, and automatic config application.

**Architecture:** Phase 1 (cheap string/header signals) narrows to candidate families. Phase 2 (BeautifulSoup CSS checks, negative signals) confirms the winner. A parent/child hierarchy auto-resolves docusaurus vs docusaurus-openapi style conflicts. `apply_to_config()` pushes pattern settings into the pipeline config.

**Tech Stack:** Python 3.10+, Pydantic, BeautifulSoup4 (already a transitive dep via trafilatura), httpx, pytest

**Design doc:** `docs/plans/2026-01-31-pattern-detection-redesign.md`

---

### Task 1: Add Phase2Check model and update SitePattern

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py` (lines 10-43)
- Test: `tests/patterns/test_models.py` (create)

**Step 1: Write the failing tests**

Create `tests/` directory structure and test file:

```bash
mkdir -p tests/patterns
touch tests/__init__.py tests/patterns/__init__.py
```

```python
# tests/patterns/test_models.py
"""Tests for pattern detection models."""

from doc_retrieval.patterns.registry import (
    DetectionSignal,
    Phase2Check,
    SitePattern,
)


class TestPhase2Check:
    def test_create_css_present(self):
        check = Phase2Check(kind="css_present", value=".my-class", weight=20)
        assert check.kind == "css_present"
        assert check.value == ".my-class"
        assert check.weight == 20
        assert check.required is False

    def test_create_required_check(self):
        check = Phase2Check(kind="css_present", value=".must-have", required=True)
        assert check.required is True

    def test_css_absent_kind(self):
        check = Phase2Check(kind="css_absent", value=".sphinxsidebar")
        assert check.kind == "css_absent"

    def test_script_src_regex_kind(self):
        check = Phase2Check(kind="script_src_regex", value=r"redoc\.standalone")
        assert check.kind == "script_src_regex"

    def test_content_min_length_kind(self):
        check = Phase2Check(kind="content_min_length", value="500")
        assert check.kind == "content_min_length"


class TestSitePatternHierarchy:
    def test_default_no_parent(self):
        p = SitePattern(name="test", description="Test pattern")
        assert p.parent is None
        assert p.specificity == 0

    def test_parent_field(self):
        p = SitePattern(
            name="test-child", description="Child", parent="test-parent"
        )
        assert p.parent == "test-parent"

    def test_phase_fields_default_empty(self):
        p = SitePattern(name="test", description="Test")
        assert p.phase1_signals == []
        assert p.phase2_checks == []

    def test_phase1_signals(self):
        p = SitePattern(
            name="test",
            description="Test",
            phase1_signals=[
                DetectionSignal(kind="meta_generator", value="test", weight=50),
            ],
        )
        assert len(p.phase1_signals) == 1

    def test_phase2_checks(self):
        p = SitePattern(
            name="test",
            description="Test",
            phase2_checks=[
                Phase2Check(kind="css_present", value=".test", weight=20),
            ],
        )
        assert len(p.phase2_checks) == 1

    def test_backward_compat_detection_signals_still_works(self):
        """Old detection_signals field should still be accepted."""
        p = SitePattern(
            name="test",
            description="Test",
            detection_signals=[
                DetectionSignal(kind="html_substring", value="test", weight=10),
            ],
        )
        assert len(p.detection_signals) == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_models.py -v`
Expected: FAIL — `Phase2Check` not defined, `phase1_signals` / `phase2_checks` not on SitePattern

**Step 3: Implement the models**

In `src/doc_retrieval/patterns/registry.py`, add `Phase2Check` after `DetectionSignal` (after line 16) and update `SitePattern` (lines 28-43):

```python
class Phase2Check(BaseModel):
    """A DOM-aware check used in Phase 2 detection."""

    kind: str  # "css_present" | "css_absent" | "script_src_regex" | "content_min_length"
    value: str
    weight: int = 20
    required: bool = False
```

Update `SitePattern` to add `parent`, `specificity`, `phase1_signals`, `phase2_checks`:

```python
class SitePattern(BaseModel):
    """Configuration for a specific documentation site type."""

    name: str
    description: str
    parent: str | None = None
    specificity: int = 0

    content_selectors: list[str] = []
    remove_selectors: list[str] = []
    doc_url_patterns: list[str] = []
    exclude_url_patterns: list[str] = []
    requires_js: bool = True
    wait_selector: str | None = None
    wait_time_ms: int = 0
    click_tabs_selector: str | None = None

    detection_signals: list[DetectionSignal] = []
    phase1_signals: list[DetectionSignal] = []
    phase2_checks: list[Phase2Check] = []
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/test_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/ src/doc_retrieval/patterns/registry.py
git commit -m "feat: add Phase2Check model and hierarchy fields to SitePattern"
```

---

### Task 2: Phase 1 scoring logic

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py`
- Test: `tests/patterns/test_phase1.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_phase1.py
"""Tests for Phase 1 signal scoring."""

from doc_retrieval.patterns.registry import (
    DetectionSignal,
    PatternRegistry,
    SitePattern,
)

# Minimal test pattern for Phase 1 scoring
_TEST_PATTERN = SitePattern(
    name="_test_phase1",
    description="Test pattern for Phase 1",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="testgen", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__test_marker", weight=30),
        DetectionSignal(kind="url_substring", value="testdocs.io", weight=25),
        DetectionSignal(kind="http_header", value="x-test-engine", weight=40),
    ],
)


class TestPhase1Scoring:
    def test_meta_generator_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html='<meta name="generator" content="TestGen v2.0">',
            headers={},
        )
        assert score >= 50
        assert any("meta_generator" in m for m in matched)

    def test_html_substring_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html="<div>__test_marker</div>",
            headers={},
        )
        assert score >= 30
        assert any("html_substring" in m for m in matched)

    def test_url_substring_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://testdocs.io/guide",
            html="<html></html>",
            headers={},
        )
        assert score >= 25
        assert any("url_substring" in m for m in matched)

    def test_http_header_match_presence(self):
        """Header name only (no colon) — checks presence."""
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html="<html></html>",
            headers={"x-test-engine": "v1.0"},
        )
        assert score >= 40
        assert any("http_header" in m for m in matched)

    def test_http_header_match_value(self):
        """Header with colon — checks header value contains substring."""
        pattern = SitePattern(
            name="_test_hdr",
            description="Test",
            phase1_signals=[
                DetectionSignal(
                    kind="http_header",
                    value="x-powered-by:mintlify",
                    weight=40,
                    case_sensitive=False,
                ),
            ],
        )
        score, matched = PatternRegistry._score_phase1(
            pattern=pattern,
            url="https://example.com",
            html="<html></html>",
            headers={"x-powered-by": "Mintlify/3.0"},
        )
        assert score >= 40

    def test_http_header_no_match(self):
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html="<html></html>",
            headers={},
        )
        # Only http_header signal should NOT match; others may or may not
        assert not any("http_header:x-test-engine" in m for m in matched)

    def test_case_insensitive_meta_generator(self):
        score, _ = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://example.com",
            html='<meta name="generator" content="TESTGEN">',
            headers={},
        )
        assert score >= 50

    def test_no_signals_returns_zero(self):
        empty = SitePattern(name="_empty", description="No signals")
        score, matched = PatternRegistry._score_phase1(
            pattern=empty,
            url="https://example.com",
            html="<html></html>",
            headers={},
        )
        assert score == 0
        assert matched == []

    def test_multiple_signals_sum(self):
        """All signals matching should sum their weights."""
        score, matched = PatternRegistry._score_phase1(
            pattern=_TEST_PATTERN,
            url="https://testdocs.io/guide",
            html='<meta name="generator" content="testgen"><div>__test_marker</div>',
            headers={"x-test-engine": "v1"},
        )
        assert score == 50 + 30 + 25 + 40
        assert len(matched) == 4
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_phase1.py -v`
Expected: FAIL — `_score_phase1` method doesn't exist

**Step 3: Implement Phase 1 scoring**

Add to `PatternRegistry` class in `registry.py`:

```python
@classmethod
def _score_phase1(
    cls,
    pattern: SitePattern,
    url: str,
    html: str,
    headers: dict[str, str],
) -> tuple[int, list[str]]:
    """Score a pattern's Phase 1 signals against page data.

    Returns (score, list_of_matched_signal_descriptions).
    """
    url_lower = url.lower()
    html_lower = html.lower() if html else ""
    generators = _extract_meta_generators(html) if html else []
    generators_lower = [g.lower() for g in generators]
    headers_lower = {k.lower(): v.lower() for k, v in headers.items()}

    score = 0
    matched: list[str] = []

    for signal in pattern.phase1_signals:
        hit = False

        if signal.kind == "url_substring":
            target = url if signal.case_sensitive else url_lower
            value = signal.value if signal.case_sensitive else signal.value.lower()
            hit = value in target

        elif signal.kind == "html_substring":
            target = html if signal.case_sensitive else html_lower
            value = signal.value if signal.case_sensitive else signal.value.lower()
            hit = value in target

        elif signal.kind == "meta_generator":
            value = signal.value if signal.case_sensitive else signal.value.lower()
            source = generators if signal.case_sensitive else generators_lower
            hit = any(value in g for g in source)

        elif signal.kind == "http_header":
            if ":" in signal.value:
                header_name, expected = signal.value.split(":", 1)
                header_name_l = header_name.lower()
                expected_l = expected.lower() if not signal.case_sensitive else expected
                actual = headers_lower.get(header_name_l, "")
                if not signal.case_sensitive:
                    hit = expected_l in actual
                else:
                    raw_actual = headers.get(header_name, "")
                    hit = expected in raw_actual
            else:
                hit = signal.value.lower() in headers_lower

        if hit:
            score += signal.weight
            matched.append(f"{signal.kind}:{signal.value}")

    return score, matched
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/test_phase1.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/patterns/test_phase1.py src/doc_retrieval/patterns/registry.py
git commit -m "feat: add Phase 1 scoring with http_header signal support"
```

---

### Task 3: Phase 2 scoring logic

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py`
- Test: `tests/patterns/test_phase2.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_phase2.py
"""Tests for Phase 2 DOM-aware scoring."""

import pytest

from doc_retrieval.patterns.registry import (
    PatternRegistry,
    Phase2Check,
    SitePattern,
)


def _make_pattern(checks: list[Phase2Check]) -> SitePattern:
    return SitePattern(
        name="_test_p2", description="Test", phase2_checks=checks
    )


SIMPLE_HTML = """
<html>
<head><script src="/assets/redoc.standalone.js"></script></head>
<body>
<main>
  <article class="markdown">
    <div class="openapi-left-panel__container">
        <p>Some API documentation content that is long enough to pass length checks
        and contains meaningful text about endpoints and parameters.</p>
    </div>
  </article>
</main>
</body>
</html>
"""


class TestPhase2CssPresent:
    def test_css_present_hit(self):
        p = _make_pattern([Phase2Check(kind="css_present", value="article.markdown", weight=20)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 20
        assert len(matched) == 1
        assert not disqualified

    def test_css_present_miss(self):
        p = _make_pattern([Phase2Check(kind="css_present", value=".nonexistent-class", weight=20)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0
        assert matched == []
        assert not disqualified

    def test_css_present_required_miss_disqualifies(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value=".nonexistent", weight=30, required=True),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert disqualified

    def test_css_present_required_hit_does_not_disqualify(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value="article.markdown", weight=30, required=True),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 30
        assert not disqualified


class TestPhase2CssAbsent:
    def test_css_absent_hit(self):
        """Element NOT present → css_absent scores."""
        p = _make_pattern([Phase2Check(kind="css_absent", value=".sphinxsidebar", weight=15)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 15

    def test_css_absent_miss(self):
        """Element IS present → css_absent does NOT score."""
        p = _make_pattern([Phase2Check(kind="css_absent", value="article.markdown", weight=15)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0

    def test_css_absent_required_miss_disqualifies(self):
        """Element IS present when it shouldn't be → disqualify."""
        p = _make_pattern([
            Phase2Check(kind="css_absent", value="article.markdown", weight=15, required=True),
        ])
        _, _, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert disqualified


class TestPhase2ScriptSrcRegex:
    def test_script_src_regex_hit(self):
        p = _make_pattern([
            Phase2Check(kind="script_src_regex", value=r"redoc\.standalone", weight=25),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 25

    def test_script_src_regex_miss(self):
        p = _make_pattern([
            Phase2Check(kind="script_src_regex", value=r"swagger-ui-bundle", weight=25),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0


class TestPhase2ContentMinLength:
    def test_content_min_length_pass(self):
        p = _make_pattern([Phase2Check(kind="content_min_length", value="10", weight=10)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 10

    def test_content_min_length_fail(self):
        short_html = "<html><body><main><p>Hi</p></main></body></html>"
        p = _make_pattern([Phase2Check(kind="content_min_length", value="5000", weight=10)])
        score, matched, disqualified = PatternRegistry._score_phase2(p, short_html)
        assert score == 0


class TestPhase2MultipleChecks:
    def test_scores_sum(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value="article.markdown", weight=20),
            Phase2Check(kind="css_absent", value=".sphinxsidebar", weight=15),
            Phase2Check(kind="script_src_regex", value=r"redoc\.standalone", weight=25),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 20 + 15 + 25
        assert len(matched) == 3
        assert not disqualified

    def test_one_required_fail_disqualifies_all(self):
        p = _make_pattern([
            Phase2Check(kind="css_present", value="article.markdown", weight=20),
            Phase2Check(kind="css_present", value=".nonexistent", weight=30, required=True),
        ])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert disqualified

    def test_empty_checks(self):
        p = _make_pattern([])
        score, matched, disqualified = PatternRegistry._score_phase2(p, SIMPLE_HTML)
        assert score == 0
        assert matched == []
        assert not disqualified
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_phase2.py -v`
Expected: FAIL — `_score_phase2` method doesn't exist

**Step 3: Implement Phase 2 scoring**

Add import at top of `registry.py`:

```python
from bs4 import BeautifulSoup
```

Add to `PatternRegistry` class:

```python
@classmethod
def _score_phase2(
    cls,
    pattern: SitePattern,
    html: str,
) -> tuple[int, list[str], bool]:
    """Score a pattern's Phase 2 checks against parsed HTML.

    Returns (score, matched_descriptions, disqualified).
    disqualified is True if any required check failed.
    """
    if not pattern.phase2_checks:
        return 0, [], False

    soup = BeautifulSoup(html, "html.parser")
    score = 0
    matched: list[str] = []
    disqualified = False

    for check in pattern.phase2_checks:
        hit = False

        if check.kind == "css_present":
            hit = soup.select_one(check.value) is not None

        elif check.kind == "css_absent":
            hit = soup.select_one(check.value) is None

        elif check.kind == "script_src_regex":
            regex = re.compile(check.value)
            for script in soup.find_all("script", src=True):
                if regex.search(script["src"]):
                    hit = True
                    break

        elif check.kind == "content_min_length":
            threshold = int(check.value)
            main_el = soup.select_one("main") or soup.select_one("body")
            if main_el:
                text = main_el.get_text(separator=" ", strip=True)
                hit = len(text) >= threshold

        if hit:
            score += check.weight
            matched.append(f"{check.kind}:{check.value}")
        elif check.required:
            disqualified = True

    return score, matched, disqualified
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/test_phase2.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/patterns/test_phase2.py src/doc_retrieval/patterns/registry.py
git commit -m "feat: add Phase 2 DOM-aware scoring with CSS checks and negative signals"
```

---

### Task 4: Winner selection with hierarchy

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py`
- Test: `tests/patterns/test_winner_selection.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_winner_selection.py
"""Tests for winner selection with pattern hierarchy."""

import pytest

from doc_retrieval.patterns.registry import (
    DetectionResult,
    DetectionSignal,
    PatternRegistry,
    Phase2Check,
    SitePattern,
)


def _result(pattern: SitePattern, p1: int, p2: int, disq: bool = False) -> dict:
    """Helper to build a candidate dict for _select_winner."""
    return {
        "pattern": pattern,
        "phase1_score": p1,
        "phase2_score": p2,
        "disqualified": disq,
        "matched_signals": [f"test:{p1}"],
    }


class TestSelectWinner:
    def setup_method(self):
        """Register test patterns for hierarchy tests."""
        self.parent = SitePattern(
            name="_test_parent", description="Parent", specificity=0
        )
        self.child = SitePattern(
            name="_test_child",
            description="Child",
            parent="_test_parent",
            specificity=1,
        )
        self.unrelated = SitePattern(
            name="_test_unrelated", description="Unrelated", specificity=0
        )

    def test_highest_score_wins(self):
        candidates = [
            _result(self.parent, 50, 20),
            _result(self.unrelated, 30, 10),
        ]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is not None
        assert winner.pattern.name == "_test_parent"

    def test_child_beats_parent_in_same_family(self):
        """Child with lower score still wins over parent due to specificity."""
        candidates = [
            _result(self.parent, 50, 30),  # total 80
            _result(self.child, 50, 20),   # total 70, but specificity=1
        ]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is not None
        assert winner.pattern.name == "_test_child"

    def test_disqualified_pattern_excluded(self):
        candidates = [
            _result(self.parent, 50, 30, disq=True),
            _result(self.unrelated, 30, 10),
        ]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is not None
        assert winner.pattern.name == "_test_unrelated"

    def test_disqualified_child_falls_back_to_parent(self):
        candidates = [
            _result(self.parent, 50, 30),
            _result(self.child, 50, 20, disq=True),
        ]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is not None
        assert winner.pattern.name == "_test_parent"

    def test_all_disqualified_returns_none(self):
        candidates = [
            _result(self.parent, 50, 30, disq=True),
            _result(self.unrelated, 30, 10, disq=True),
        ]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is None

    def test_empty_candidates_returns_none(self):
        winner = PatternRegistry._select_winner([])
        assert winner is None

    def test_tie_broken_by_specificity(self):
        """Same score across families — higher specificity wins."""
        specific = SitePattern(
            name="_test_specific", description="Specific", specificity=1
        )
        general = SitePattern(
            name="_test_general", description="General", specificity=0
        )
        candidates = [
            _result(general, 50, 20),
            _result(specific, 50, 20),
        ]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is not None
        assert winner.pattern.name == "_test_specific"

    def test_confidence_calculation(self):
        candidates = [_result(self.parent, 50, 30)]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is not None
        # (50 + 30) / 100 = 0.8
        assert winner.confidence == pytest.approx(0.8)

    def test_confidence_capped_at_1(self):
        candidates = [_result(self.parent, 80, 50)]
        winner = PatternRegistry._select_winner(candidates)
        assert winner is not None
        assert winner.confidence == 1.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_winner_selection.py -v`
Expected: FAIL — `_select_winner` method doesn't exist

**Step 3: Implement winner selection**

Add constant and method to `registry.py`:

```python
CONFIDENCE_NORMALIZER = 100
```

Add to `PatternRegistry` class:

```python
@classmethod
def _select_winner(
    cls, candidates: list[dict]
) -> DetectionResult | None:
    """Select the winning pattern from scored candidates.

    Each candidate dict has keys: pattern, phase1_score, phase2_score,
    disqualified, matched_signals.

    Rules:
    1. Disqualified patterns are excluded.
    2. Group by family (parent chain root).
    3. Within each family, most-specific wins.
    4. Across families, highest combined score wins.
    5. Ties broken by specificity.
    """
    # Filter out disqualified
    viable = [c for c in candidates if not c["disqualified"]]
    if not viable:
        return None

    # Group by family root
    families: dict[str, list[dict]] = {}
    for c in viable:
        root = c["pattern"].parent or c["pattern"].name
        families.setdefault(root, []).append(c)

    # Pick best per family (highest specificity)
    family_winners: list[dict] = []
    for members in families.values():
        members.sort(key=lambda c: c["pattern"].specificity, reverse=True)
        family_winners.append(members[0])

    # Pick overall winner: highest total score, ties broken by specificity
    family_winners.sort(
        key=lambda c: (
            c["phase1_score"] + c["phase2_score"],
            c["pattern"].specificity,
        ),
        reverse=True,
    )

    best = family_winners[0]
    total = best["phase1_score"] + best["phase2_score"]
    confidence = min(1.0, total / CONFIDENCE_NORMALIZER)

    all_matched = best["matched_signals"]

    return DetectionResult(
        pattern=best["pattern"],
        score=total,
        confidence=confidence,
        matched_signals=all_matched,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/test_winner_selection.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/patterns/test_winner_selection.py src/doc_retrieval/patterns/registry.py
git commit -m "feat: add winner selection with hierarchy, disqualification, and fixed-normalizer confidence"
```

---

### Task 5: detect_two_phase() integration

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py`
- Test: `tests/patterns/test_detect_two_phase.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_detect_two_phase.py
"""Integration tests for two-phase detection."""

import pytest

from doc_retrieval.patterns.registry import (
    DetectionSignal,
    PatternRegistry,
    Phase2Check,
    SitePattern,
)

# Register test patterns with Phase 1 + Phase 2 signals
_PARENT = SitePattern(
    name="_integ_parent",
    description="Integration parent",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="integtest", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__integtest", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".integ-content", weight=20),
    ],
)

_CHILD = SitePattern(
    name="_integ_child",
    description="Integration child",
    parent="_integ_parent",
    specificity=1,
    phase1_signals=[],  # Inherits candidacy from parent
    phase2_checks=[
        Phase2Check(kind="css_present", value=".integ-special", weight=30, required=True),
        Phase2Check(kind="css_present", value=".integ-content", weight=20),
    ],
)

_OTHER = SitePattern(
    name="_integ_other",
    description="Integration other",
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="__other_marker", weight=40),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".other-content", weight=20),
    ],
)


class TestDetectTwoPhase:
    def setup_method(self):
        # Save original patterns to restore later
        self._original = dict(PatternRegistry._patterns)
        PatternRegistry._patterns.clear()
        PatternRegistry.register(_PARENT)
        PatternRegistry.register(_CHILD)
        PatternRegistry.register(_OTHER)

    def teardown_method(self):
        PatternRegistry._patterns = self._original

    def test_parent_detected_when_child_disqualified(self):
        html = """
        <html>
        <head><meta name="generator" content="IntegTest v1"></head>
        <body><main>
            <div class="integ-content">
                <p>Enough content to be meaningful for detection.</p>
            </div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is not None
        assert result.pattern.name == "_integ_parent"

    def test_child_wins_when_special_element_present(self):
        html = """
        <html>
        <head><meta name="generator" content="IntegTest v1"></head>
        <body><main>
            <div class="integ-content">
                <div class="integ-special">Special child content</div>
                <p>Main content here.</p>
            </div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is not None
        assert result.pattern.name == "_integ_child"

    def test_unrelated_pattern_detected(self):
        html = """
        <html><body><main>
            <div>__other_marker</div>
            <div class="other-content">Content</div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is not None
        assert result.pattern.name == "_integ_other"

    def test_no_match_returns_none(self):
        html = "<html><body><p>Generic page</p></body></html>"
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        assert result is None

    def test_http_header_contributes_to_detection(self):
        header_pattern = SitePattern(
            name="_integ_header",
            description="Header-detected",
            phase1_signals=[
                DetectionSignal(kind="http_header", value="x-custom-engine", weight=50),
            ],
            phase2_checks=[],
        )
        PatternRegistry.register(header_pattern)
        result = PatternRegistry.detect_two_phase(
            url="https://example.com",
            html="<html><body></body></html>",
            headers={"x-custom-engine": "v2.0"},
        )
        assert result is not None
        assert result.pattern.name == "_integ_header"

    def test_child_auto_candidacy_from_parent(self):
        """Child with no phase1_signals still becomes candidate when parent matches."""
        html = """
        <html>
        <head><meta name="generator" content="IntegTest"></head>
        <body><main>
            <div class="integ-content">
                <div class="integ-special">API docs</div>
            </div>
        </main></body></html>
        """
        result = PatternRegistry.detect_two_phase(
            url="https://example.com", html=html, headers={}
        )
        # Child should win because integ-special is present
        assert result is not None
        assert result.pattern.name == "_integ_child"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_detect_two_phase.py -v`
Expected: FAIL — `detect_two_phase` method doesn't exist

**Step 3: Implement detect_two_phase()**

Add to `PatternRegistry` class:

```python
_PHASE1_CANDIDATE_THRESHOLD = 15

@classmethod
def detect_two_phase(
    cls,
    url: str,
    html: str,
    headers: dict[str, str] | None = None,
) -> DetectionResult | None:
    """Two-phase pattern detection with hierarchy support.

    Phase 1: Score all patterns with cheap signals (string checks, headers).
    Phase 2: Score candidates with DOM-aware checks (CSS selectors, etc.).
    Returns the winning DetectionResult or None.
    """
    if headers is None:
        headers = {}

    # Phase 1: score all patterns
    phase1_scores: dict[str, tuple[int, list[str]]] = {}
    for pattern in cls._patterns.values():
        if not pattern.phase1_signals:
            continue
        score, matched = cls._score_phase1(pattern, url, html, headers)
        if score >= cls._PHASE1_CANDIDATE_THRESHOLD:
            phase1_scores[pattern.name] = (score, matched)

    # Build candidate set: patterns that passed Phase 1 + children of passing parents
    candidate_names: set[str] = set(phase1_scores.keys())
    for pattern in cls._patterns.values():
        if pattern.parent and pattern.parent in candidate_names:
            candidate_names.add(pattern.name)

    if not candidate_names:
        return None

    # Phase 2: score candidates with DOM-aware checks
    candidates: list[dict] = []
    for name in candidate_names:
        pattern = cls._patterns[name]
        p1_score, p1_matched = phase1_scores.get(name, (0, []))
        p2_score, p2_matched, disqualified = cls._score_phase2(pattern, html)

        candidates.append({
            "pattern": pattern,
            "phase1_score": p1_score,
            "phase2_score": p2_score,
            "disqualified": disqualified,
            "matched_signals": p1_matched + p2_matched,
        })

    return cls._select_winner(candidates)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/test_detect_two_phase.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/patterns/test_detect_two_phase.py src/doc_retrieval/patterns/registry.py
git commit -m "feat: add detect_two_phase() integrating Phase 1, Phase 2, and hierarchy"
```

---

### Task 6: Inner-page probing

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py`
- Test: `tests/patterns/test_inner_probe.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_inner_probe.py
"""Tests for inner-page probing utilities."""

from doc_retrieval.patterns.registry import PatternRegistry


class TestExtractProbeUrls:
    def test_extracts_doc_paths(self):
        html = """
        <html><body>
        <a href="/docs/getting-started">Start</a>
        <a href="/guide/intro">Guide</a>
        <a href="/api/reference">API</a>
        <a href="/blog/post-1">Blog</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        assert len(urls) <= 3
        # Doc paths should be preferred over blog
        paths = [u.split("example.com")[1] for u in urls]
        assert "/blog/post-1" not in paths
        assert any("/docs/" in p or "/guide/" in p or "/api/" in p for p in paths)

    def test_limits_to_3(self):
        html = """
        <html><body>
        <a href="/docs/a">A</a>
        <a href="/docs/b">B</a>
        <a href="/guide/c">C</a>
        <a href="/api/d">D</a>
        <a href="/reference/e">E</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        assert len(urls) == 3

    def test_falls_back_to_same_domain_links(self):
        html = """
        <html><body>
        <a href="/about">About</a>
        <a href="/features">Features</a>
        <a href="https://other.com/page">External</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        # Should pick same-domain links, not external
        assert all("example.com" in u for u in urls)

    def test_deduplicates(self):
        html = """
        <html><body>
        <a href="/docs/intro">Intro</a>
        <a href="/docs/intro">Intro again</a>
        <a href="/docs/intro#section">Intro with hash</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        # /docs/intro and /docs/intro#section should deduplicate to 1-2
        assert len(urls) <= 2

    def test_skips_root_url(self):
        html = """
        <html><body>
        <a href="/">Home</a>
        <a href="/docs/intro">Intro</a>
        </body></html>
        """
        urls = PatternRegistry._extract_probe_urls(
            html, base_url="https://example.com"
        )
        assert "https://example.com/" not in urls
        assert "https://example.com" not in urls

    def test_empty_html(self):
        urls = PatternRegistry._extract_probe_urls(
            html="<html></html>", base_url="https://example.com"
        )
        assert urls == []


class TestShouldProbeInnerPages:
    def test_confident_result_no_probe(self):
        assert not PatternRegistry._should_probe_inner_pages(
            best_confidence=0.7, best_score=80, second_score=30
        )

    def test_low_confidence_triggers_probe(self):
        assert PatternRegistry._should_probe_inner_pages(
            best_confidence=0.3, best_score=30, second_score=0
        )

    def test_ambiguous_scores_trigger_probe(self):
        assert PatternRegistry._should_probe_inner_pages(
            best_confidence=0.6, best_score=60, second_score=50
        )

    def test_no_result_triggers_probe(self):
        assert PatternRegistry._should_probe_inner_pages(
            best_confidence=0.0, best_score=0, second_score=0
        )
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_inner_probe.py -v`
Expected: FAIL — `_extract_probe_urls` and `_should_probe_inner_pages` don't exist

**Step 3: Implement inner-page probe utilities**

Add regex at module level in `registry.py`:

```python
from urllib.parse import urljoin, urlparse

_DOC_PATH_RE = re.compile(
    r'href="(/(?:docs?|guide|api|reference|tutorial|getting-started)[^"]*)"',
    re.IGNORECASE,
)

_SAME_DOMAIN_HREF_RE = re.compile(r'href="(/[^"]*)"')
```

Add to `PatternRegistry` class:

```python
@staticmethod
def _should_probe_inner_pages(
    best_confidence: float,
    best_score: int,
    second_score: int,
) -> bool:
    """Determine if inner-page probing should be triggered."""
    if best_score == 0:
        return True
    if best_confidence < 0.5:
        return True
    if second_score >= best_score * 0.8:
        return True
    return False

@staticmethod
def _extract_probe_urls(html: str, base_url: str) -> list[str]:
    """Extract up to 3 internal URLs for probing, preferring doc-like paths."""
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    base_normalized = f"{parsed_base.scheme}://{base_domain}"

    # Prefer doc-like paths
    doc_hrefs = _DOC_PATH_RE.findall(html)
    # Fallback: any same-domain relative path
    all_hrefs = _SAME_DOMAIN_HREF_RE.findall(html)

    seen: set[str] = set()
    result: list[str] = []

    def _add(href: str) -> bool:
        # Strip fragment
        href = href.split("#")[0]
        if not href or href == "/":
            return False
        full = urljoin(base_normalized + "/", href)
        # Must be same domain
        if urlparse(full).netloc != base_domain:
            return False
        if full in seen:
            return False
        # Skip if it's the base URL itself
        if full.rstrip("/") == base_url.rstrip("/"):
            return False
        seen.add(full)
        result.append(full)
        return len(result) >= 3

    # Doc paths first
    for href in doc_hrefs:
        if _add(href):
            break

    # Fill remaining with any same-domain links
    if len(result) < 3:
        for href in all_hrefs:
            if _add(href):
                break

    return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/test_inner_probe.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/patterns/test_inner_probe.py src/doc_retrieval/patterns/registry.py
git commit -m "feat: add inner-page probe URL extraction and trigger logic"
```

---

### Task 7: apply_to_config()

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py`
- Test: `tests/patterns/test_apply_config.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_apply_config.py
"""Tests for PatternRegistry.apply_to_config()."""

from doc_retrieval.config import AppConfig, ExtractorConfig, FetcherConfig
from doc_retrieval.patterns.registry import PatternRegistry, SitePattern


def _register_test_pattern() -> SitePattern:
    p = SitePattern(
        name="_test_apply",
        description="Test apply",
        content_selectors=[".test-content", ".test-article"],
        remove_selectors=[".test-nav", ".test-footer"],
        requires_js=True,
        wait_selector=".test-main",
        wait_time_ms=500,
        click_tabs_selector='.test-tabs [role="tab"]',
    )
    PatternRegistry.register(p)
    return p


class TestApplyToConfig:
    def setup_method(self):
        self._original = dict(PatternRegistry._patterns)
        _register_test_pattern()

    def teardown_method(self):
        PatternRegistry._patterns = self._original

    def test_fills_default_fetcher_fields(self):
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.wait_selector == ".test-main"
        assert result.fetcher.wait_time_ms == 500
        assert result.fetcher.click_tabs_selector == '.test-tabs [role="tab"]'
        assert result.fetcher.use_js is True

    def test_does_not_override_explicit_wait_selector(self):
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(wait_selector=".user-custom"),
        )
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.wait_selector == ".user-custom"

    def test_does_not_override_explicit_wait_time(self):
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(wait_time_ms=2000),
        )
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.wait_time_ms == 2000

    def test_replaces_extractor_selectors(self):
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.extractor.content_selectors == [".test-content", ".test-article"]
        assert result.extractor.remove_selectors == [".test-nav", ".test-footer"]

    def test_unknown_pattern_returns_unchanged(self):
        config = AppConfig(base_url="https://example.com")
        result = PatternRegistry.apply_to_config("nonexistent", config)
        assert result.fetcher.wait_selector is None
        assert result.extractor.content_selectors == config.extractor.content_selectors

    def test_original_config_not_mutated(self):
        config = AppConfig(base_url="https://example.com")
        original_wait = config.fetcher.wait_selector
        PatternRegistry.apply_to_config("_test_apply", config)
        assert config.fetcher.wait_selector == original_wait

    def test_enables_js_when_pattern_requires_it(self):
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(use_js=False),
        )
        result = PatternRegistry.apply_to_config("_test_apply", config)
        assert result.fetcher.use_js is True

    def test_no_js_pattern_preserves_user_choice(self):
        """A pattern that doesn't require JS shouldn't force it on."""
        no_js = SitePattern(
            name="_test_no_js",
            description="No JS",
            requires_js=False,
            content_selectors=[".static"],
        )
        PatternRegistry.register(no_js)
        config = AppConfig(
            base_url="https://example.com",
            fetcher=FetcherConfig(use_js=False),
        )
        result = PatternRegistry.apply_to_config("_test_no_js", config)
        assert result.fetcher.use_js is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_apply_config.py -v`
Expected: FAIL — `apply_to_config` method doesn't exist

**Step 3: Implement apply_to_config()**

Add import at top of `registry.py`:

```python
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from doc_retrieval.config import AppConfig
```

Add to `PatternRegistry` class:

```python
@classmethod
def apply_to_config(cls, pattern_name: str, config: AppConfig) -> AppConfig:
    """Apply pattern settings to config, filling defaults only.

    Pattern settings override default values but not explicit user settings.
    Returns a new AppConfig (original is not mutated).
    """
    from doc_retrieval.config import AppConfig as _AC  # avoid circular at runtime

    pattern = cls.get(pattern_name)
    if not pattern:
        return config

    fetcher_updates: dict = {}
    if config.fetcher.wait_selector is None and pattern.wait_selector:
        fetcher_updates["wait_selector"] = pattern.wait_selector
    if config.fetcher.wait_time_ms == 0 and pattern.wait_time_ms > 0:
        fetcher_updates["wait_time_ms"] = pattern.wait_time_ms
    if config.fetcher.click_tabs_selector is None and pattern.click_tabs_selector:
        fetcher_updates["click_tabs_selector"] = pattern.click_tabs_selector
    if not config.fetcher.use_js and pattern.requires_js:
        fetcher_updates["use_js"] = True

    extractor_updates: dict = {}
    if pattern.content_selectors:
        extractor_updates["content_selectors"] = pattern.content_selectors
    if pattern.remove_selectors:
        extractor_updates["remove_selectors"] = pattern.remove_selectors

    updates: dict = {}
    if fetcher_updates:
        updates["fetcher"] = config.fetcher.model_copy(update=fetcher_updates)
    if extractor_updates:
        updates["extractor"] = config.extractor.model_copy(update=extractor_updates)

    if updates:
        return config.model_copy(update=updates)
    return config
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/test_apply_config.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/patterns/test_apply_config.py src/doc_retrieval/patterns/registry.py
git commit -m "feat: add apply_to_config() for automatic pattern-to-pipeline config flow"
```

---

### Task 8: Restructure all 13 pattern definitions

**Files:**
- Modify: `src/doc_retrieval/patterns/registry.py` (lines 46-448)
- Test: `tests/patterns/test_pattern_definitions.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_pattern_definitions.py
"""Tests verifying all built-in pattern definitions are valid."""

import pytest

from doc_retrieval.patterns.registry import PatternRegistry, SitePattern


class TestPatternDefinitions:
    def test_all_patterns_have_phase1_signals(self):
        """Every pattern (except children with no own signals) has phase1_signals."""
        for p in PatternRegistry.list_patterns():
            if p.parent:
                continue  # Children may inherit candidacy
            assert len(p.phase1_signals) > 0, f"{p.name} has no phase1_signals"

    def test_no_pattern_uses_old_detection_signals(self):
        """Old detection_signals field should be empty on all built-in patterns."""
        for p in PatternRegistry.list_patterns():
            assert p.detection_signals == [], (
                f"{p.name} still uses old detection_signals field"
            )

    def test_hierarchy_parents_exist(self):
        """Every pattern with a parent references an existing pattern."""
        names = {p.name for p in PatternRegistry.list_patterns()}
        for p in PatternRegistry.list_patterns():
            if p.parent:
                assert p.parent in names, (
                    f"{p.name} has parent '{p.parent}' which doesn't exist"
                )

    def test_child_specificity_greater_than_parent(self):
        patterns = {p.name: p for p in PatternRegistry.list_patterns()}
        for p in patterns.values():
            if p.parent:
                parent = patterns[p.parent]
                assert p.specificity > parent.specificity, (
                    f"{p.name} (specificity={p.specificity}) should be > "
                    f"parent {p.parent} (specificity={parent.specificity})"
                )

    def test_docusaurus_openapi_is_child_of_docusaurus(self):
        p = PatternRegistry.get("docusaurus-openapi")
        assert p is not None
        assert p.parent == "docusaurus"
        assert p.specificity == 1

    def test_docusaurus_openapi_has_required_check(self):
        p = PatternRegistry.get("docusaurus-openapi")
        assert p is not None
        required = [c for c in p.phase2_checks if c.required]
        assert len(required) >= 1, "docusaurus-openapi needs at least one required Phase 2 check"

    def test_all_patterns_registered(self):
        names = {p.name for p in PatternRegistry.list_patterns()}
        expected = {
            "docusaurus", "docusaurus-openapi", "gitbook", "readthedocs",
            "mkdocs", "sphinx", "vitepress", "mintlify", "nextra",
            "swagger-ui", "redoc", "redocly-realm", "starlight",
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

    @pytest.mark.parametrize("name", [
        "docusaurus", "gitbook", "readthedocs", "mkdocs", "sphinx",
        "vitepress", "mintlify", "nextra", "swagger-ui", "redoc",
        "redocly-realm", "starlight",
    ])
    def test_pattern_has_content_selectors(self, name: str):
        p = PatternRegistry.get(name)
        assert p is not None
        assert len(p.content_selectors) > 0

    @pytest.mark.parametrize("name", [
        "docusaurus", "gitbook", "readthedocs", "mkdocs", "sphinx",
        "vitepress", "mintlify", "nextra", "swagger-ui", "redoc",
        "redocly-realm", "starlight",
    ])
    def test_pattern_has_description(self, name: str):
        p = PatternRegistry.get(name)
        assert p is not None
        assert len(p.description) > 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_pattern_definitions.py -v`
Expected: FAIL — patterns still use old `detection_signals`, no `phase1_signals`/`phase2_checks`, no hierarchy

**Step 3: Restructure all 13 pattern definitions**

Replace all pattern definitions in `registry.py` (lines 46-405). Each pattern moves from `detection_signals` to `phase1_signals` + `phase2_checks`. Only docusaurus-openapi gets `parent`/`specificity`.

The full replacement (condensed to save space — write the complete code per pattern):

```python
DOCUSAURUS_PATTERN = SitePattern(
    name="docusaurus",
    description="Docusaurus documentation sites",
    content_selectors=[
        "article.markdown",
        ".docMainContent",
        'main[class*="docMainContainer"]',
        "main .col",
        "main .container article",
        '[class*="docItemContainer"]',
    ],
    remove_selectors=[
        ".theme-doc-sidebar-container",
        '[class*="docSidebarContainer"]',
        "aside",
        'nav[aria-label="Main"]',
        ".navbar",
        ".theme-doc-breadcrumbs",
        ".pagination-nav",
        ".theme-doc-toc-mobile",
        ".theme-doc-footer",
        ".theme-edit-this-page",
        '[class*="tocCollapsible"]',
        "footer",
    ],
    requires_js=True,
    wait_selector="article.markdown",
    click_tabs_selector='.openapi-tabs__code-container [role="tab"]',
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="docusaurus", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="__docusaurus", weight=30),
        DetectionSignal(kind="html_substring", value="docMainContainer", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value="article.markdown", weight=20),
        Phase2Check(kind="css_present", value='[class*="docMainContainer"]', weight=20),
    ],
)

DOCUSAURUS_OPENAPI_PATTERN = SitePattern(
    name="docusaurus-openapi",
    description="Docusaurus sites with docusaurus-openapi-docs plugin",
    parent="docusaurus",
    specificity=1,
    content_selectors=[
        "article .theme-doc-markdown",
        "article.markdown",
        'main[class*="docMainContainer"]',
        "main .col",
        "article",
    ],
    remove_selectors=[
        ".openapi-explorer__request-form",
        ".openapi-explorer__response-container",
        ".theme-doc-sidebar-container",
        '[class*="docSidebarContainer"]',
        "aside",
        'nav[aria-label="Main"]',
        ".navbar",
        ".theme-doc-breadcrumbs",
        ".pagination-nav",
        ".theme-doc-toc-mobile",
        ".theme-doc-footer",
        ".theme-edit-this-page",
        ".breadcrumbs",
        '[class*="tocCollapsible"]',
        "footer",
    ],
    requires_js=True,
    wait_selector=".openapi-left-panel__container, article.markdown",
    wait_time_ms=500,
    click_tabs_selector='.openapi-tabs__code-container [role="tab"]',
    phase1_signals=[],  # Inherits candidacy from parent (docusaurus)
    phase2_checks=[
        Phase2Check(kind="css_present", value=".openapi-left-panel__container", weight=30, required=True),
        Phase2Check(kind="css_present", value=".openapi-schema__property", weight=20),
        Phase2Check(kind="script_src_regex", value="docusaurus-openapi|plugin-content-docs-api", weight=20),
        Phase2Check(kind="css_present", value=".openapi-explorer", weight=15),
    ],
)

GITBOOK_PATTERN = SitePattern(
    name="gitbook",
    description="GitBook documentation sites",
    content_selectors=[
        '[data-testid="page.contentEditor"]',
        ".markdown-section",
        ".page-inner",
        "main",
    ],
    remove_selectors=[
        ".book-summary",
        ".navigation",
        ".page-footer",
        '[data-testid="page.tableOfContents"]',
    ],
    requires_js=True,
    wait_selector='[data-testid="page.contentEditor"], .markdown-section',
    phase1_signals=[
        DetectionSignal(kind="html_substring", value='data-testid="page.', weight=30),
        DetectionSignal(kind="html_substring", value="gitbook", weight=25, case_sensitive=False),
        DetectionSignal(kind="url_substring", value="gitbook.io", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value='[data-testid="page.contentEditor"]', weight=20),
    ],
)

READTHEDOCS_PATTERN = SitePattern(
    name="readthedocs",
    description="Read the Docs sites",
    content_selectors=[
        '[role="main"]',
        ".document",
        ".rst-content",
        ".body",
    ],
    remove_selectors=[
        ".wy-nav-side",
        ".rst-versions",
        ".wy-breadcrumbs",
        ".headerlink",
        '[role="navigation"]',
    ],
    requires_js=False,
    phase1_signals=[
        DetectionSignal(kind="url_substring", value="readthedocs", weight=25),
        DetectionSignal(kind="url_substring", value=".rtfd.", weight=25),
        DetectionSignal(kind="html_substring", value="rst-content", weight=30),
        DetectionSignal(kind="html_substring", value="wy-nav-side", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".wy-nav-side", weight=20, required=True),
        Phase2Check(kind="css_absent", value=".sphinxsidebar", weight=15),
    ],
)

MKDOCS_PATTERN = SitePattern(
    name="mkdocs",
    description="MkDocs documentation sites",
    content_selectors=[
        '[role="main"]',
        ".md-content",
        "article",
        ".content",
    ],
    remove_selectors=[
        ".md-sidebar",
        ".md-header",
        ".md-footer",
        ".md-tabs",
        ".md-source",
    ],
    requires_js=False,
    wait_selector='[role="main"]',
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="mkdocs", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value='class="md-content"', weight=30),
        DetectionSignal(kind="html_substring", value="md-sidebar", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".md-content", weight=20),
    ],
)

SPHINX_PATTERN = SitePattern(
    name="sphinx",
    description="Sphinx documentation sites",
    content_selectors=[
        '[role="main"]',
        ".document",
        ".body",
        ".section",
    ],
    remove_selectors=[
        ".sphinxsidebar",
        ".related",
        ".footer",
        ".headerlink",
    ],
    requires_js=False,
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="sphinx", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="sphinxsidebar", weight=30),
        DetectionSignal(kind="html_substring", value="sphinx.pocoo.org", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value='[role="main"]', weight=15),
        Phase2Check(kind="css_present", value=".document", weight=15),
    ],
)

VITEPRESS_PATTERN = SitePattern(
    name="vitepress",
    description="VitePress documentation sites",
    content_selectors=[
        ".vp-doc",
        "main .content",
        ".content-container",
    ],
    remove_selectors=[
        ".VPSidebar",
        ".VPNav",
        ".VPFooter",
        ".aside",
        ".edit-link",
        ".prev-next",
    ],
    requires_js=True,
    wait_selector=".vp-doc",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="vitepress", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="vp-doc", weight=30),
        DetectionSignal(kind="html_substring", value="VPSidebar", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".vp-doc", weight=20),
    ],
)

MINTLIFY_PATTERN = SitePattern(
    name="mintlify",
    description="Mintlify documentation sites",
    content_selectors=[
        "#content-area",
        "article",
        ".prose",
        "main",
    ],
    remove_selectors=[
        "#sidebar",
        '[class*="Sidebar"]',
        "nav",
        "header",
        "footer",
        ".on-this-page",
        '[class*="TableOfContents"]',
        '[class*="Pagination"]',
        '[class*="FeedbackButtons"]',
    ],
    requires_js=True,
    wait_selector="#content-area, article",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="mintlify", weight=50, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="mintlify-", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value="#content-area", weight=20),
    ],
)

NEXTRA_PATTERN = SitePattern(
    name="nextra",
    description="Nextra (Next.js) documentation sites",
    content_selectors=[
        "article",
        ".nextra-content",
        "main .nx-prose",
        "main",
    ],
    remove_selectors=[
        "aside",
        "nav",
        ".nextra-sidebar-container",
        '[class*="nx-sidebar"]',
        ".nextra-toc",
        ".nextra-breadcrumb",
        "footer",
        ".nx-mt-auto",
    ],
    requires_js=True,
    wait_selector="article, .nextra-content",
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="nextra-content", weight=30),
        DetectionSignal(kind="html_substring", value="nx-prose", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".nextra-content", weight=20),
    ],
)

SWAGGER_UI_PATTERN = SitePattern(
    name="swagger-ui",
    description="Swagger UI API documentation",
    content_selectors=[
        ".swagger-ui",
        "#swagger-ui",
    ],
    remove_selectors=[
        ".topbar",
        ".auth-wrapper",
        ".scheme-container",
    ],
    requires_js=True,
    wait_selector=".swagger-ui .information-container, .swagger-ui .opblock",
    wait_time_ms=1000,
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="swagger-ui", weight=30),
        DetectionSignal(kind="html_substring", value="swagger-ui-bundle", weight=25),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".swagger-ui", weight=20),
        Phase2Check(kind="css_absent", value=".redoc-wrap", weight=10),
    ],
)

REDOC_PATTERN = SitePattern(
    name="redoc",
    description="Redoc API documentation",
    content_selectors=[
        ".redoc-wrap",
        "#redoc",
        "[data-role='redoc']",
    ],
    remove_selectors=[
        ".menu-content",
        '[role="navigation"]',
    ],
    requires_js=True,
    wait_selector=".redoc-wrap, .api-content",
    wait_time_ms=1000,
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="redoc-wrap", weight=30),
        DetectionSignal(kind="html_substring", value="redoc.standalone", weight=30, case_sensitive=False),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".redoc-wrap", weight=20),
        Phase2Check(kind="css_absent", value=".swagger-ui", weight=10),
    ],
)

REDOCLY_REALM_PATTERN = SitePattern(
    name="redocly-realm",
    description="Redocly Realm developer portals",
    content_selectors=[
        "main",
        "article",
        '[role="main"]',
    ],
    remove_selectors=[
        "aside",
        "nav",
        "header",
        "footer",
        '[class*="Sidebar"]',
        '[class*="Navbar"]',
        '[class*="Footer"]',
        '[class*="CopyForLlm"]',
        '[class*="Breadcrumb"]',
    ],
    requires_js=False,
    wait_selector="main",
    phase1_signals=[
        DetectionSignal(kind="html_substring", value="/runtime/browser-entry.js", weight=30),
        DetectionSignal(kind="html_substring", value="-redocly-", weight=25, case_sensitive=False),
    ],
    phase2_checks=[],
)

STARLIGHT_PATTERN = SitePattern(
    name="starlight",
    description="Starlight (Astro) documentation sites",
    content_selectors=[
        ".sl-markdown-content",
        "[data-pagefind-body]",
        "main",
    ],
    remove_selectors=[
        "nav",
        "header.header",
        ".sidebar",
        '[class*="sidebar"]',
        "starlight-toc",
        ".right-sidebar",
        "footer",
        ".pagination-links",
    ],
    requires_js=False,
    wait_selector=".sl-markdown-content",
    phase1_signals=[
        DetectionSignal(kind="meta_generator", value="starlight", weight=50, case_sensitive=False),
        DetectionSignal(kind="meta_generator", value="astro", weight=25, case_sensitive=False),
        DetectionSignal(kind="html_substring", value="sl-markdown-content", weight=30),
    ],
    phase2_checks=[
        Phase2Check(kind="css_present", value=".sl-markdown-content", weight=20),
    ],
)
```

Also update the `_patterns` dict in `PatternRegistry` class (it stays the same keys, just references the updated pattern objects — no change needed since it references the module-level variables).

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/ -v`
Expected: All PASS (all previous tests + new definition tests)

**Step 5: Commit**

```bash
git add tests/patterns/test_pattern_definitions.py src/doc_retrieval/patterns/registry.py
git commit -m "refactor: restructure all 13 patterns to use phase1_signals + phase2_checks"
```

---

### Task 9: Update patterns/__init__.py and backward compat wrappers

**Files:**
- Modify: `src/doc_retrieval/patterns/__init__.py`
- Modify: `src/doc_retrieval/patterns/registry.py`
- Test: `tests/patterns/test_backward_compat.py` (create)

**Step 1: Write the failing tests**

```python
# tests/patterns/test_backward_compat.py
"""Tests for backward compatibility wrappers."""

from doc_retrieval.patterns import Phase2Check
from doc_retrieval.patterns.registry import PatternRegistry


class TestBackwardCompat:
    def test_detect_with_confidence_wraps_two_phase(self):
        """Old API should still work."""
        html = '<html><head><meta name="generator" content="MkDocs"></head>'
        html += '<body><div class="md-content"><p>Content</p></div></body></html>'
        result = PatternRegistry.detect_with_confidence(
            "https://example.com", html
        )
        # Should detect mkdocs via the old API
        assert result is not None
        assert result.pattern.name == "mkdocs"

    def test_detect_wraps_two_phase(self):
        """Old detect() should return pattern or None."""
        html = '<html><head><meta name="generator" content="MkDocs"></head>'
        html += '<body><div class="md-content"><p>Content</p></div></body></html>'
        pattern = PatternRegistry.detect("https://example.com", html)
        assert pattern is not None
        assert pattern.name == "mkdocs"

    def test_detect_returns_none_for_unknown(self):
        result = PatternRegistry.detect(
            "https://example.com", "<html><body>Generic</body></html>"
        )
        assert result is None


class TestPhase2CheckExport:
    def test_phase2check_importable_from_patterns_package(self):
        """Phase2Check should be importable from doc_retrieval.patterns."""
        assert Phase2Check is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/patterns/test_backward_compat.py -v`
Expected: FAIL — `Phase2Check` not exported from `__init__.py`, old methods may not wrap `detect_two_phase` yet

**Step 3: Implement**

Update `src/doc_retrieval/patterns/__init__.py`:

```python
"""Site-specific extraction patterns."""

from doc_retrieval.patterns.registry import (
    DetectionResult,
    DetectionSignal,
    PatternRegistry,
    Phase2Check,
    SitePattern,
)

__all__ = [
    "DetectionResult",
    "DetectionSignal",
    "PatternRegistry",
    "Phase2Check",
    "SitePattern",
]
```

Update the `detect_with_confidence()` and `detect()` methods in `PatternRegistry` to wrap `detect_two_phase()`:

```python
@classmethod
def detect_with_confidence(
    cls, url: str, html: str
) -> DetectionResult | None:
    """Score all patterns and return the best match.

    Backward-compatible wrapper around detect_two_phase().
    """
    return cls.detect_two_phase(url, html, headers={})

@classmethod
def detect(cls, url: str, html: str) -> SitePattern | None:
    """Auto-detect site type from URL or HTML content.

    Backward-compatible wrapper around detect_two_phase().
    """
    result = cls.detect_two_phase(url, html, headers={})
    return result.pattern if result else None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/patterns/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/doc_retrieval/patterns/__init__.py src/doc_retrieval/patterns/registry.py tests/patterns/test_backward_compat.py
git commit -m "feat: add backward compat wrappers and export Phase2Check"
```

---

### Task 10: Update interactive.py

**Files:**
- Modify: `src/doc_retrieval/interactive.py` (lines 196-225, 236-292, 1236-1268)
- Test: `tests/test_interactive_detection.py` (create)

**Step 1: Write the failing tests**

```python
# tests/test_interactive_detection.py
"""Tests for interactive mode detection integration."""

import pytest

from doc_retrieval.interactive import InteractiveExtractor


class TestAnalyzeSiteHeaders:
    """Verify _analyze_site captures HTTP headers."""

    @pytest.mark.asyncio
    async def test_site_info_includes_headers(self, httpx_mock):
        """site_info dict should include 'headers' key."""
        httpx_mock.add_response(
            url="https://example.com/",
            html="<html><body>Test</body></html>",
            headers={"x-custom": "value", "content-type": "text/html"},
        )
        extractor = InteractiveExtractor()
        info = await extractor._analyze_site("https://example.com/")
        assert info is not None
        assert "headers" in info
        assert "x-custom" in info["headers"]
```

> **Note:** This test requires `pytest-asyncio` and `pytest-httpx`. If not installed: `uv pip install pytest-asyncio pytest-httpx`. If httpx_mock is not available, this test can use a simple monkeypatch instead — see alternative below.

Alternative without httpx_mock (using monkeypatch):

```python
# tests/test_interactive_detection.py
"""Tests for interactive mode detection integration."""

import pytest

from doc_retrieval.interactive import InteractiveExtractor


class _FakeResponse:
    status_code = 200
    url = "https://example.com/"
    text = "<html><body>Test</body></html>"
    headers = {"x-custom": "value", "content-type": "text/html"}

    def raise_for_status(self):
        pass


class _FakeClient:
    async def get(self, url, **kwargs):
        return _FakeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestAnalyzeSiteHeaders:
    @pytest.mark.asyncio
    async def test_site_info_includes_headers(self, monkeypatch):
        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())
        extractor = InteractiveExtractor()
        info = await extractor._analyze_site("https://example.com/")
        assert info is not None
        assert "headers" in info
        assert info["headers"]["x-custom"] == "value"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_interactive_detection.py -v`
Expected: FAIL — `headers` key not in site_info dict

**Step 3: Implement changes to interactive.py**

**Change 1:** `_analyze_site()` — capture response headers (around line 213):

In the returned dict, add:
```python
"headers": dict(response.headers),
```

So the return block becomes:
```python
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
```

**Change 2:** `_detect_or_ask_pattern()` — pass headers to `detect_two_phase()` (line 242):

Replace:
```python
result = PatternRegistry.detect_with_confidence(url, html)
```
With:
```python
headers = site_info.get("headers", {})
result = PatternRegistry.detect_two_phase(url, html, headers=headers)
```

**Change 3:** `_build_config()` — call `apply_to_config()` after building config (after line 1267):

Add at the end of `_build_config()`, before the return:
```python
if pattern:
    config = PatternRegistry.apply_to_config(pattern, config)
return config
```

So the method ends:
```python
config = AppConfig(
    base_url=url,
    # ... all existing fields ...
)
if pattern:
    config = PatternRegistry.apply_to_config(pattern, config)
return config
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_interactive_detection.py -v && pytest tests/patterns/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/doc_retrieval/interactive.py tests/test_interactive_detection.py
git commit -m "feat: wire two-phase detection and apply_to_config into interactive mode"
```

---

### Task 11: Update orchestrator.py

**Files:**
- Modify: `src/doc_retrieval/orchestrator.py` (lines 209-211, 318-341, 1067-1107)

**Step 1: Implement changes**

**Change 1:** Replace `_apply_pattern()` method (lines 1067-1107) to use `apply_to_config()`:

```python
def _apply_pattern(self, pattern: SitePattern) -> None:
    """Apply pattern settings to config via PatternRegistry.apply_to_config()."""
    parts: list[str] = []
    if pattern.content_selectors:
        parts.append(f"{len(pattern.content_selectors)} content selectors")
    if pattern.remove_selectors:
        parts.append(f"{len(pattern.remove_selectors)} remove selectors")
    if pattern.requires_js:
        parts.append("requires JS")
    if parts:
        self.console.print(
            f"[blue]Applied pattern '{pattern.name}': {', '.join(parts)}[/blue]"
        )

    self.config = PatternRegistry.apply_to_config(pattern.name, self.config)
```

**Change 2:** Auto-detection block (lines 318-341) — pass headers when available:

The fetcher returns a `FetchResult` which doesn't carry HTTP headers. For the orchestrator's auto-detection path, we keep using the backward-compatible `detect_with_confidence()` (which internally calls `detect_two_phase` with empty headers). This is acceptable because:
- The orchestrator's auto-detect fetches via the full fetcher pipeline (not raw httpx), so headers aren't easily accessible
- Interactive mode is the primary path where headers matter (it uses raw httpx)
- We can enhance this later if needed

No change to lines 318-341 needed.

**Step 2: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 3: Run linter and type checker**

Run: `ruff check src/ && mypy src/`
Expected: Clean (or only pre-existing issues)

**Step 4: Commit**

```bash
git add src/doc_retrieval/orchestrator.py
git commit -m "refactor: orchestrator uses apply_to_config() for pattern application"
```

---

### Task 12: Final integration verification

**Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

**Step 2: Run linter**

```bash
ruff check src/
```

**Step 3: Run type checker**

```bash
mypy src/
```

**Step 4: Manual smoke test**

```bash
# Verify detection works on a known site
python -c "
import asyncio
from doc_retrieval.interactive import InteractiveExtractor
# Just test the detection logic, not full interactive flow
async def test():
    ext = InteractiveExtractor()
    info = await ext._analyze_site('https://docs.pydantic.dev/')
    if info:
        from doc_retrieval.patterns import PatternRegistry
        result = PatternRegistry.detect_two_phase(
            info['final_url'], info['html'], info.get('headers', {})
        )
        if result:
            print(f'Detected: {result.pattern.name} (confidence={result.confidence:.0%})')
            print(f'Signals: {result.matched_signals}')
        else:
            print('No pattern detected')
asyncio.run(test())
"
```

**Step 5: Commit all remaining changes if any**

```bash
git status
# If any uncommitted changes remain:
git add -A && git commit -m "chore: final cleanup for pattern detection redesign"
```
