"""Helpers for Telegram inline result thumbnails."""

from __future__ import annotations

from telethon.tl.types import DocumentAttributeImageSize, InputWebDocument


def input_web_thumb(
    url: str,
    *,
    width: int = 480,
    height: int = 360,
) -> InputWebDocument:
    """Build InputWebDocument thumb for InlineBuilder.article."""
    return InputWebDocument(
        url=url,
        size=max(width * height, 1),
        mime_type="image/jpeg",
        attributes=[DocumentAttributeImageSize(w=width, h=height)],
    )
