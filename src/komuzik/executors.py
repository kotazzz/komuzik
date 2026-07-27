"""Dedicated thread pools for the bot's blocking workloads.

Everything blocking used to go to ``run_in_executor(None, ...)``, i.e. the single
default ``ThreadPoolExecutor`` sized ``min(32, cpu_count + 4)``. On a 2-core VPS
that is 6 threads shared by yt-dlp downloads, ffmpeg/ffprobe, gallery-dl, Pillow
rendering and search enrichment — and ``enrich_youtube_search_stats`` alone fires
one full extraction per search hit at once. A couple of playlist downloads plus
one «🖼 Превью» press was enough to exhaust the pool and stall every other
handler behind it.

Splitting by workload means a saturated download queue can no longer block a
stats render, and vice versa. Sizes are deliberately small: these are all
IO/subprocess bound, and unbounded parallelism just multiplies memory and disk
pressure.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config_loader import ConfigLoader

logger = logging.getLogger(__name__)

_settings: dict[str, Any] = ConfigLoader().get_section("executors")

DOWNLOAD_WORKERS = int(_settings.get("download_workers", 4))
MEDIA_WORKERS = int(_settings.get("media_workers", 4))
RENDER_WORKERS = int(_settings.get("render_workers", 2))
ENRICH_CONCURRENCY = int(_settings.get("enrich_concurrency", 4))

#: yt-dlp extraction and downloading, playlist listing.
download_executor = ThreadPoolExecutor(
    max_workers=DOWNLOAD_WORKERS, thread_name_prefix="komuzik-dl"
)

#: ffprobe / ffmpeg / gallery-dl subprocesses.
media_executor = ThreadPoolExecutor(max_workers=MEDIA_WORKERS, thread_name_prefix="komuzik-media")

#: Pillow rendering and thumbnail fetching.
render_executor = ThreadPoolExecutor(
    max_workers=RENDER_WORKERS, thread_name_prefix="komuzik-render"
)

_ALL = (download_executor, media_executor, render_executor)

# Lazily created: asyncio.Semaphore must be built inside a running loop.
_enrich_holder: list[asyncio.Semaphore] = []


def enrich_semaphore() -> asyncio.Semaphore:
    """Bound how many search-result enrichments run at once."""
    if not _enrich_holder:
        _enrich_holder.append(asyncio.Semaphore(ENRICH_CONCURRENCY))
    return _enrich_holder[0]


async def run_download(func: Any, /, *args: Any) -> Any:
    """Run a blocking download-ish callable on the download pool."""
    return await asyncio.get_running_loop().run_in_executor(download_executor, func, *args)


async def run_media(func: Any, /, *args: Any) -> Any:
    """Run a blocking ffmpeg/ffprobe/gallery-dl callable on the media pool."""
    return await asyncio.get_running_loop().run_in_executor(media_executor, func, *args)


async def run_render(func: Any, /, *args: Any) -> Any:
    """Run a blocking Pillow render on the render pool."""
    return await asyncio.get_running_loop().run_in_executor(render_executor, func, *args)


def shutdown(*, wait: bool = False) -> None:
    """Stop all pools. ``wait=False`` keeps shutdown from hanging on a stuck download."""
    for executor in _ALL:
        executor.shutdown(wait=wait, cancel_futures=True)
    logger.info("Thread pools shut down (wait=%s)", wait)
