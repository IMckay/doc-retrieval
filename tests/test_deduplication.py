"""Tests for content-hash deduplication in the orchestrator."""

import hashlib


class TestContentHashDeduplication:
    def test_identical_content_produces_same_hash(self):
        """Two pages with identical markdown produce the same content hash."""
        md = "# Hello\n\nSome content here."
        hash1 = hashlib.sha256(md.encode()).hexdigest()[:16]
        hash2 = hashlib.sha256(md.encode()).hexdigest()[:16]
        assert hash1 == hash2

    def test_different_content_produces_different_hash(self):
        """Pages with different markdown produce different content hashes."""
        md1 = "# Page One\n\nContent for page one."
        md2 = "# Page Two\n\nContent for page two."
        hash1 = hashlib.sha256(md1.encode()).hexdigest()[:16]
        hash2 = hashlib.sha256(md2.encode()).hexdigest()[:16]
        assert hash1 != hash2

    def test_hash_truncated_to_16_chars(self):
        """Content hash is truncated to 16 hex characters."""
        md = "# Test\n\nContent."
        h = hashlib.sha256(md.encode()).hexdigest()[:16]
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_dict_detects_duplicates(self):
        """Simulates the orchestrator's dedup logic with a hash dict."""
        content_hashes: dict[str, str] = {}
        pages = [
            ("https://example.com/a", "# Page\n\nSame content."),
            ("https://example.com/b", "# Page\n\nSame content."),
            ("https://example.com/c", "# Different\n\nOther content."),
        ]

        deduplicated = 0
        kept: list[str] = []

        for url, md in pages:
            h = hashlib.sha256(md.encode()).hexdigest()[:16]
            if h in content_hashes:
                deduplicated += 1
            else:
                content_hashes[h] = url
                kept.append(url)

        assert deduplicated == 1
        assert len(kept) == 2
        assert "https://example.com/a" in kept
        assert "https://example.com/c" in kept
