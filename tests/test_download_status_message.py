"""The transient «Загрузка…» status must disappear on success and on failure."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from komuzik.handlers import BotHandlers
from komuzik.repository import UserSettings


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeEvent:
    def __init__(self):
        self.sender_id = 42
        self.sender = SimpleNamespace(username="tester")
        self.chat_id = 42
        self.is_group = False
        self.responses: list[FakeMessage] = []
        self.client = self

    @asynccontextmanager
    async def action(self, _chat_id, _action):
        yield

    async def respond(self, text, **_kwargs):
        msg = FakeMessage(text)
        self.responses.append(msg)
        return msg


def _make_handlers():
    handlers = BotHandlers.__new__(BotHandlers)
    handlers.bot_username = "komuzik_bot"

    stats = MagicMock()
    stats.get_user_settings.return_value = UserSettings(user_id=42)
    handlers.stats = stats

    limiter = MagicMock()

    async def _start(_uid, _did):
        return True

    async def _finish(_uid, _did):
        return None

    limiter.start_download = _start
    limiter.finish_download = _finish
    handlers.download_limiter = limiter
    return handlers


def _run_download(*, download, send):
    handlers = _make_handlers()
    event = FakeEvent()

    asyncio.run(
        handlers._download_and_send_content(
            event,
            "https://youtu.be/abcdefghijk",
            status_text="Загрузка видео... Пожалуйста, подождите.",
            error_context="Произошла ошибка при обработке видео:",
            download=download,
            send=send,
            track=lambda *_a, **_k: None,
            action="video",
            log_label="видео",
        )
    )
    return event


def test_status_message_deleted_on_success():
    async def download():
        return "/tmp/nonexistent/video.mp4", {"title": "T"}

    async def send(*_args, **_kwargs):
        return None

    event = _run_download(download=download, send=send)

    status = event.responses[0]
    assert status.text.startswith("Загрузка видео")
    assert status.deleted is True


def test_status_message_deleted_on_download_failure():
    """Regression: the status used to survive errors, leaving the bot looking stuck."""

    async def download():
        raise RuntimeError("boom")

    async def send(*_args, **_kwargs):
        raise AssertionError("send must not be reached")

    event = _run_download(download=download, send=send)

    status = event.responses[0]
    assert status.deleted is True
    # the user still gets an error message instead of a silent failure
    assert any("boom" in m.text for m in event.responses[1:])


def test_status_message_deleted_on_send_failure():
    async def download():
        return "/tmp/nonexistent/video.mp4", {"title": "T"}

    async def send(*_args, **_kwargs):
        raise RuntimeError("upload rejected")

    event = _run_download(download=download, send=send)

    assert event.responses[0].deleted is True
    assert any("upload rejected" in m.text for m in event.responses[1:])


def test_discard_status_tolerates_delete_failure():
    class Stubborn:
        async def delete(self):
            raise RuntimeError("message already gone")

    # must not propagate — it runs inside finally
    asyncio.run(BotHandlers._discard_status(Stubborn()))
    asyncio.run(BotHandlers._discard_status(None))
