"""Downloads are bounded in time and stale slots are reclaimed."""

import asyncio

import pytest

from komuzik.download_limiter import DownloadLimiter
from komuzik.downloaders import DownloadTimeoutError
from komuzik.handlers import BotHandlers
from komuzik.user_errors import format_download_error


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter(timeout: int = 3600):
    clock = FakeClock()
    limiter = DownloadLimiter(timer=clock)
    limiter.DOWNLOAD_TIMEOUT = timeout
    limiter.ADMIN_USER_IDS = set()
    limiter.UNLIMITED_USER_IDS = set()
    limiter._yaml_concurrent = 1
    limiter._stats = None
    return limiter, clock


def test_slot_is_tracked_with_start_time():
    limiter, clock = _limiter()
    asyncio.run(limiter.start_download(7, "d1"))

    assert limiter._active_downloads[7]["d1"] == clock.now
    assert limiter.get_active_count(7) == 1


def test_stale_slot_is_released():
    """Regression: a slot whose task died locked the user out until restart."""
    limiter, clock = _limiter(timeout=3600)
    asyncio.run(limiter.start_download(7, "d1"))
    assert not limiter.can_download(7)

    clock.advance(3601)

    assert limiter.prune_stale() == 1
    assert limiter.can_download(7)
    assert limiter.get_active_count(7) == 0


def test_fresh_slot_survives_prune():
    limiter, clock = _limiter(timeout=3600)
    asyncio.run(limiter.start_download(7, "d1"))

    clock.advance(3599)

    assert limiter.prune_stale() == 0
    assert not limiter.can_download(7)


def test_prune_only_touches_expired_slots_of_same_user():
    """Admission already prunes, so the stale slot is gone by the time 'new' lands."""
    limiter, clock = _limiter(timeout=100)
    asyncio.run(limiter.start_download(7, "old"))
    clock.advance(101)

    # the stale slot must not block a new download despite max_concurrent=1
    assert asyncio.run(limiter.start_download(7, "new")) is True
    assert list(limiter._active_downloads[7]) == ["new"]
    assert limiter.prune_stale() == 0


def test_prune_drops_empty_user_entries():
    limiter, clock = _limiter(timeout=10)
    asyncio.run(limiter.start_download(7, "d1"))
    clock.advance(11)
    limiter.prune_stale()

    assert 7 not in limiter._active_downloads


def test_can_download_prunes_lazily():
    """No background task is required for correctness."""
    limiter, clock = _limiter(timeout=10)
    asyncio.run(limiter.start_download(7, "d1"))
    clock.advance(11)

    assert limiter.can_download(7)


def test_bounded_raises_download_timeout(monkeypatch):
    monkeypatch.setattr("komuzik.handlers.DOWNLOAD_TIMEOUT_SECONDS", 0.01)
    handlers = BotHandlers.__new__(BotHandlers)

    async def slow():
        await asyncio.sleep(5)

    with pytest.raises(DownloadTimeoutError):
        asyncio.run(handlers._bounded(slow()))


def test_bounded_passes_result_through():
    handlers = BotHandlers.__new__(BotHandlers)

    async def quick():
        return "/tmp/x.mp4", {"title": "T"}

    assert asyncio.run(handlers._bounded(quick())) == ("/tmp/x.mp4", {"title": "T"})


def test_timeout_gets_a_friendly_message():
    text = format_download_error(DownloadTimeoutError("download exceeded 3600s"))

    assert "слишком долго" in text
    assert "3600" not in text  # no raw internals leaked to the user


def test_other_errors_keep_their_text():
    text = format_download_error(RuntimeError("boom"), context="Ошибка:")
    assert "boom" in text
