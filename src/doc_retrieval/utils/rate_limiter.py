"""Rate limiting for polite crawling."""

import asyncio
from time import monotonic


class RateLimiter:
    """Simple rate limiter with configurable delay between requests."""

    def __init__(self, delay_seconds: float = 1.0):
        self.delay_seconds = delay_seconds
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until enough time has passed since the last request."""
        async with self._lock:
            now = monotonic()
            elapsed = now - self._last_request_time
            wait_time = self.delay_seconds - elapsed

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self._last_request_time = monotonic()
