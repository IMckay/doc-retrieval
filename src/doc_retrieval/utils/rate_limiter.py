"""Rate limiting for polite crawling."""

import asyncio
from time import monotonic


class RateLimiter:
    """Rate limiter with semaphore-based concurrency and staggered delays.

    Ensures at most ``max_concurrent`` requests are in flight and that new
    requests start at least ``delay_seconds`` apart.
    """

    _MAX_DELAY = 5.0  # Upper bound for adaptive back-off

    def __init__(self, delay_seconds: float = 0.2, max_concurrent: int = 3):
        self.delay_seconds = delay_seconds
        self._original_delay = delay_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()
        self.backoff_count: int = 0
        self.peak_delay: float = delay_seconds

    async def acquire(self) -> None:
        """Acquire a concurrency slot, then enforce minimum delay between starts."""
        await self._semaphore.acquire()
        async with self._lock:
            now = monotonic()
            elapsed = now - self._last_request_time
            wait_time = self.delay_seconds - elapsed

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self._last_request_time = monotonic()

    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()

    def back_off(self) -> None:
        """Double the delay between requests (capped at _MAX_DELAY).

        Called when a 429 is encountered so all subsequent requests slow down.
        """
        self.delay_seconds = min(self.delay_seconds * 2, self._MAX_DELAY)
        self.backoff_count += 1
        self.peak_delay = max(self.peak_delay, self.delay_seconds)

    @property
    def is_throttled(self) -> bool:
        """Whether the current delay exceeds the originally configured value."""
        return self.delay_seconds > self._original_delay

    def ease_off(self) -> None:
        """Halve the delay back toward the original configured value.

        Called on successful fetches to gradually restore normal pace.
        """
        self.delay_seconds = max(self.delay_seconds / 2, self._original_delay)
