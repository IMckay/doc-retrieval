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
