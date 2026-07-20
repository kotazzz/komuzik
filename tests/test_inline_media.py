import asyncio
from types import SimpleNamespace

from telethon import Button

from komuzik.inline_media import edit_inline_with_media


class FakeClient:
    def __init__(self):
        self.calls: list[tuple] = []

    async def edit_message(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_edit_inline_with_media_passes_empty_caption_positionally():
    """Empty caption must clear «Загрузка…»; keyword text=\"\" is dropped by Telethon."""
    client = FakeClient()
    staging = SimpleNamespace(media="audio-media", message="")

    asyncio.run(edit_inline_with_media(client, "inline-id", staging))

    assert len(client.calls) == 1
    args, kwargs = client.calls[0]
    assert args == ("inline-id", "")
    assert kwargs["file"] == "audio-media"
    assert "text" not in kwargs
    assert kwargs["buttons"] == Button.clear()


def test_edit_inline_with_media_keeps_nonempty_caption():
    client = FakeClient()
    staging = SimpleNamespace(media="video-media", message="@komuzik_bot")

    asyncio.run(edit_inline_with_media(client, "inline-id", staging))

    args, kwargs = client.calls[0]
    assert args == ("inline-id", "@komuzik_bot")
    assert kwargs["file"] == "video-media"
