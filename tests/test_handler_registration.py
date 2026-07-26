"""Registration-level guards for message handlers."""

import asyncio
from types import SimpleNamespace

import pytest

from komuzik.handlers import BotHandlers


def _run(coro):
    return asyncio.run(coro)


def test_requires_sender_drops_anonymous_message():
    """Anonymous group admins have sender_id=None — the handler must not run."""
    called = []

    async def handler(event):
        called.append(event)

    guarded = BotHandlers._requires_sender(handler)
    _run(guarded(SimpleNamespace(sender_id=None, chat_id=-100123)))

    assert called == []


def test_requires_sender_passes_normal_message():
    called = []

    async def handler(event):
        called.append(event.sender_id)

    guarded = BotHandlers._requires_sender(handler)
    _run(guarded(SimpleNamespace(sender_id=42, chat_id=42)))

    assert called == [42]


def test_requires_sender_drops_event_without_attribute():
    """Service updates may not carry sender_id at all."""
    called = []

    async def handler(event):
        called.append(event)

    guarded = BotHandlers._requires_sender(handler)
    _run(guarded(SimpleNamespace(chat_id=1)))

    assert called == []


def test_get_user_info_still_guards_invariant():
    """_get_user_info stays strict; the registration guard is what prevents the raise."""
    handlers = BotHandlers.__new__(BotHandlers)
    event = SimpleNamespace(sender_id=None, sender=None)

    with pytest.raises(ValueError, match="sender_id"):
        handlers._get_user_info(event)
