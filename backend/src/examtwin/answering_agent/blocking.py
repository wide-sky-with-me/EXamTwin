from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TypeVar

ResultT = TypeVar("ResultT")

_WORKER_COUNT = 8
_SUBMISSION_LIMIT = 16
_EXECUTOR = ThreadPoolExecutor(
    max_workers=_WORKER_COUNT,
    thread_name_prefix="answering-tool",
)
_SUBMISSION_SLOTS = threading.BoundedSemaphore(_SUBMISSION_LIMIT)


def _invoke_with_slot(
    function: Callable[..., ResultT],
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> ResultT:
    try:
        return function(*args, **kwargs)
    finally:
        _SUBMISSION_SLOTS.release()


def _consume_late_outcome(future: asyncio.Future[object]) -> None:
    """Retrieve a timed-out call's eventual exception without changing its outcome."""

    if future.cancelled():
        return
    future.exception()


async def run_blocking_bounded(
    function: Callable[..., ResultT],
    *args: object,
    timeout: float,
    **kwargs: object,
) -> ResultT:
    """Run blocking provider code in a shared, capacity-bounded executor."""
    loop = asyncio.get_running_loop()
    if not _SUBMISSION_SLOTS.acquire(blocking=False):
        raise RuntimeError("blocking answering tool capacity is exhausted")
    try:
        outcome = loop.run_in_executor(
            _EXECUTOR,
            partial(_invoke_with_slot, function, args, kwargs),
        )
    except BaseException:
        _SUBMISSION_SLOTS.release()
        raise

    try:
        return await asyncio.wait_for(asyncio.shield(outcome), timeout=timeout)
    except TimeoutError:
        try:
            outcome.add_done_callback(_consume_late_outcome)
        except RuntimeError:
            pass
        raise TimeoutError(
            f"blocking answering tool exceeded its {timeout:.0f}s timeout"
        ) from None
