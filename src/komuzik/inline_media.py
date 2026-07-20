"""Helpers for inline staging in user PM and editing via-messages."""

from __future__ import annotations

import logging
from typing import Any

from telethon.errors import (
    ChatWriteForbiddenError,
    InputUserDeactivatedError,
    PeerFloodError,
    UserIsBlockedError,
    UserPrivacyRestrictedError,
)
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from .config import DEFAULT_VIDEO_HEIGHT, DEFAULT_VIDEO_WIDTH

logger = logging.getLogger(__name__)

PM_UNAVAILABLE_MESSAGE = (
    "❌ Не могу отправить файл в ваш ЛС.\n\n"
    "Откройте бота и нажмите /start (или уберите бота из чёрного списка), "
    "затем повторите inline-запрос."
)

INLINE_PM_ERRORS = (
    UserIsBlockedError,
    InputUserDeactivatedError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    ChatWriteForbiddenError,
    ValueError,
    TypeError,
)


async def stage_media_to_user(
    client: Any,
    user_id: int,
    file_path: str,
    media_kind: str,
    metadata: dict,
    bot_username: str = "",
):
    """Send media to user PM for file_id staging. Returns the sent Message."""
    caption = f"@{bot_username}" if bot_username else ""

    if media_kind == "video":
        video_attr = DocumentAttributeVideo(
            duration=metadata.get("duration", 0),
            w=metadata.get("width", DEFAULT_VIDEO_WIDTH),
            h=metadata.get("height", DEFAULT_VIDEO_HEIGHT),
            supports_streaming=True,
        )
        return await client.send_file(
            user_id,
            file_path,
            caption=caption,
            supports_streaming=True,
            attributes=[video_attr],
        )

    if media_kind == "audio":
        audio_attr = DocumentAttributeAudio(
            duration=metadata.get("duration", 0),
            title=metadata.get("track", "Unknown"),
            performer=metadata.get("artist", "Unknown Artist"),
        )
        return await client.send_file(
            user_id,
            file_path,
            caption=caption,
            attributes=[audio_attr],
        )

    return await client.send_file(user_id, file_path, caption=caption)


async def edit_inline_with_media(client: Any, inline_msg_id, sent_message) -> None:
    """Replace inline placeholder with staged media (must already be on Telegram servers)."""
    caption = sent_message.message or ""
    await client.edit_message(inline_msg_id, file=sent_message.media, text=caption)


async def edit_inline_text(client: Any, inline_msg_id, text: str) -> None:
    """Replace inline placeholder with an error/status text."""
    await client.edit_message(inline_msg_id, text)


async def delete_staging_message(client: Any, user_id: int, message) -> None:
    """Best-effort delete of the PM staging message."""
    try:
        await client.delete_messages(user_id, [message.id])
    except Exception as e:
        logger.warning(f"Failed to delete staging message for {user_id}: {e}")


def is_pm_unavailable_error(error: BaseException) -> bool:
    """Return True if the error means we cannot write to the user's PM."""
    if isinstance(error, INLINE_PM_ERRORS):
        return True
    message = str(error).lower()
    markers = (
        "cannot find any entity",
        "could not find the input entity",
        "user is blocked",
        "bot was blocked",
        "peer id invalid",
        "write forbidden",
    )
    return any(marker in message for marker in markers)
