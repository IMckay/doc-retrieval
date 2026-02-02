"""Tests for LLMFormatter markdown cleanup patterns."""

from doc_retrieval.converter.llm_formatter import LLMFormatter


class TestMarkdownCleanupPatterns:
    def test_no_patterns_passthrough(self):
        """Without cleanup patterns, markdown passes through unchanged (modulo default cleanup)."""
        fmt = LLMFormatter(include_metadata=False, include_toc=False)
        md = "# Hello World\n\nSome content here."
        # format_page not needed; test _clean_markdown directly
        result = fmt._clean_markdown(md)
        assert "Hello World" in result
        assert "Some content" in result

    def test_pattern_compilation(self):
        """Patterns are compiled into regex objects."""
        patterns = [r"(?m)^REMOVE_ME$", r"(?m)(keep)\s+discard"]
        fmt = LLMFormatter(markdown_cleanup_patterns=patterns)
        assert len(fmt._cleanup_patterns) == 2
        # First has no groups -> replacement is ""
        assert fmt._cleanup_patterns[0][1] == ""
        # Second has a group -> replacement is r"\1"
        assert fmt._cleanup_patterns[1][1] == r"\1"

    def test_format_a_toolbar_fused_heading(self):
        """FORMAT A: toolbar text fused onto heading line is stripped."""
        patterns = [r"(?m)(^#{1,6}\s+.+?)\s+Copy\s+-\s+Copy for LLM\b.*$"]
        fmt = LLMFormatter(markdown_cleanup_patterns=patterns)
        md = "## List Contacts Copy - Copy for LLM\n\nSome API docs."
        result = fmt._clean_markdown(md)
        assert "## List Contacts" in result
        assert "Copy - Copy for LLM" not in result
        assert "Some API docs" in result

    def test_format_b_standalone_toolbar_block(self):
        """FORMAT B: standalone toolbar block is removed."""
        patterns = [
            (
                r"(?m)^Copy\n\n- Copy for LLM\n"
                r"(?:\n\s+Copy page as Markdown[^\n]*\n)*"
                r"(?:- \[(?:View as Markdown|Open in ChatGPT|Open in Claude)\b[^\n]*\n)*"
                r"(?:- Connect to (?:Cursor|VS Code)\b[^\n]*\n)*"
            ),
        ]
        fmt = LLMFormatter(markdown_cleanup_patterns=patterns)
        md = (
            "## List Contacts\n\n"
            "Copy\n\n- Copy for LLM\n"
            "- [View as Markdown](https://example.com)\n"
            "- [Open in ChatGPT](https://example.com)\n"
            "\nSome API docs."
        )
        result = fmt._clean_markdown(md)
        assert "Copy for LLM" not in result
        assert "View as Markdown" not in result
        assert "Some API docs" in result

    def test_was_this_page_helpful_removed(self):
        """'Was this page helpful?' heading is removed."""
        patterns = [r"(?m)^#{1,6}\s+Was this page helpful\?\s*$"]
        fmt = LLMFormatter(markdown_cleanup_patterns=patterns)
        md = "## API Reference\n\nContent here.\n\n## Was this page helpful?\n"
        result = fmt._clean_markdown(md)
        assert "API Reference" in result
        assert "Was this page helpful?" not in result

    def test_multiple_patterns_applied_in_order(self):
        """All patterns are applied sequentially."""
        patterns = [
            r"(?m)(^#{1,6}\s+.+?)\s+Copy\s+-\s+Copy for LLM\b.*$",
            r"(?m)^#{1,6}\s+Was this page helpful\?\s*$",
        ]
        fmt = LLMFormatter(markdown_cleanup_patterns=patterns)
        md = (
            "## Endpoint Copy - Copy for LLM\n\n"
            "Content.\n\n"
            "## Was this page helpful?\n"
        )
        result = fmt._clean_markdown(md)
        assert "## Endpoint" in result
        assert "Copy - Copy for LLM" not in result
        assert "Was this page helpful?" not in result
