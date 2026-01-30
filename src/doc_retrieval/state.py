"""Extraction state persistence for incremental/resumable runs."""

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PageState(BaseModel):
    """State of a single extracted page."""

    url: str
    status: str  # "completed", "failed", "skipped"
    extracted_at: str | None = None
    error: str | None = None
    content_hash: str | None = None


class RunState(BaseModel):
    """Persistent state for an extraction run."""

    base_url: str
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None
    pages: dict[str, PageState] = Field(default_factory=dict)

    @property
    def completed_urls(self) -> set[str]:
        return {url for url, p in self.pages.items() if p.status == "completed"}

    @property
    def failed_urls(self) -> set[str]:
        return {url for url, p in self.pages.items() if p.status == "failed"}

    def mark_completed(self, url: str, content_hash: str | None = None) -> None:
        self.pages[url] = PageState(
            url=url,
            status="completed",
            extracted_at=datetime.now().isoformat(),
            content_hash=content_hash,
        )

    def mark_failed(self, url: str, error: str) -> None:
        self.pages[url] = PageState(
            url=url,
            status="failed",
            error=error,
        )

    def mark_skipped(self, url: str) -> None:
        self.pages[url] = PageState(url=url, status="skipped")

    def is_completed(self, url: str) -> bool:
        page = self.pages.get(url)
        return page is not None and page.status == "completed"


class StateManager:
    """Manages reading and writing extraction state to disk."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self._state: RunState | None = None

    def load(self, base_url: str) -> RunState:
        """Load state from disk, or create a new one."""
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._state = RunState.model_validate(data)
                logger.info(
                    "Loaded state: %d completed, %d failed",
                    len(self._state.completed_urls),
                    len(self._state.failed_urls),
                )
                return self._state
            except Exception:
                logger.warning("Failed to load state file, starting fresh", exc_info=True)

        self._state = RunState(base_url=base_url)
        return self._state

    def save(self) -> None:
        """Persist current state to disk."""
        if not self._state:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._state.model_dump(mode="json")
        self.state_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def finalize(self) -> None:
        """Mark the run as complete and save."""
        if self._state:
            self._state.completed_at = datetime.now().isoformat()
            self.save()
