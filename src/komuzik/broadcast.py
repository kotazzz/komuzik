"""Throttled admin broadcast with FloodWait / PeerFlood handling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    InputUserDeactivatedError,
    PeerFloodError,
    UserIsBlockedError,
    UserPrivacyRestrictedError,
)

logger = logging.getLogger(__name__)

# Permanent delivery failures — skip the recipient, keep going.
_PERMANENT_SEND_ERRORS = (
    UserIsBlockedError,
    InputUserDeactivatedError,
    UserPrivacyRestrictedError,
    ChatWriteForbiddenError,
    ValueError,
    TypeError,
)


@dataclass
class BroadcastResult:
    sent: int = 0
    failed: int = 0
    cancelled: bool = False
    aborted_by_flood: bool = False
    flood_waits: int = 0
    total: int = 0


@dataclass
class BroadcastControl:
    """Mutable cancel flag shared with the cancel-button callback."""

    cancel_requested: bool = False


@dataclass
class BroadcastConfig:
    delay_seconds: float = 0.07
    progress_every: int = 25
    max_flood_wait_seconds: float = 120.0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> BroadcastConfig:
        data = raw or {}
        return cls(
            delay_seconds=float(data.get("delay_seconds", 0.07)),
            progress_every=max(1, int(data.get("progress_every", 25))),
            max_flood_wait_seconds=float(data.get("max_flood_wait_seconds", 120)),
        )


ProgressCallback = Callable[[BroadcastResult], Awaitable[None]]
SendCallback = Callable[[int], Awaitable[None]]
SleepCallback = Callable[[float], Awaitable[Any]]


async def broadcast_messages(
    send: SendCallback,
    user_ids: Sequence[int],
    *,
    config: BroadcastConfig | None = None,
    control: BroadcastControl | None = None,
    on_progress: ProgressCallback | None = None,
    sleep: SleepCallback = asyncio.sleep,
) -> BroadcastResult:
    """Send ``message`` to each user with pacing and flood handling.

    ``send(user_id)`` performs one delivery attempt. On ``FloodWaitError`` the
    wait is honoured (capped) and the same user is retried; on ``PeerFloodError``
    the whole broadcast stops so Telegram does not escalate the ban.
    """
    cfg = config or BroadcastConfig()
    ctrl = control or BroadcastControl()
    result = BroadcastResult(total=len(user_ids))

    for index, user_id in enumerate(user_ids):
        if ctrl.cancel_requested:
            result.cancelled = True
            break

        delivered = False
        while not delivered:
            if ctrl.cancel_requested:
                result.cancelled = True
                break
            try:
                await send(user_id)
                result.sent += 1
                delivered = True
            except FloodWaitError as e:
                wait = float(getattr(e, "seconds", 0) or 0)
                capped = min(wait, cfg.max_flood_wait_seconds)
                result.flood_waits += 1
                logger.warning(
                    "FloodWait %ss (capped to %ss) during broadcast to %s",
                    wait,
                    capped,
                    user_id,
                )
                if wait > cfg.max_flood_wait_seconds:
                    # Absurd wait — treat as failure for this user and continue.
                    result.failed += 1
                    delivered = True
                else:
                    await sleep(capped)
            except PeerFloodError as e:
                logger.error("PeerFlood during broadcast to %s: %s — aborting", user_id, e)
                result.failed += 1
                result.aborted_by_flood = True
                return result
            except _PERMANENT_SEND_ERRORS as e:
                logger.warning("Permanent send failure for %s: %s", user_id, e)
                result.failed += 1
                delivered = True
            except Exception as e:
                logger.warning("Failed to send broadcast to %s: %s", user_id, e)
                result.failed += 1
                delivered = True

        if result.cancelled:
            break

        processed = result.sent + result.failed
        if on_progress and (
            processed == result.total
            or processed % cfg.progress_every == 0
            or processed == 1
        ):
            await on_progress(result)

        # Pace between recipients (skip after the last one).
        if (
            index + 1 < len(user_ids)
            and not result.cancelled
            and not result.aborted_by_flood
            and cfg.delay_seconds > 0
        ):
            await sleep(cfg.delay_seconds)

    return result


def format_broadcast_progress(result: BroadcastResult) -> str:
    """Human-readable status line for the admin progress message."""
    done = result.sent + result.failed
    line = f"📢 Рассылка: {done}/{result.total} (✅ {result.sent} · ⚠️ {result.failed})"
    if result.flood_waits:
        line += f" · ⏳ FloodWait×{result.flood_waits}"
    return line


def format_broadcast_result(result: BroadcastResult) -> str:
    """Final summary shown when the broadcast finishes."""
    if result.cancelled:
        head = "⏹ Рассылка остановлена"
    elif result.aborted_by_flood:
        head = "🛑 Рассылка прервана (PeerFlood)"
    else:
        head = "✅ Рассылка завершена"

    lines = [
        head,
        f"Отправлено: {result.sent}/{result.total}",
    ]
    if result.failed:
        lines.append(f"Не удалось: {result.failed}")
    if result.flood_waits:
        lines.append(f"FloodWait: {result.flood_waits}")
    return "\n".join(lines)
