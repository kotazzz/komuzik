"""Media caption helpers based on user settings."""

from __future__ import annotations

TELEGRAM_CAPTION_LIMIT = 1024


def build_media_caption(
    *,
    bot_username: str = "",
    title: str | None = None,
    show_bot_caption: bool = True,
    show_title: bool = True,
) -> str:
    """Build a Telegram media caption from user preferences.

    Defaults: both title and bot username are enabled.
    """
    parts: list[str] = []

    if show_title:
        clean_title = (title or "").strip()
        if clean_title and clean_title.lower() != "unknown":
            parts.append(clean_title)

    if show_bot_caption and bot_username:
        parts.append(f"@{bot_username.lstrip('@')}")

    caption = "\n".join(parts).strip()
    if len(caption) <= TELEGRAM_CAPTION_LIMIT:
        return caption
    return caption[: TELEGRAM_CAPTION_LIMIT - 1] + "…"
