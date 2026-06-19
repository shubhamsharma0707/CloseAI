"""
utils/compat.py
Compatibility shims for Python 3.10 / 3.11+ differences.
"""
import sys

if sys.version_info >= (3, 11):
    # asyncio.timeout is a native async context manager in 3.11+
    from asyncio import timeout as async_timeout
else:
    # Backport: wrap asyncio.wait_for so it behaves like a context manager
    import asyncio
    from contextlib import asynccontextmanager
    from typing import AsyncGenerator

    @asynccontextmanager
    async def async_timeout(delay: float) -> AsyncGenerator[None, None]:
        """
        Drop-in async context manager replacement for asyncio.timeout(delay).
        Raises asyncio.TimeoutError on expiry, matching 3.11 behaviour.
        """
        loop = asyncio.get_event_loop()
        task = asyncio.current_task()
        handle = loop.call_later(delay, task.cancel) if task else None
        try:
            yield
        except asyncio.CancelledError:
            raise asyncio.TimeoutError()
        finally:
            if handle:
                handle.cancel()


__all__ = ["async_timeout"]
