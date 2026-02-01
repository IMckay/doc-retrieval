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
        """Same score across families -- higher specificity wins."""
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
