"""Pipeline hooks for extensible pre/post processing at each extraction stage."""

import asyncio
import importlib
import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HookPoint(str, Enum):
    """Points in the pipeline where hooks can be registered."""

    PRE_FETCH = "pre_fetch"
    POST_FETCH = "post_fetch"
    PRE_EXTRACT = "pre_extract"
    POST_EXTRACT = "post_extract"
    PRE_CONVERT = "pre_convert"
    POST_CONVERT = "post_convert"


class Pipeline:
    """Hook registry and executor for the extraction pipeline.

    Hook signatures by point:
        pre_fetch(url: str) -> str | None
            Return modified URL, or None to skip the page.
        post_fetch(url: str, html: str) -> str
            Return modified HTML.
        pre_extract(url: str, html: str) -> str
            Return modified HTML before extraction.
        post_extract(url: str, content) -> content
            Return modified ExtractedContent.
        pre_convert(url: str, content) -> content
            Return modified ExtractedContent before conversion.
        post_convert(url: str, page) -> page
            Return modified FormattedPage.
    """

    def __init__(self) -> None:
        self._hooks: dict[HookPoint, list[Callable]] = {
            point: [] for point in HookPoint
        }

    def register(self, point: HookPoint, hook: Callable) -> None:
        """Register a hook function at a pipeline point."""
        self._hooks[point].append(hook)

    def has_hooks(self, point: HookPoint) -> bool:
        return len(self._hooks[point]) > 0

    async def run_pre_fetch(self, url: str) -> str | None:
        """Run pre_fetch hooks. Returns modified URL or None to skip."""
        for hook in self._hooks[HookPoint.PRE_FETCH]:
            try:
                result = _call_hook(hook, url)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                logger.warning(
                    "Hook %s failed at %s: %s",
                    getattr(hook, "__name__", repr(hook)),
                    HookPoint.PRE_FETCH.value,
                    e,
                )
                continue
            if result is None:
                return None
            url = result
        return url

    async def run_post_fetch(self, url: str, html: str) -> str:
        """Run post_fetch hooks. Returns modified HTML."""
        for hook in self._hooks[HookPoint.POST_FETCH]:
            try:
                result = _call_hook(hook, url, html)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                logger.warning(
                    "Hook %s failed at %s: %s",
                    getattr(hook, "__name__", repr(hook)),
                    HookPoint.POST_FETCH.value,
                    e,
                )
                continue
            html = result
        return html

    async def run_pre_extract(self, url: str, html: str) -> str:
        """Run pre_extract hooks. Returns modified HTML."""
        for hook in self._hooks[HookPoint.PRE_EXTRACT]:
            try:
                result = _call_hook(hook, url, html)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                logger.warning(
                    "Hook %s failed at %s: %s",
                    getattr(hook, "__name__", repr(hook)),
                    HookPoint.PRE_EXTRACT.value,
                    e,
                )
                continue
            html = result
        return html

    async def run_post_extract(self, url: str, content: Any) -> Any:
        """Run post_extract hooks. Returns modified ExtractedContent."""
        for hook in self._hooks[HookPoint.POST_EXTRACT]:
            try:
                result = _call_hook(hook, url, content)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                logger.warning(
                    "Hook %s failed at %s: %s",
                    getattr(hook, "__name__", repr(hook)),
                    HookPoint.POST_EXTRACT.value,
                    e,
                )
                continue
            content = result
        return content

    async def run_pre_convert(self, url: str, content: Any) -> Any:
        """Run pre_convert hooks. Returns modified ExtractedContent."""
        for hook in self._hooks[HookPoint.PRE_CONVERT]:
            try:
                result = _call_hook(hook, url, content)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                logger.warning(
                    "Hook %s failed at %s: %s",
                    getattr(hook, "__name__", repr(hook)),
                    HookPoint.PRE_CONVERT.value,
                    e,
                )
                continue
            content = result
        return content

    async def run_post_convert(self, url: str, page: Any) -> Any:
        """Run post_convert hooks. Returns modified FormattedPage."""
        for hook in self._hooks[HookPoint.POST_CONVERT]:
            try:
                result = _call_hook(hook, url, page)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                logger.warning(
                    "Hook %s failed at %s: %s",
                    getattr(hook, "__name__", repr(hook)),
                    HookPoint.POST_CONVERT.value,
                    e,
                )
                continue
            page = result
        return page

    @classmethod
    def from_config(cls, hooks_config: dict[str, list[str]]) -> "Pipeline":
        """Create a Pipeline from a config dict mapping hook points to module:function refs.

        Example config:
            {"post_fetch": ["mymodule:clean_html"], "post_convert": ["mymodule:add_meta"]}
        """
        pipeline = cls()
        for point_name, hook_refs in hooks_config.items():
            try:
                point = HookPoint(point_name)
            except ValueError:
                logger.warning("Unknown hook point: %s", point_name)
                continue
            for ref in hook_refs:
                fn = _import_hook(ref)
                if fn:
                    pipeline.register(point, fn)
                    logger.info("Registered hook %s at %s", ref, point_name)
        return pipeline


def _call_hook(hook: Callable, *args: Any) -> Any:
    """Call a hook function, handling both sync and async."""
    return hook(*args)


def _import_hook(ref: str) -> Callable | None:
    """Import a hook from a 'module:function' reference string."""
    if ":" not in ref:
        logger.warning("Invalid hook reference '%s' — use 'module:function' format", ref)
        return None
    module_path, _, func_name = ref.partition(":")
    try:
        module = importlib.import_module(module_path)
        fn = getattr(module, func_name)
        if not callable(fn):
            logger.warning("Hook %s:%s is not callable", module_path, func_name)
            return None
        return fn
    except (ImportError, AttributeError) as e:
        logger.warning("Failed to import hook %s: %s", ref, e)
        return None
