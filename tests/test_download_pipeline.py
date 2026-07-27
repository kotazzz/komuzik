"""Platform download handlers must all go through the shared pipeline."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from komuzik.handlers import BotHandlers


def _handlers_with_spy():
    handlers = BotHandlers.__new__(BotHandlers)
    handlers.bot_username = "bot"
    handlers.stats = MagicMock()
    handlers._download_and_send_content = AsyncMock()
    return handlers


def test_platform_handlers_delegate_to_shared_pipeline():
    handlers = _handlers_with_spy()
    event = MagicMock()
    url = "https://example.com/x"

    asyncio.run(handlers._handle_tiktok(event, url))
    asyncio.run(handlers._handle_hls_host(event, url))
    asyncio.run(handlers._handle_youtube_shorts(event, url))
    asyncio.run(handlers._handle_twitter(event, url))
    asyncio.run(handlers._handle_pinterest(event, url))

    assert handlers._download_and_send_content.await_count == 5

    calls = handlers._download_and_send_content.await_args_list
    kwargs_labels = [c.kwargs["log_label"] for c in calls]
    assert kwargs_labels == [
        "TikTok video",
        "hls_host video",
        "YouTube Short",
        "Twitter content",
        "Pinterest content",
    ]

    # Status / error strings stay platform-specific.
    statuses = [c.kwargs["status_text"] for c in calls]
    assert "TikTok" in statuses[0]
    assert "Twitter" in statuses[3]
    assert "Pinterest" in statuses[4]

    assert calls[4].kwargs["action"] == "document"
    assert all(c.kwargs["action"] == "video" for c in calls[:4])
