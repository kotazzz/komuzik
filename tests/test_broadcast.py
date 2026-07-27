"""Throttled broadcast: FloodWait, PeerFlood, cancel, pacing."""

import asyncio
from unittest.mock import AsyncMock

from telethon.errors import FloodWaitError, PeerFloodError, UserIsBlockedError

from komuzik.broadcast import (
    BroadcastConfig,
    BroadcastControl,
    BroadcastResult,
    broadcast_messages,
    format_broadcast_progress,
    format_broadcast_result,
)


def test_broadcast_paces_and_counts_success():
    sent: list[int] = []
    sleeps: list[float] = []

    async def send(uid: int) -> None:
        sent.append(uid)

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        broadcast_messages(
            send,
            [1, 2, 3],
            config=BroadcastConfig(delay_seconds=0.05, progress_every=10),
            sleep=sleep,
        )
    )

    assert sent == [1, 2, 3]
    assert result.sent == 3
    assert result.failed == 0
    assert sleeps == [0.05, 0.05]  # no delay after last


def test_flood_wait_retries_same_user():
    attempts: list[int] = []

    async def send(uid: int) -> None:
        attempts.append(uid)
        if len(attempts) == 1:
            raise FloodWaitError(request=None, capture=2)

    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        broadcast_messages(
            send,
            [10],
            config=BroadcastConfig(delay_seconds=0, max_flood_wait_seconds=30),
            sleep=sleep,
        )
    )

    assert attempts == [10, 10]
    assert result.sent == 1
    assert result.flood_waits == 1
    assert sleeps == [2.0]


def test_oversized_flood_wait_skips_user():
    async def send(_uid: int) -> None:
        raise FloodWaitError(request=None, capture=999)

    result = asyncio.run(
        broadcast_messages(
            send,
            [1, 2],
            config=BroadcastConfig(delay_seconds=0, max_flood_wait_seconds=10),
            sleep=AsyncMock(),
        )
    )

    assert result.sent == 0
    assert result.failed == 2
    assert result.flood_waits == 2
    assert not result.aborted_by_flood


def test_peer_flood_aborts_remaining():
    sent: list[int] = []

    async def send(uid: int) -> None:
        if uid == 2:
            raise PeerFloodError(request=None)
        sent.append(uid)

    result = asyncio.run(
        broadcast_messages(
            send,
            [1, 2, 3],
            config=BroadcastConfig(delay_seconds=0),
            sleep=AsyncMock(),
        )
    )

    assert sent == [1]
    assert result.sent == 1
    assert result.failed == 1
    assert result.aborted_by_flood
    assert result.total == 3


def test_cancel_stops_midway():
    control = BroadcastControl()
    sent: list[int] = []

    async def send(uid: int) -> None:
        sent.append(uid)
        if uid == 2:
            control.cancel_requested = True

    result = asyncio.run(
        broadcast_messages(
            send,
            [1, 2, 3, 4],
            config=BroadcastConfig(delay_seconds=0),
            control=control,
            sleep=AsyncMock(),
        )
    )

    assert sent == [1, 2]
    assert result.cancelled
    assert result.sent == 2


def test_blocked_user_counts_as_failed():
    async def send(uid: int) -> None:
        if uid == 2:
            raise UserIsBlockedError(request=None)

    result = asyncio.run(
        broadcast_messages(
            send,
            [1, 2, 3],
            config=BroadcastConfig(delay_seconds=0),
            sleep=AsyncMock(),
        )
    )

    assert result.sent == 2
    assert result.failed == 1


def test_progress_callback_fires():
    snapshots: list[BroadcastResult] = []

    async def send(_uid: int) -> None:
        pass

    async def on_progress(result: BroadcastResult) -> None:
        snapshots.append(
            BroadcastResult(
                sent=result.sent,
                failed=result.failed,
                total=result.total,
            )
        )

    asyncio.run(
        broadcast_messages(
            send,
            list(range(5)),
            config=BroadcastConfig(delay_seconds=0, progress_every=2),
            on_progress=on_progress,
            sleep=AsyncMock(),
        )
    )

    # first + every 2 + final
    assert [s.sent for s in snapshots] == [1, 2, 4, 5]


def test_format_helpers():
    running = BroadcastResult(sent=3, failed=1, total=10, flood_waits=2)
    progress = format_broadcast_progress(running)
    assert "4/10" in progress
    assert "FloodWait×2" in progress

    done = BroadcastResult(sent=9, failed=1, total=10, cancelled=True)
    text = format_broadcast_result(done)
    assert "остановлена" in text
    assert "9/10" in text

    flooded = BroadcastResult(sent=2, failed=1, total=5, aborted_by_flood=True)
    assert "PeerFlood" in format_broadcast_result(flooded)


def test_config_from_mapping():
    cfg = BroadcastConfig.from_mapping(
        {"delay_seconds": 0.2, "progress_every": 50, "max_flood_wait_seconds": 60}
    )
    assert cfg.delay_seconds == 0.2
    assert cfg.progress_every == 50
    assert cfg.max_flood_wait_seconds == 60
    assert BroadcastConfig.from_mapping(None).delay_seconds == 0.07
