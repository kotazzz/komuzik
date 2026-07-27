"""Dedicated executors must isolate download and render workloads."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from komuzik import executors
from komuzik.executors import enrich_semaphore, run_download, run_media, run_render


def test_pools_are_distinct():
    assert executors.download_executor is not executors.media_executor
    assert executors.media_executor is not executors.render_executor
    assert executors.download_executor is not executors.render_executor


def test_pool_sizes_match_defaults():
    assert executors.download_executor._max_workers == executors.DOWNLOAD_WORKERS
    assert executors.media_executor._max_workers == executors.MEDIA_WORKERS
    assert executors.render_executor._max_workers == executors.RENDER_WORKERS


def _thread_name() -> str:
    return threading.current_thread().name


@pytest.mark.parametrize(
    ("runner", "prefix"),
    [
        (run_download, "komuzik-dl"),
        (run_media, "komuzik-media"),
        (run_render, "komuzik-render"),
    ],
)
def test_runner_uses_named_pool(runner, prefix):
    name = asyncio.run(runner(_thread_name))
    assert name.startswith(prefix)


def test_enrich_semaphore_bounds_concurrency(monkeypatch):
    monkeypatch.setattr(executors, "ENRICH_CONCURRENCY", 2)
    # Force a fresh semaphore with the patched limit
    monkeypatch.setattr(executors, "_enrich_holder", [])

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal active, peak
        async with enrich_semaphore():
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1

    async def run():
        await asyncio.gather(*[worker() for _ in range(8)])

    asyncio.run(run())
    assert peak == 2


def test_saturated_download_pool_does_not_block_render():
    """The whole point of the split: a full download queue must leave render free."""
    # Use tiny private pools so the test stays fast and deterministic
    download_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-dl")
    render_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-render")

    async def blocked_download():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(download_pool, time.sleep, 0.3)

    async def quick_render():
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        await loop.run_in_executor(render_pool, lambda: None)
        return time.monotonic() - started

    async def run():
        download_task = asyncio.create_task(blocked_download())
        await asyncio.sleep(0.02)  # let the download grab its only worker
        render_elapsed = await quick_render()
        await download_task
        return render_elapsed

    try:
        elapsed = asyncio.run(run())
    finally:
        download_pool.shutdown(wait=False, cancel_futures=True)
        render_pool.shutdown(wait=False, cancel_futures=True)

    # If they shared one worker, render would wait ~0.3s behind sleep
    assert elapsed < 0.15
