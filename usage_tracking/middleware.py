import asyncio
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Awaitable, Callable, Dict, Optional


def now_ms() -> int:
    return int(time.time() * 1000)


@contextmanager
def usage_timing_context() -> Dict[str, int]:
    """Context manager returning a dict with timing metrics."""

    start = now_ms()
    data = {"start_ms": start}
    try:
        yield data
    finally:
        data["end_ms"] = now_ms()
        data["latency_ms"] = data["end_ms"] - data["start_ms"]


@asynccontextmanager
async def async_usage_timing_context() -> Dict[str, int]:
    start = now_ms()
    data = {"start_ms": start}
    try:
        yield data
    finally:
        data["end_ms"] = now_ms()
        data["latency_ms"] = data["end_ms"] - data["start_ms"]


async def wrap_async_handler(
    handler: Callable[..., Awaitable[Any]],
    before: Callable[[], Dict[str, Any]],
    after: Callable[[Dict[str, Any], Optional[BaseException]], Awaitable[None]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Wrap async handlers to capture latency and ensure usage tracking is fire-and-forget."""

    error: Optional[BaseException] = None
    context = before()
    start = now_ms()
    try:
        return await handler(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001
        error = exc
        raise
    finally:
        context["latencyMs"] = now_ms() - start
        await after(context, error)


def wrap_sync_handler(
    handler: Callable[..., Any],
    before: Callable[[], Dict[str, Any]],
    after: Callable[[Dict[str, Any], Optional[BaseException]], None],
    *args: Any,
    **kwargs: Any,
) -> Any:
    error: Optional[BaseException] = None
    context = before()
    start = now_ms()
    try:
        return handler(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001
        error = exc
        raise
    finally:
        context["latencyMs"] = now_ms() - start
        after(context, error)


def run_fire_and_forget(coro: Awaitable[None]) -> None:
    """Best-effort fire-and-forget async call for usage writes."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    loop.create_task(coro)
