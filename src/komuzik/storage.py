"""Staging media in an admin storage group and copying to users."""

from __future__ import annotations

import logging
from typing import Any

from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from .captions import build_media_caption
from .config import DEFAULT_VIDEO_HEIGHT, DEFAULT_VIDEO_WIDTH

logger = logging.getLogger(__name__)


async def stage_media(
    client: Any,
    storage_chat_id: int,
    file_path: str,
    media_kind: str,
    metadata: dict,
    bot_username: str = "",
    *,
    show_bot_caption: bool = True,
    show_title: bool = True,
):
    title = metadata.get("title") or metadata.get("track")
    caption = build_media_caption(
        bot_username=bot_username,
        title=title if isinstance(title, str) else None,
        show_bot_caption=show_bot_caption,
        show_title=show_title,
    )

    if media_kind == "video":
        attrs = [
            DocumentAttributeVideo(
                duration=int(metadata.get("duration") or 0),
                w=int(metadata.get("width") or DEFAULT_VIDEO_WIDTH),
                h=int(metadata.get("height") or DEFAULT_VIDEO_HEIGHT),
                supports_streaming=True,
            )
        ]
        return await client.send_file(
            storage_chat_id,
            file_path,
            caption=caption,
            supports_streaming=True,
            attributes=attrs,
        )

    if media_kind == "audio":
        attrs = [
            DocumentAttributeAudio(
                duration=int(metadata.get("duration") or 0),
                title=metadata.get("track", "Unknown"),
                performer=metadata.get("artist", "Unknown Artist"),
            )
        ]
        return await client.send_file(
            storage_chat_id,
            file_path,
            caption=caption,
            attributes=attrs,
            force_document=False,
        )

    return await client.send_file(storage_chat_id, file_path, caption=caption)


async def copy_messages_to_chat(client: Any, dest_chat_id: int, messages: list) -> None:
    """Re-send media by file_id without a Forwarded-from header."""
    for msg in messages:
        if msg is None or msg.media is None:
            continue
        caption = msg.message or ""
        await client.send_file(dest_chat_id, msg.media, caption=caption)


async def delete_staging(client: Any, storage_chat_id: int, messages: list) -> None:
    ids = [m.id for m in messages if m is not None]
    if not ids:
        return
    try:
        await client.delete_messages(storage_chat_id, ids)
    except Exception as e:
        logger.warning(f"Failed to delete staging messages in {storage_chat_id}: {e}")
