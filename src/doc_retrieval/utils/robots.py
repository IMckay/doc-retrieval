"""Robots.txt checking using urllib.robotparser."""

import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


class RobotsChecker:
    """Fetch and check robots.txt for a base URL."""

    def __init__(self, user_agent: str = "DocRetrieval"):
        self._user_agent = user_agent
        self._parser: RobotFileParser | None = None
        self._loaded = False
        self._disallowed_count = 0

    @property
    def disallowed_count(self) -> int:
        return self._disallowed_count

    async def load(self, base_url: str) -> bool:
        """Fetch and parse robots.txt for the site.

        Returns True if robots.txt was found and parsed.
        """
        parsed = urlparse(base_url)
        robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(robots_url)
                if response.status_code == 200:
                    self._parser = RobotFileParser()
                    self._parser.parse(response.text.splitlines())
                    self._loaded = True
                    return True
                else:
                    logger.debug("robots.txt returned %d", response.status_code)
                    return False
        except Exception as e:
            logger.debug("Failed to fetch robots.txt: %s", e)
            return False

    def is_allowed(self, url: str) -> bool:
        """Check if the URL is allowed by robots.txt.

        Returns True if no robots.txt was loaded or the URL is allowed.
        """
        if not self._loaded or not self._parser:
            return True
        allowed = self._parser.can_fetch(self._user_agent, url)
        if not allowed:
            self._disallowed_count += 1
        return allowed
